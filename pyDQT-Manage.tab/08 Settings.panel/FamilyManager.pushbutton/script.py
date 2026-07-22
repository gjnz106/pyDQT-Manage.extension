# -*- coding: utf-8 -*-
"""Family Manager v3.1 - Revit 2024-2027 Compatible
Author: Dang Quoc Truong (DQT)

Changes in v3.1:
- Added Revit 2024-2027 compatibility (ElementId.Value vs IntegerValue)
- Fixed Health Check tab (was using old attributes)

Changes in v3.0:
- Added System Families support (Walls, Floors, Ceilings, Roofs)
- Added Model Groups support
- Filter by Loadable/System/Groups
- Rename works for all family types
"""
__title__ = "Family\nManager"
__author__ = "DQT"

from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Architecture import StairsType, RailingType
from System.Collections.Generic import List
import System
import re, datetime, codecs, os

# ============================================================================
# REVIT VERSION COMPATIBILITY
# ============================================================================
def _eid_int(element_id):
    """Get integer value from ElementId - compatible with Revit 2024-2027
    Revit 2024+: ElementId.Value (Int64)
    Revit 2023-: ElementId.IntegerValue (Int32)
    """
    if element_id is None:
        return -1
    try:
        # Revit 2024+ uses .Value
        return element_id.Value
    except AttributeError:
        try:
            # Revit 2023 and earlier uses .IntegerValue
            return element_id.IntegerValue
        except:
            return -1

# ============================================================================
# CONFIGURATION
# ============================================================================
class Config:
    warn_size_kb = 1024
    err_size_kb = 5120
    patterns = [r'^[A-Z]{2,4}_.*', r'^FAM_.*', r'^.*_v\d+$']

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def get_name(element):
    """Safely get element name"""
    if not element:
        return "<None>"
    try:
        if hasattr(element, 'Name') and element.Name:
            return element.Name
    except:
        pass
    try:
        name = Element.Name.GetValue(element)
        if name:
            return name
    except:
        pass
    try:
        param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param and param.HasValue:
            return param.AsString()
    except:
        pass
    try:
        param = element.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if param and param.HasValue:
            return param.AsString()
    except:
        pass
    return "<No Name>"

def format_size(kb):
    if kb < 1024:
        return "{} KB".format(kb)
    return "{:.1f} MB".format(kb / 1024.0)


def purge_family_document(fam_doc):
    """Purge ALL unused elements in a family document.
    Uses multiple strategies to find and delete unused elements.
    Returns: (success, purged_count, error_message)
    """
    if not fam_doc or not fam_doc.IsFamilyDocument:
        return False, 0, "Not a family document"
    
    total_purged = 0
    
    try:
        # Multiple passes - some elements become purgeable after others are deleted
        max_iterations = 10
        
        for iteration in range(max_iterations):
            purged_this_round = 0
            
            # === Strategy 1: Unused Nested Family Types ===
            try:
                # Collect used symbol IDs
                used_symbol_ids = set()
                for inst in FilteredElementCollector(fam_doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
                    try:
                        if inst.Symbol:
                            used_symbol_ids.add(_eid_int(inst.Symbol.Id))
                            # Also mark the family as used
                            if inst.Symbol.Family:
                                used_symbol_ids.add(_eid_int(inst.Symbol.Family.Id))
                    except:
                        pass
                
                # Delete unused symbols
                for fam in FilteredElementCollector(fam_doc).OfClass(Family):
                    try:
                        type_ids = fam.GetFamilySymbolIds()
                        if type_ids:
                            all_unused = True
                            for tid in type_ids:
                                if _eid_int(tid) in used_symbol_ids:
                                    all_unused = False
                                    break
                            
                            if all_unused:
                                # Delete entire family if no types are used
                                try:
                                    fam_doc.Delete(fam.Id)
                                    purged_this_round += 1
                                    continue
                                except:
                                    pass
                            
                            # Delete individual unused types
                            for tid in type_ids:
                                if _eid_int(tid) not in used_symbol_ids:
                                    try:
                                        fam_doc.Delete(tid)
                                        purged_this_round += 1
                                    except:
                                        pass
                    except:
                        pass
            except:
                pass
            
            # === Strategy 2: Unused Materials ===
            try:
                used_material_ids = set()
                
                # Check all elements for material usage
                for elem in FilteredElementCollector(fam_doc).WhereElementIsNotElementType():
                    try:
                        mat_ids = elem.GetMaterialIds(False)
                        for mid in mat_ids:
                            used_material_ids.add(_eid_int(mid))
                        mat_ids = elem.GetMaterialIds(True)  # Paint materials
                        for mid in mat_ids:
                            used_material_ids.add(_eid_int(mid))
                    except:
                        pass
                
                # Check family parameter default values
                try:
                    fm = fam_doc.FamilyManager
                    for param in fm.Parameters:
                        try:
                            if param.StorageType == StorageType.ElementId:
                                for ft in fm.Types:
                                    try:
                                        fm.CurrentType = ft
                                        val = fm.CurrentType.AsElementId(param)
                                        if val and _eid_int(val) > 0:
                                            used_material_ids.add(_eid_int(val))
                                    except:
                                        pass
                        except:
                            pass
                except:
                    pass
                
                # Delete unused materials
                for mat in FilteredElementCollector(fam_doc).OfClass(Material):
                    try:
                        if _eid_int(mat.Id) not in used_material_ids:
                            fam_doc.Delete(mat.Id)
                            purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 3: Unused Import Instances (CAD) ===
            try:
                for imp in FilteredElementCollector(fam_doc).OfClass(ImportInstance):
                    try:
                        fam_doc.Delete(imp.Id)
                        purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 4: Unused CAD Link Types ===
            try:
                for cad in FilteredElementCollector(fam_doc).OfClass(CADLinkType):
                    try:
                        fam_doc.Delete(cad.Id)
                        purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 5: Unused Image Types ===
            try:
                used_image_ids = set()
                for img in FilteredElementCollector(fam_doc).OfClass(ImageInstance):
                    try:
                        used_image_ids.add(_eid_int(img.GetTypeId()))
                    except:
                        pass
                
                for img_type in FilteredElementCollector(fam_doc).OfClass(ImageType):
                    try:
                        if _eid_int(img_type.Id) not in used_image_ids:
                            fam_doc.Delete(img_type.Id)
                            purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 6: Unused Fill Patterns ===
            try:
                # Get default fill pattern IDs that should not be deleted
                default_patterns = {"Solid fill", "<Solid fill>", "No pattern", "<No pattern>"}
                
                for fp in FilteredElementCollector(fam_doc).OfClass(FillPatternElement):
                    try:
                        if fp.Name not in default_patterns:
                            fam_doc.Delete(fp.Id)
                            purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 7: Unused Line Patterns ===
            try:
                default_patterns = {"Solid", "<Solid>", "Hidden", "Center", "Dash"}
                
                for lp in FilteredElementCollector(fam_doc).OfClass(LinePatternElement):
                    try:
                        if lp.Name not in default_patterns:
                            fam_doc.Delete(lp.Id)
                            purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 8: Unused Group Types ===
            try:
                used_group_ids = set()
                for grp in FilteredElementCollector(fam_doc).OfClass(Group):
                    try:
                        used_group_ids.add(_eid_int(grp.GetTypeId()))
                    except:
                        pass
                
                for grp_type in FilteredElementCollector(fam_doc).OfClass(GroupType):
                    try:
                        if _eid_int(grp_type.Id) not in used_group_ids:
                            fam_doc.Delete(grp_type.Id)
                            purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 9: Unused Views (non-essential) ===
            try:
                # Essential views in family editor - DO NOT DELETE
                essential_views = {
                    "Ref. Level", "Reference Level",
                    "Front", "Back", "Left", "Right", "Top", "Bottom",
                    "View 1", "View 2"
                }
                
                for view in FilteredElementCollector(fam_doc).OfClass(View):
                    try:
                        # Skip essential views and templates
                        if view.IsTemplate:
                            continue
                        if view.Name in essential_views:
                            continue
                        # Skip if it's a dependent view
                        if hasattr(view, 'GetPrimaryViewId'):
                            primary = view.GetPrimaryViewId()
                            if primary and primary != ElementId.InvalidElementId:
                                continue
                        
                        fam_doc.Delete(view.Id)
                        purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            # === Strategy 10: Unused Annotation Symbols / Generic Annotations ===
            try:
                used_anno_ids = set()
                for anno in FilteredElementCollector(fam_doc).OfClass(AnnotationSymbol):
                    try:
                        used_anno_ids.add(_eid_int(anno.GetTypeId()))
                    except:
                        pass
                
                for anno_type in FilteredElementCollector(fam_doc).OfClass(AnnotationSymbolType):
                    try:
                        if _eid_int(anno_type.Id) not in used_anno_ids:
                            fam_doc.Delete(anno_type.Id)
                            purged_this_round += 1
                    except:
                        pass
            except:
                pass
            
            total_purged += purged_this_round
            
            # Stop if nothing was purged this round
            if purged_this_round == 0:
                break
        
        return True, total_purged, ""
        
    except Exception as ex:
        return False, total_purged, str(ex)

# ============================================================================
# DATA MODELS
# ============================================================================
class FamilyData(object):
    """Data model for Families (grouped) - used in Families tab"""
    def __init__(self):
        self.element_id = 0
        self.family_name = ""      # Family name
        self.category_name = ""
        self.type_count = 0        # Number of types in this family
        self.instance_count = 0    # Total instances of all types
        self.is_in_place = False
        self.is_editable = True
        self.estimated_size_kb = 0
        self.size_display = "-"
        self.issue_text = "OK"
        self.has_issues = False
        self.family = None         # Family object (for loadable only)
        self.is_unused = False
        self.family_type = "Loadable"  # "Loadable", "System", "In-Place", "Model Groups"
        self.family_type_display = "Loadable"

class FamilyTypeData(object):
    def __init__(self):
        self.element_id = 0
        self.type_name = ""
        self.family_name = ""
        self.instance_count = 0
        self.symbol = None
        self.parameter_count = 0

class ParameterData(object):
    def __init__(self):
        self.name = ""
        self.value = ""
        self.storage_type = ""
        self.is_instance = False
        self.is_shared = False
        self.is_read_only = False
        self.group_name = ""
        self.parameter = None
        self.scope_display = ""
        self.shared_display = ""

# ============================================================================
# DATA COLLECTORS
# ============================================================================

def get_all_families(doc, include_loadable=True, include_system=True, include_groups=True):
    """Get all families grouped (not individual types) for Families tab"""
    families = []
    
    # Count instances for each type
    type_instance_counts = {}
    
    # Count FamilyInstance
    for inst in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
        try:
            type_id = _eid_int(inst.GetTypeId())
            type_instance_counts[type_id] = type_instance_counts.get(type_id, 0) + 1
        except:
            pass
    
    # Count Wall instances
    for wall in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            type_id = _eid_int(wall.GetTypeId())
            type_instance_counts[type_id] = type_instance_counts.get(type_id, 0) + 1
        except:
            pass
    
    # Count Floor instances
    for floor in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
        try:
            type_id = _eid_int(floor.GetTypeId())
            type_instance_counts[type_id] = type_instance_counts.get(type_id, 0) + 1
        except:
            pass
    
    # Count Ceiling instances
    for ceiling in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        try:
            type_id = _eid_int(ceiling.GetTypeId())
            type_instance_counts[type_id] = type_instance_counts.get(type_id, 0) + 1
        except:
            pass
    
    # Count Roof instances
    for roof in FilteredElementCollector(doc).OfClass(RoofBase).WhereElementIsNotElementType():
        try:
            type_id = _eid_int(roof.GetTypeId())
            type_instance_counts[type_id] = type_instance_counts.get(type_id, 0) + 1
        except:
            pass
    
    # === LOADABLE FAMILIES (grouped by Family) ===
    if include_loadable:
        for fam in FilteredElementCollector(doc).OfClass(Family):
            try:
                d = FamilyData()
                d.family = fam
                d.element_id = _eid_int(fam.Id)
                d.family_name = get_name(fam)
                d.is_in_place = fam.IsInPlace
                d.is_editable = fam.IsEditable
                
                if d.is_in_place:
                    d.family_type = "In-Place"
                    d.family_type_display = "In-Place"
                else:
                    d.family_type = "Loadable"
                    d.family_type_display = "Loadable"
                
                try:
                    d.category_name = fam.FamilyCategory.Name if fam.FamilyCategory else "N/A"
                except:
                    d.category_name = "N/A"
                
                # Count types and instances
                try:
                    type_ids = fam.GetFamilySymbolIds()
                    d.type_count = type_ids.Count if type_ids else 0
                    
                    # Sum instances from all types
                    total_inst = 0
                    for tid in type_ids:
                        total_inst += type_instance_counts.get(_eid_int(tid), 0)
                    d.instance_count = total_inst
                except:
                    d.type_count = 0
                    d.instance_count = 0
                
                d.is_unused = d.instance_count == 0 and not d.is_in_place
                d.estimated_size_kb = 50 + d.type_count * 10
                d.size_display = format_size(d.estimated_size_kb)
                
                families.append(d)
            except:
                pass
    
    # === SYSTEM FAMILIES (each type is shown as a "family") ===
    if include_system:
        # Walls
        for wt in FilteredElementCollector(doc).OfClass(WallType):
            try:
                d = FamilyData()
                d.element_id = _eid_int(wt.Id)
                d.family_name = get_name(wt)
                d.family_type = "System"
                d.family_type_display = "System"
                d.category_name = "Walls"
                d.is_editable = True
                d.type_count = 1
                d.instance_count = type_instance_counts.get(d.element_id, 0)
                d.is_unused = d.instance_count == 0
                d.family = None  # No family object for system
                d._system_type = wt  # Store for rename
                families.append(d)
            except:
                pass
        
        # Floors
        for ft in FilteredElementCollector(doc).OfClass(FloorType):
            try:
                d = FamilyData()
                d.element_id = _eid_int(ft.Id)
                d.family_name = get_name(ft)
                d.family_type = "System"
                d.family_type_display = "System"
                d.category_name = "Floors"
                d.is_editable = True
                d.type_count = 1
                d.instance_count = type_instance_counts.get(d.element_id, 0)
                d.is_unused = d.instance_count == 0
                d.family = None
                d._system_type = ft
                families.append(d)
            except:
                pass
        
        # Ceilings
        for ct in FilteredElementCollector(doc).OfClass(CeilingType):
            try:
                d = FamilyData()
                d.element_id = _eid_int(ct.Id)
                d.family_name = get_name(ct)
                d.family_type = "System"
                d.family_type_display = "System"
                d.category_name = "Ceilings"
                d.is_editable = True
                d.type_count = 1
                d.instance_count = type_instance_counts.get(d.element_id, 0)
                d.is_unused = d.instance_count == 0
                d.family = None
                d._system_type = ct
                families.append(d)
            except:
                pass
        
        # Roofs
        for rt in FilteredElementCollector(doc).OfClass(RoofType):
            try:
                d = FamilyData()
                d.element_id = _eid_int(rt.Id)
                d.family_name = get_name(rt)
                d.family_type = "System"
                d.family_type_display = "System"
                d.category_name = "Roofs"
                d.is_editable = True
                d.type_count = 1
                d.instance_count = type_instance_counts.get(d.element_id, 0)
                d.is_unused = d.instance_count == 0
                d.family = None
                d._system_type = rt
                families.append(d)
            except:
                pass
    
    # === MODEL GROUPS ===
    if include_groups:
        for gt in FilteredElementCollector(doc).OfClass(GroupType):
            try:
                # Only Model groups, not Detail groups
                if gt.Category and _eid_int(gt.Category.Id) == int(BuiltInCategory.OST_IOSModelGroups):
                    d = FamilyData()
                    d.element_id = _eid_int(gt.Id)
                    d.family_name = get_name(gt)
                    d.family_type = "Model Groups"
                    d.family_type_display = "Groups"
                    d.category_name = "Model Groups"
                    d.is_editable = True
                    d.type_count = 1
                    
                    # Count group instances
                    group_count = 0
                    for grp in FilteredElementCollector(doc).OfClass(Group):
                        try:
                            if grp.GetTypeId() == gt.Id:
                                group_count += 1
                        except:
                            pass
                    d.instance_count = group_count
                    d.is_unused = d.instance_count == 0
                    d.family = None
                    d._system_type = gt
                    families.append(d)
            except:
                pass
    
    return families


def get_families(doc):
    """Get only Loadable families for Type Manager and Parameters tabs"""
    return [f for f in get_all_families(doc, include_loadable=True, include_system=False, include_groups=False)]


def get_family_types(doc, family):
    types = []
    if not family:
        return types
    
    instance_counts = {}
    try:
        collector = FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
        for inst in collector:
            try:
                sym = inst.Symbol
                if sym and sym.Family and sym.Family.Id == family.Id:
                    type_id = _eid_int(sym.Id)
                    instance_counts[type_id] = instance_counts.get(type_id, 0) + 1
            except:
                pass
    except:
        pass
    
    try:
        type_ids = family.GetFamilySymbolIds()
        if type_ids:
            for tid in type_ids:
                try:
                    symbol = doc.GetElement(tid)
                    if symbol:
                        t = FamilyTypeData()
                        t.element_id = _eid_int(tid)
                        t.type_name = get_name(symbol)
                        t.family_name = get_name(family)
                        t.instance_count = instance_counts.get(_eid_int(tid), 0)
                        t.symbol = symbol
                        try:
                            t.parameter_count = symbol.Parameters.Size
                        except:
                            t.parameter_count = 0
                        types.append(t)
                except:
                    pass
    except:
        pass
    
    return types


def get_type_parameters(symbol, include_instance=True):
    params = []
    if not symbol:
        return params
    
    try:
        for param in symbol.Parameters:
            try:
                p = ParameterData()
                p.name = param.Definition.Name
                p.is_instance = False
                p.is_shared = param.IsShared
                p.is_read_only = param.IsReadOnly
                p.parameter = param
                p.storage_type = str(param.StorageType)
                p.value = get_param_value(param)
                p.scope_display = "Type"
                p.shared_display = "Yes" if param.IsShared else "No"
                params.append(p)
            except:
                pass
    except:
        pass
    
    if include_instance:
        try:
            doc = symbol.Document
            collector = FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
            for inst in collector:
                try:
                    if inst.Symbol and inst.Symbol.Id == symbol.Id:
                        for param in inst.Parameters:
                            try:
                                if any(pp.name == param.Definition.Name for pp in params):
                                    continue
                                p = ParameterData()
                                p.name = param.Definition.Name
                                p.is_instance = True
                                p.is_shared = param.IsShared
                                p.is_read_only = param.IsReadOnly
                                p.parameter = param
                                p.storage_type = str(param.StorageType)
                                p.value = get_param_value(param)
                                p.scope_display = "Inst"
                                p.shared_display = "Yes" if param.IsShared else "No"
                                params.append(p)
                            except:
                                pass
                        break
                except:
                    pass
        except:
            pass
    
    return params


def get_param_value(param):
    try:
        if not param.HasValue:
            return "<None>"
        st = param.StorageType
        if st == StorageType.String:
            return param.AsString() or ""
        elif st == StorageType.Integer:
            return str(param.AsInteger())
        elif st == StorageType.Double:
            try:
                vs = param.AsValueString()
                if vs:
                    return vs
            except:
                pass
            return str(round(param.AsDouble(), 4))
        elif st == StorageType.ElementId:
            eid = param.AsElementId()
            if eid and _eid_int(eid) != -1:
                try:
                    el = param.Element.Document.GetElement(eid)
                    if el:
                        return get_name(el)
                except:
                    pass
            return "<None>"
        return ""
    except:
        return ""


# ============================================================================
# XAML TEMPLATES
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Family Manager v2.0 - DQT" Height="800" Width="1300" 
        WindowStartupLocation="CenterScreen" Background="#FEF8E7">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        
        <Border Grid.Row="0" Background="#F0CC88" CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
            <Grid>
                <StackPanel>
                    <TextBlock Text="Family Manager v2.0" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37"/>
                </StackPanel>
                <Button Name="btnHelp" Content="? Help" Padding="10,4" Background="White" HorizontalAlignment="Right"/>
            </Grid>
        </Border>
        
        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="0,0,4,0">
                <StackPanel><TextBlock Text="TOTAL" FontSize="9" Foreground="#666"/><TextBlock Name="txtTotal" Text="0" FontSize="18" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="4,0">
                <StackPanel><TextBlock Text="LOADABLE" FontSize="9" Foreground="#4CAF50"/><TextBlock Name="txtLoadable" Text="0" FontSize="18" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="4,0">
                <StackPanel><TextBlock Text="SYSTEM" FontSize="9" Foreground="#2196F3"/><TextBlock Name="txtSystem" Text="0" FontSize="18" FontWeight="Bold" Foreground="#2196F3"/></StackPanel>
            </Border>
            <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="4,0">
                <StackPanel><TextBlock Text="GROUPS" FontSize="9" Foreground="#9C27B0"/><TextBlock Name="txtGroups" Text="0" FontSize="18" FontWeight="Bold" Foreground="#9C27B0"/></StackPanel>
            </Border>
            <Border Grid.Column="4" Background="White" BorderBrush="#FF9800" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="4,0">
                <StackPanel><TextBlock Text="UNUSED" FontSize="9" Foreground="#FF9800"/><TextBlock Name="txtUnused" Text="0" FontSize="18" FontWeight="Bold" Foreground="#FF9800"/></StackPanel>
            </Border>
            <Border Grid.Column="5" Background="White" BorderBrush="#E5B85C" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="4,0,0,0">
                <StackPanel><TextBlock Text="SELECTED" FontSize="9" Foreground="#E5B85C"/><TextBlock Name="txtSelected" Text="0" FontSize="18" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
            </Border>
        </Grid>
        
        <TabControl Grid.Row="2" Name="tabControl" Background="White" BorderBrush="#D4B87A">
            
            <TabItem Header="  Families  " Padding="12,6">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="180"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Border Background="#FFFDF5" Padding="8">
                        <StackPanel>
                            <TextBlock Text="SEARCH" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                            <TextBox Name="txtSearch" Padding="4" Margin="0,0,0,8"/>
                            <TextBlock Text="FAMILY TYPE" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                            <ComboBox Name="cmbFamilyType" Padding="4" Margin="0,0,0,8" SelectedIndex="0">
                                <ComboBoxItem Content="All Types"/>
                                <ComboBoxItem Content="Loadable Families"/>
                                <ComboBoxItem Content="System Families"/>
                                <ComboBoxItem Content="Model Groups"/>
                            </ComboBox>
                            <TextBlock Text="FILTER" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                            <ComboBox Name="cmbFilter" Padding="4" Margin="0,0,0,8" SelectedIndex="0">
                                <ComboBoxItem Content="All"/>
                                <ComboBoxItem Content="With Issues"/>
                                <ComboBoxItem Content="Unused"/>
                            </ComboBox>
                            <TextBlock Text="CATEGORY" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                            <ListBox Name="lstCategories" Height="200" Margin="0,0,0,8"/>
                            <Button Name="btnSelectUnused" Content="Select Unused" Padding="6,4" Margin="0,0,0,4" Background="#FFF3E0"/>
                            <Button Name="btnPurgeUnused" Content="Purge Unused" Padding="6,4" Background="#FFEBEE" Foreground="#C62828"/>
                        </StackPanel>
                    </Border>
                    <DataGrid Grid.Column="1" Name="dataGrid" AutoGenerateColumns="False" IsReadOnly="True" 
                              SelectionMode="Extended" Margin="8,0,0,0" Background="White" BorderThickness="0" 
                              GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#EEE">
                        <DataGrid.Columns>
                            <DataGridTextColumn Header="Family Name" Binding="{Binding family_name}" Width="*"/>
                            <DataGridTextColumn Header="Category" Binding="{Binding category_name}" Width="120"/>
                            <DataGridTextColumn Header="Kind" Binding="{Binding family_type_display}" Width="65"/>
                            <DataGridTextColumn Header="Types" Binding="{Binding type_count}" Width="50"/>
                            <DataGridTextColumn Header="Inst" Binding="{Binding instance_count}" Width="50"/>
                        </DataGrid.Columns>
                    </DataGrid>
                </Grid>
            </TabItem>
            
            <TabItem Header="  Type Manager  " Padding="12,6">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="250"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Border Background="#FFFDF5" Padding="8">
                        <Grid>
                            <Grid.RowDefinitions>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="*"/>
                            </Grid.RowDefinitions>
                            <TextBlock Text="SELECT FAMILY" FontSize="10" FontWeight="SemiBold" Margin="0,0,0,6"/>
                            <TextBox Grid.Row="1" Name="txtTypeSearch" Padding="4" Margin="0,0,0,6"/>
                            <ListBox Grid.Row="2" Name="lstFamiliesForTypes"/>
                        </Grid>
                    </Border>
                    <Grid Grid.Column="1" Margin="8,0,0,0">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
                            <TextBlock Name="txtSelectedFamily" Text="Select a family" FontSize="14" FontWeight="SemiBold"/>
                            <TextBlock Name="txtTypeCount" Text="" FontSize="12" Foreground="#666" Margin="10,0,0,0" VerticalAlignment="Center"/>
                        </StackPanel>
                        <DataGrid Grid.Row="1" Name="dataGridTypes" AutoGenerateColumns="False" IsReadOnly="True" 
                                  SelectionMode="Extended" Background="White" BorderBrush="#D4B87A" 
                                  GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#EEE">
                            <DataGrid.Columns>
                                <DataGridTextColumn Header="ID" Binding="{Binding element_id}" Width="60"/>
                                <DataGridTextColumn Header="Type Name" Binding="{Binding type_name}" Width="*"/>
                                <DataGridTextColumn Header="Instances" Binding="{Binding instance_count}" Width="70"/>
                                <DataGridTextColumn Header="Params" Binding="{Binding parameter_count}" Width="60"/>
                            </DataGrid.Columns>
                        </DataGrid>
                        <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,8,0,0">
                            <Button Name="btnRenameType" Content="Rename" Padding="8,4" Margin="0,0,4,0" Background="#F0CC88"/>
                            <Button Name="btnDuplicateType" Content="Duplicate" Padding="8,4" Margin="0,0,4,0" Background="#F0CC88"/>
                            <Button Name="btnDeleteType" Content="Delete" Padding="8,4" Margin="0,0,4,0" Background="#FFCDD2"/>
                            <Button Name="btnActivateType" Content="Activate" Padding="8,4" Margin="0,0,4,0" Background="#C8E6C9"/>
                            <Button Name="btnSelectInstances" Content="Select Instances" Padding="8,4" Background="White"/>
                        </StackPanel>
                    </Grid>
                </Grid>
            </TabItem>
            
            <TabItem Header="  Parameters  " Padding="12,6">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="250"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Border Background="#FFFDF5" Padding="8">
                        <Grid>
                            <Grid.RowDefinitions>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="*"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="150"/>
                            </Grid.RowDefinitions>
                            <TextBlock Text="SELECT FAMILY" FontSize="10" FontWeight="SemiBold" Margin="0,0,0,6"/>
                            <TextBox Grid.Row="1" Name="txtParamFamilySearch" Padding="4" Margin="0,0,0,6"/>
                            <ListBox Grid.Row="2" Name="lstFamiliesForParams"/>
                            <TextBlock Grid.Row="3" Text="SELECT TYPE" FontSize="10" FontWeight="SemiBold" Margin="0,8,0,6"/>
                            <ListBox Grid.Row="4" Name="lstTypesForParams"/>
                        </Grid>
                    </Border>
                    <Grid Grid.Column="1" Margin="8,0,0,0">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
                            <TextBlock Name="txtSelectedType" Text="Select a type" FontSize="14" FontWeight="SemiBold"/>
                            <TextBlock Name="txtParamCount" Text="" FontSize="12" Foreground="#666" Margin="10,0,0,0" VerticalAlignment="Center"/>
                        </StackPanel>
                        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,0,0,8">
                            <ComboBox Name="cmbParamFilter" Width="110" SelectedIndex="0">
                                <ComboBoxItem Content="All"/>
                                <ComboBoxItem Content="Type Only"/>
                                <ComboBoxItem Content="Instance Only"/>
                                <ComboBoxItem Content="Shared"/>
                            </ComboBox>
                            <TextBox Name="txtParamNameSearch" Width="120" Padding="4" Margin="8,0,0,0"/>
                        </StackPanel>
                        <DataGrid Grid.Row="2" Name="dataGridParams" AutoGenerateColumns="False" IsReadOnly="True" 
                                  SelectionMode="Extended" Background="White" BorderBrush="#D4B87A" 
                                  GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#EEE">
                            <DataGrid.Columns>
                                <DataGridTextColumn Header="Parameter" Binding="{Binding name}" Width="*"/>
                                <DataGridTextColumn Header="Value" Binding="{Binding value}" Width="140"/>
                                <DataGridTextColumn Header="Type" Binding="{Binding storage_type}" Width="60"/>
                                <DataGridTextColumn Header="Scope" Binding="{Binding scope_display}" Width="60"/>
                                <DataGridTextColumn Header="Shared" Binding="{Binding shared_display}" Width="50"/>
                            </DataGrid.Columns>
                        </DataGrid>
                        <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,8,0,0">
                            <Button Name="btnEditParam" Content="Edit" Padding="8,4" Margin="0,0,4,0" Background="#F0CC88"/>
                            <Button Name="btnCopyParams" Content="Copy to Types" Padding="8,4" Margin="0,0,4,0" Background="#F0CC88"/>
                            <Button Name="btnExportParams" Content="Export CSV" Padding="8,4" Margin="0,0,4,0" Background="#C8E6C9"/>
                            <Button Name="btnImportParams" Content="Import CSV" Padding="8,4" Margin="0,0,4,0" Background="#C8E6C9"/>
                            <Button Name="btnCompareParams" Content="Compare" Padding="8,4" Background="#E3F2FD"/>
                        </StackPanel>
                    </Grid>
                </Grid>
            </TabItem>
            
            <TabItem Header="  Health Check  " Padding="12,6">
                <Grid Margin="8">
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <StackPanel Orientation="Horizontal" Margin="0,0,0,10">
                        <Button Name="btnRunHealth" Content="Run Health Check" Padding="12,6" Background="#F0CC88" FontWeight="SemiBold"/>
                        <TextBlock Name="txtHealthStatus" Text="Click to analyze..." VerticalAlignment="Center" Margin="15,0,0,0" Foreground="#666"/>
                    </StackPanel>
                    <Border Grid.Row="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10">
                        <ScrollViewer VerticalScrollBarVisibility="Auto">
                            <StackPanel Name="healthPanel">
                                <TextBlock Text="Results will appear here..." Foreground="#999" FontStyle="Italic"/>
                            </StackPanel>
                        </ScrollViewer>
                    </Border>
                    <Button Grid.Row="2" Name="btnExportHealth" Content="Export Report" Padding="8,4" Background="White" HorizontalAlignment="Right" Margin="0,8,0,0" IsEnabled="False"/>
                </Grid>
            </TabItem>
        </TabControl>
        
        <Border Grid.Row="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8" Margin="0,10,0,0">
            <StackPanel Orientation="Horizontal" HorizontalAlignment="Center">
                <Button Name="btnSelectAll" Content="All" Padding="6,4" Margin="2" Background="White" Width="40"/>
                <Button Name="btnClear" Content="Clear" Padding="6,4" Margin="2" Background="White" Width="45"/>
                <Rectangle Width="1" Fill="#D4B87A" Margin="8,2"/>
                <Button Name="btnRename" Content="Rename" Padding="8,4" Margin="2" Background="#F0CC88"/>
                <Button Name="btnExport" Content="Export" Padding="8,4" Margin="2" Background="#F0CC88"/>
                <Button Name="btnImport" Content="Import" Padding="8,4" Margin="2" Background="#F0CC88"/>
                <Button Name="btnDelete" Content="Delete" Padding="8,4" Margin="2" Background="#FFCDD2"/>
                <Rectangle Width="1" Fill="#D4B87A" Margin="8,2"/>
                <Button Name="btnExportCSV" Content="CSV" Padding="8,4" Margin="2" Background="White"/>
                <Button Name="btnExportHTML" Content="Report" Padding="8,4" Margin="2" Background="White"/>
                <Button Name="btnRefresh" Content="Refresh" Padding="8,4" Margin="2" Background="White"/>
            </StackPanel>
        </Border>
        
        <Grid Grid.Row="4" Margin="0,8,0,0">
            <TextBlock Text="Double-click to edit family | Ctrl+Click for multi-select" FontSize="10" Foreground="#888"/>
            <Button Name="btnClose" Content="Close" Padding="12,4" Background="White" HorizontalAlignment="Right"/>
        </Grid>
    </Grid>
</Window>
"""

# NEW: Enhanced Rename Dialog with Prefix/Suffix
RENAME_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Rename" Height="500" Width="500" WindowStartupLocation="CenterOwner" Background="#FEF8E7" ResizeMode="NoResize">
    <Grid Margin="15">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        
        <TextBlock Text="Batch Rename" FontSize="14" FontWeight="Bold" Margin="0,0,0,10"/>
        
        <StackPanel Grid.Row="1">
            <!-- Option 1: New Name -->
            <TextBlock Text="Option 1: New name (use {n} for numbering, {family} for family name):" Margin="0,0,0,4" FontWeight="SemiBold"/>
            <TextBox Name="txtNewName" Padding="6" Margin="0,0,0,10"/>
            
            <!-- Option 2: Prefix/Suffix -->
            <TextBlock Text="Option 2: Add Prefix / Suffix:" Margin="0,0,0,4" FontWeight="SemiBold"/>
            <Grid Margin="0,0,0,10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="80"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <StackPanel>
                    <TextBlock Text="Prefix:" FontSize="10" Foreground="#666"/>
                    <TextBox Name="txtPrefix" Padding="6"/>
                </StackPanel>
                <TextBlock Grid.Column="1" Text="[name]" HorizontalAlignment="Center" VerticalAlignment="Bottom" Margin="0,0,0,8" Foreground="#888"/>
                <StackPanel Grid.Column="2">
                    <TextBlock Text="Suffix:" FontSize="10" Foreground="#666"/>
                    <TextBox Name="txtSuffix" Padding="6"/>
                </StackPanel>
            </Grid>
            
            <!-- Option 3: Find/Replace -->
            <TextBlock Text="Option 3: Find and Replace:" Margin="0,0,0,4" FontWeight="SemiBold"/>
            <Grid Margin="0,0,0,10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="40"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <StackPanel>
                    <TextBlock Text="Find:" FontSize="10" Foreground="#666"/>
                    <TextBox Name="txtFind" Padding="6"/>
                </StackPanel>
                <TextBlock Grid.Column="1" Text="->" HorizontalAlignment="Center" VerticalAlignment="Bottom" Margin="0,0,0,8" FontWeight="Bold"/>
                <StackPanel Grid.Column="2">
                    <TextBlock Text="Replace:" FontSize="10" Foreground="#666"/>
                    <TextBox Name="txtReplace" Padding="6"/>
                </StackPanel>
            </Grid>
            
            <!-- Option 4: Case Conversion -->
            <TextBlock Text="Option 4: Case Conversion:" Margin="0,0,0,4" FontWeight="SemiBold"/>
            <StackPanel Orientation="Horizontal" Margin="0,0,0,5">
                <RadioButton Name="rbCaseNone" Content="None" IsChecked="True" Margin="0,0,15,0"/>
                <RadioButton Name="rbCaseUpper" Content="UPPERCASE" Margin="0,0,15,0"/>
                <RadioButton Name="rbCaseLower" Content="lowercase" Margin="0,0,15,0"/>
                <RadioButton Name="rbCaseTitle" Content="Title Case"/>
            </StackPanel>
        </StackPanel>
        
        <!-- Preview -->
        <Border Grid.Row="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" Padding="8" Margin="0,10,0,0" CornerRadius="4">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                </Grid.RowDefinitions>
                <TextBlock Text="Preview:" FontSize="10" FontWeight="SemiBold" Margin="0,0,0,4"/>
                <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto">
                    <StackPanel Name="previewPanel"/>
                </ScrollViewer>
            </Grid>
        </Border>
        
        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button Name="btnCancel" Content="Cancel" Width="80" Padding="8,6" Margin="0,0,8,0" Background="White"/>
            <Button Name="btnApply" Content="Apply" Width="80" Padding="8,6" Background="#F0CC88"/>
        </StackPanel>
    </Grid>
</Window>
"""

# Export Options Dialog
EXPORT_OPTIONS_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Export Options" Height="220" Width="450" WindowStartupLocation="CenterOwner" Background="#FEF8E7" ResizeMode="NoResize">
    <Grid Margin="15">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        
        <TextBlock Text="Export Families" FontSize="14" FontWeight="Bold" Margin="0,0,0,10"/>
        
        <StackPanel Grid.Row="1">
            <TextBlock Name="txtExportInfo" Text="Selected: 0 families" Margin="0,0,0,15"/>
            
            <CheckBox Name="chkAutoPurge" Content="Auto purge before export (removes unused nested families, materials, CAD)" Margin="0,0,0,10"/>
            
            <CheckBox Name="chkOverwrite" Content="Overwrite existing files" IsChecked="True"/>
        </StackPanel>
        
        <StackPanel Grid.Row="2" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,15,0,0">
            <Button Name="btnCancel" Content="Cancel" Width="80" Padding="8,6" Margin="0,0,8,0" Background="White"/>
            <Button Name="btnExport" Content="Export" Width="80" Padding="8,6" Background="#F0CC88"/>
        </StackPanel>
    </Grid>
</Window>
"""

EDIT_PARAM_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Edit Parameter" Height="220" Width="380" WindowStartupLocation="CenterOwner" Background="#FEF8E7" ResizeMode="NoResize">
    <Grid Margin="15">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Name="txtParamName" FontSize="14" FontWeight="Bold" Margin="0,0,0,10"/>
        <TextBlock Grid.Row="1" Name="txtCurrentValue" Foreground="#666" Margin="0,0,0,10"/>
        <TextBox Grid.Row="2" Name="txtNewValue" Padding="6" VerticalAlignment="Top"/>
        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button Name="btnCancel" Content="Cancel" Width="80" Padding="8,6" Margin="0,0,8,0" Background="White"/>
            <Button Name="btnApply" Content="Apply" Width="80" Padding="8,6" Background="#F0CC88"/>
        </StackPanel>
    </Grid>
</Window>
"""

COMPARE_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Compare Parameters" Height="550" Width="800" WindowStartupLocation="CenterScreen" Background="#FEF8E7">
    <Grid Margin="15">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Text="Compare Type Parameters" FontSize="14" FontWeight="Bold" Margin="0,0,0,10"/>
        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="50"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <ComboBox Name="cmbType1" Padding="6"/>
            <TextBlock Grid.Column="1" Text="vs" HorizontalAlignment="Center" VerticalAlignment="Center" FontWeight="Bold"/>
            <ComboBox Grid.Column="2" Name="cmbType2" Padding="6"/>
        </Grid>
        <DataGrid Grid.Row="2" Name="dataGridCompare" AutoGenerateColumns="False" IsReadOnly="True" Background="White" BorderBrush="#D4B87A">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Parameter" Binding="{Binding name}" Width="*"/>
                <DataGridTextColumn Header="Type 1" Binding="{Binding value1}" Width="180"/>
                <DataGridTextColumn Header="Type 2" Binding="{Binding value2}" Width="180"/>
                <DataGridTextColumn Header="Match" Binding="{Binding match_display}" Width="60"/>
            </DataGrid.Columns>
        </DataGrid>
        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
            <TextBlock Name="txtStats" VerticalAlignment="Center" Margin="0,0,15,0" Foreground="#666"/>
            <Button Name="btnClose" Content="Close" Padding="12,6" Background="#F0CC88"/>
        </StackPanel>
    </Grid>
</Window>
"""


# ============================================================================
# DIALOG CLASSES
# ============================================================================
class RenameDialog(WPFWindow):
    """Enhanced Rename Dialog with New Name, Prefix/Suffix, Find/Replace, and Case Conversion"""
    def __init__(self, items, is_types=False, rename_family=False):
        WPFWindow.__init__(self, RENAME_XAML, literal_string=True)
        self.items = list(items)
        self.is_types = is_types
        self.rename_family = rename_family  # True = rename family name, False = rename type name
        self.result = False
        
        # Update title based on mode
        if rename_family:
            self.Title = "Rename Family"
        else:
            self.Title = "Rename Type"
        
        # Connect events
        self.txtNewName.TextChanged += self.update_preview
        self.txtPrefix.TextChanged += self.update_preview
        self.txtSuffix.TextChanged += self.update_preview
        self.txtFind.TextChanged += self.update_preview
        self.txtReplace.TextChanged += self.update_preview
        
        # Case conversion radio buttons
        self.rbCaseNone.Checked += self.update_preview
        self.rbCaseUpper.Checked += self.update_preview
        self.rbCaseLower.Checked += self.update_preview
        self.rbCaseTitle.Checked += self.update_preview
        
        self.btnCancel.Click += self.on_cancel
        self.btnApply.Click += self.on_apply
        
        self.update_preview(None, None)
    
    def update_preview(self, sender, args):
        try:
            self.previewPanel.Children.Clear()
            for i, item in enumerate(self.items[:6]):
                # Get the name based on mode
                if self.rename_family:
                    old = getattr(item, 'family_name', '') or getattr(item, 'name', '')
                else:
                    old = getattr(item, 'type_name', '') or getattr(item, 'family_name', '') or getattr(item, 'name', '')
                
                fam_name = getattr(item, 'family_name', '')
                new = self.get_new_name(old, fam_name, i)
                
                tb = System.Windows.Controls.TextBlock()
                if new != old:
                    tb.Text = "{} -> {}".format(old[:25], new[:25])
                    tb.Foreground = System.Windows.Media.Brushes.Green
                else:
                    tb.Text = "{} (no change)".format(old[:35])
                    tb.Foreground = System.Windows.Media.Brushes.Gray
                tb.Margin = System.Windows.Thickness(0, 2, 0, 2)
                tb.FontSize = 11
                self.previewPanel.Children.Add(tb)
            
            if len(self.items) > 6:
                more = System.Windows.Controls.TextBlock()
                more.Text = "... and {} more".format(len(self.items) - 6)
                more.Foreground = System.Windows.Media.Brushes.Gray
                more.FontStyle = System.Windows.FontStyles.Italic
                self.previewPanel.Children.Add(more)
        except:
            pass
    
    def on_cancel(self, sender, args):
        self.result = False
        self.Close()
    
    def on_apply(self, sender, args):
        new_name = (self.txtNewName.Text or "").strip()
        prefix = (self.txtPrefix.Text or "")
        suffix = (self.txtSuffix.Text or "")
        find_text = self.txtFind.Text or ""
        has_case = not self.rbCaseNone.IsChecked
        
        if not new_name and not prefix and not suffix and not find_text and not has_case:
            forms.alert("Enter at least one rename option:\n- New name\n- Prefix/Suffix\n- Find/Replace\n- Case conversion", title="Info")
            return
        
        self.result = True
        self.Close()
    
    def apply_case(self, name):
        """Apply case conversion to name"""
        if self.rbCaseUpper.IsChecked:
            return name.upper()
        elif self.rbCaseLower.IsChecked:
            return name.lower()
        elif self.rbCaseTitle.IsChecked:
            # Title Case: capitalize first letter of each word
            # Handle underscore and hyphen as word separators
            result = []
            for part in name.replace('-', '_').split('_'):
                if part:
                    result.append(part[0].upper() + part[1:].lower() if len(part) > 1 else part.upper())
            # Reconstruct with original separators
            final = name
            idx = 0
            for part in result:
                start = final.lower().find(part.lower(), idx)
                if start >= 0:
                    final = final[:start] + part + final[start+len(part):]
                    idx = start + len(part)
            return final
        return name
    
    def get_new_name(self, name, fam_name="", idx=0):
        """Calculate new name based on options (priority: New Name > Prefix/Suffix > Find/Replace > Case)"""
        result = name
        
        # Option 1: New name (highest priority)
        new_name = (self.txtNewName.Text or "").strip()
        if new_name:
            result = new_name.replace("{n}", str(idx + 1).zfill(3))
            result = result.replace("{family}", fam_name)
        else:
            # Option 2: Prefix/Suffix
            prefix = self.txtPrefix.Text or ""
            suffix = self.txtSuffix.Text or ""
            if prefix or suffix:
                result = prefix + name + suffix
            else:
                # Option 3: Find/Replace
                find_text = self.txtFind.Text or ""
                replace_text = self.txtReplace.Text or ""
                if find_text:
                    result = name.replace(find_text, replace_text)
        
        # Option 4: Case conversion (applied last, can combine with other options)
        result = self.apply_case(result)
        
        return result


class ExportOptionsDialog(WPFWindow):
    """Dialog for export options"""
    def __init__(self, count):
        WPFWindow.__init__(self, EXPORT_OPTIONS_XAML, literal_string=True)
        self.result = False
        self.auto_purge = False
        self.overwrite = True
        
        self.txtExportInfo.Text = "Selected: {} families".format(count)
        
        self.btnCancel.Click += self.on_cancel
        self.btnExport.Click += self.on_export
    
    def on_cancel(self, sender, args):
        self.result = False
        self.Close()
    
    def on_export(self, sender, args):
        self.auto_purge = self.chkAutoPurge.IsChecked
        self.overwrite = self.chkOverwrite.IsChecked
        self.result = True
        self.Close()


class EditParamDialog(WPFWindow):
    def __init__(self, param):
        WPFWindow.__init__(self, EDIT_PARAM_XAML, literal_string=True)
        self.param = param
        self.result = False
        self.new_value = None
        
        self.txtParamName.Text = param.name
        self.txtCurrentValue.Text = "Current value: " + str(param.value)
        self.txtNewValue.Text = str(param.value)
        
        self.btnCancel.Click += self.on_cancel
        self.btnApply.Click += self.on_apply
    
    def on_cancel(self, sender, args):
        self.result = False
        self.Close()
    
    def on_apply(self, sender, args):
        self.new_value = self.txtNewValue.Text
        self.result = True
        self.Close()


class CompareDialog(WPFWindow):
    def __init__(self, types, doc):
        WPFWindow.__init__(self, COMPARE_XAML, literal_string=True)
        self.types = types
        self.doc = doc
        
        for t in types:
            self.cmbType1.Items.Add(t.type_name)
            self.cmbType2.Items.Add(t.type_name)
        
        if len(types) >= 2:
            self.cmbType1.SelectedIndex = 0
            self.cmbType2.SelectedIndex = 1
        
        self.cmbType1.SelectionChanged += self.on_compare
        self.cmbType2.SelectionChanged += self.on_compare
        self.btnClose.Click += lambda s, e: self.Close()
        
        self.on_compare(None, None)
    
    def on_compare(self, sender, args):
        i1 = self.cmbType1.SelectedIndex
        i2 = self.cmbType2.SelectedIndex
        
        if i1 < 0 or i2 < 0 or i1 == i2:
            return
        
        p1 = {p.name: p.value for p in get_type_parameters(self.types[i1].symbol, False)}
        p2 = {p.name: p.value for p in get_type_parameters(self.types[i2].symbol, False)}
        
        self.dataGridCompare.Items.Clear()
        match_count = 0
        diff_count = 0
        
        for n in sorted(set(p1.keys()) | set(p2.keys())):
            v1 = p1.get(n, "N/A")
            v2 = p2.get(n, "N/A")
            is_match = v1 == v2
            
            if is_match:
                match_count += 1
            else:
                diff_count += 1
            
            self.dataGridCompare.Items.Add({
                "name": n,
                "value1": str(v1),
                "value2": str(v2),
                "match_display": "Yes" if is_match else "No"
            })
        
        self.txtStats.Text = "Match: {} | Different: {}".format(match_count, diff_count)


# ============================================================================
# MAIN WINDOW
# ============================================================================
class FamilyManagerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        
        self.items = []
        self.filtered = []
        self.cats = {}
        
        self.type_family_list = []
        self.cur_fam_types = None
        self.cur_types = []
        
        self.param_family_list = []
        self.cur_fam_params = None
        self.cur_type_params = None
        self.cur_params = []
        self._param_types = []
        
        self._setup_events()
        self.load_data()
        self.update_ui()
    
    def _setup_events(self):
        # Tab 1 - Families
        self.txtSearch.TextChanged += self.filter_families
        self.cmbFamilyType.SelectionChanged += self.filter_families
        self.cmbFilter.SelectionChanged += self.filter_families
        self.lstCategories.SelectionChanged += self.filter_families
        self.dataGrid.SelectionChanged += self.on_selection_changed
        self.dataGrid.MouseDoubleClick += self.edit_family
        
        self.btnHelp.Click += self.show_help
        self.btnSelectUnused.Click += self.select_unused
        self.btnPurgeUnused.Click += self.purge_unused
        
        # Bottom buttons - now context-aware
        self.btnSelectAll.Click += self.on_select_all
        self.btnClear.Click += self.on_clear
        self.btnRename.Click += self.on_rename  # Context-aware rename
        self.btnExport.Click += self.export_families
        self.btnImport.Click += self.import_families
        self.btnDelete.Click += self.on_delete  # Context-aware delete
        self.btnExportCSV.Click += self.export_csv
        self.btnExportHTML.Click += self.export_html
        self.btnRefresh.Click += self.refresh
        self.btnClose.Click += lambda s, e: self.Close()
        
        # Tab 2 - Type Manager
        self.txtTypeSearch.TextChanged += self.filter_type_families
        self.lstFamiliesForTypes.SelectionChanged += self.load_types
        self.btnRenameType.Click += self.rename_types
        self.btnDuplicateType.Click += self.duplicate_types
        self.btnDeleteType.Click += self.delete_types
        self.btnActivateType.Click += self.activate_type
        self.btnSelectInstances.Click += self.select_instances
        
        # Tab 3 - Parameters
        self.txtParamFamilySearch.TextChanged += self.filter_param_families
        self.lstFamiliesForParams.SelectionChanged += self.load_param_types
        self.lstTypesForParams.SelectionChanged += self.load_params
        self.cmbParamFilter.SelectionChanged += self.filter_params
        self.txtParamNameSearch.TextChanged += self.filter_params
        self.btnEditParam.Click += self.edit_param
        self.btnCopyParams.Click += self.copy_params
        self.btnExportParams.Click += self.export_params
        self.btnImportParams.Click += self.import_params
        self.btnCompareParams.Click += self.compare_params
        
        # Tab 4 - Health
        self.btnRunHealth.Click += self.run_health
        self.btnExportHealth.Click += self.export_health
    
    def get_current_tab(self):
        """Get current active tab index"""
        return self.tabControl.SelectedIndex
    
    def on_selection_changed(self, sender, args):
        try:
            self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)
        except:
            pass
    
    # ========== CONTEXT-AWARE BOTTOM BUTTONS ==========
    def on_select_all(self, sender, args):
        """Select all in current tab's grid"""
        tab = self.get_current_tab()
        if tab == 0:
            self.dataGrid.SelectAll()
        elif tab == 1:
            self.dataGridTypes.SelectAll()
        elif tab == 2:
            self.dataGridParams.SelectAll()
    
    def on_clear(self, sender, args):
        """Clear selection in current tab's grid"""
        tab = self.get_current_tab()
        if tab == 0:
            self.dataGrid.UnselectAll()
        elif tab == 1:
            self.dataGridTypes.UnselectAll()
        elif tab == 2:
            self.dataGridParams.UnselectAll()
    
    def on_rename(self, sender, args):
        """Context-aware rename based on current tab"""
        tab = self.get_current_tab()
        if tab == 0:
            self.rename_families(sender, args)
        elif tab == 1:
            self.rename_types(sender, args)
        else:
            forms.alert("Rename is only available in Families and Type Manager tabs", title="Info")
    
    def on_delete(self, sender, args):
        """Context-aware delete based on current tab"""
        tab = self.get_current_tab()
        if tab == 0:
            self.delete_families(sender, args)
        elif tab == 1:
            self.delete_types(sender, args)
        else:
            forms.alert("Delete is only available in Families and Type Manager tabs", title="Info")
    
    # ========== DATA LOADING ==========
    def load_data(self):
        # Load all families (Loadable + System + Groups) - grouped by family
        self.items = get_all_families(self.doc, include_loadable=True, include_system=True, include_groups=True)
        self.filtered = list(self.items)
        
        self.cats = {}
        for item in self.items:
            self.cats[item.category_name] = self.cats.get(item.category_name, 0) + 1
        
        # For Type Manager and Parameters - only loadable families
        self.type_family_list = [f for f in self.items if f.family_type in ["Loadable", "In-Place"] and f.family]
        self.param_family_list = [f for f in self.items if f.family_type in ["Loadable", "In-Place"] and f.family and f.type_count > 0]
    
    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtSelected.Text = "0"
        
        # Count by type
        loadable_count = len([i for i in self.items if i.family_type == "Loadable"])
        inplace_count = len([i for i in self.items if i.family_type == "In-Place"])
        system_count = len([i for i in self.items if i.family_type == "System"])
        groups_count = len([i for i in self.items if i.family_type == "Model Groups"])
        
        self.txtLoadable.Text = str(loadable_count + inplace_count)
        self.txtSystem.Text = str(system_count)
        self.txtGroups.Text = str(groups_count)
        self.txtUnused.Text = str(len([i for i in self.items if i.is_unused]))
        
        self.lstCategories.Items.Clear()
        self.lstCategories.Items.Add("All ({})".format(len(self.items)))
        for c in sorted(self.cats.keys()):
            self.lstCategories.Items.Add("{} ({})".format(c, self.cats[c]))
        self.lstCategories.SelectedIndex = 0
        
        self._update_type_family_list()
        self._update_param_family_list()
        self.update_grid()
    
    def _update_type_family_list(self):
        self.lstFamiliesForTypes.Items.Clear()
        for fam in self.type_family_list:
            self.lstFamiliesForTypes.Items.Add("{} ({})".format(fam.family_name, fam.type_count))
    
    def _update_param_family_list(self):
        self.lstFamiliesForParams.Items.Clear()
        for fam in self.param_family_list:
            self.lstFamiliesForParams.Items.Add("{} ({})".format(fam.family_name, fam.type_count))
    
    def update_grid(self):
        self.dataGrid.Items.Clear()
        for item in self.filtered:
            self.dataGrid.Items.Add(item)
    
    def filter_families(self, sender, args):
        # Prevent infinite loop when updating category list
        if hasattr(self, '_updating_categories') and self._updating_categories:
            return
        
        search = (self.txtSearch.Text or "").lower()
        
        # Family Type filter
        ft = self.cmbFamilyType.SelectedIndex
        # 0 = All, 1 = Loadable, 2 = System, 3 = Model Groups
        
        # Additional filter
        fi = self.cmbFilter.SelectedIndex
        # 0 = All, 1 = With Issues, 2 = Unused
        
        # First pass: filter by Family Type and additional filters (not category)
        pre_filtered = []
        for i in self.items:
            # Family type filter
            if ft == 1 and i.family_type not in ["Loadable", "In-Place"]:
                continue
            if ft == 2 and i.family_type != "System":
                continue
            if ft == 3 and i.family_type != "Model Groups":
                continue
            
            # Additional filter
            if fi == 1 and not i.has_issues:
                continue
            if fi == 2 and not i.is_unused:
                continue
            
            # Search filter
            if search and search not in i.family_name.lower():
                continue
            
            pre_filtered.append(i)
        
        # Update category list based on pre-filtered results
        filtered_cats = {}
        for i in pre_filtered:
            filtered_cats[i.category_name] = filtered_cats.get(i.category_name, 0) + 1
        
        # Remember current selection
        current_cat = None
        if self.lstCategories.SelectedIndex > 0:
            current_cat = str(self.lstCategories.SelectedItem).rsplit(" (", 1)[0]
        
        # Update category listbox (with flag to prevent re-entry)
        self._updating_categories = True
        self.lstCategories.Items.Clear()
        self.lstCategories.Items.Add("All ({})".format(len(pre_filtered)))
        new_index = 0
        idx = 1
        for c in sorted(filtered_cats.keys()):
            self.lstCategories.Items.Add("{} ({})".format(c, filtered_cats[c]))
            if c == current_cat:
                new_index = idx
            idx += 1
        
        # Restore selection if category still exists
        if new_index < self.lstCategories.Items.Count:
            self.lstCategories.SelectedIndex = new_index
        else:
            self.lstCategories.SelectedIndex = 0
        self._updating_categories = False
        
        # Second pass: apply category filter
        cat = None
        if self.lstCategories.SelectedIndex > 0:
            cat = str(self.lstCategories.SelectedItem).rsplit(" (", 1)[0]
        
        self.filtered = []
        for i in pre_filtered:
            if cat and i.category_name != cat:
                continue
            self.filtered.append(i)
        
        self.update_grid()
    
    def show_help(self, sender, args):
        forms.alert(
            "Family Manager v2.0\n\n"
            "Tabs:\n"
            "- Families: View/manage all families\n"
            "- Type Manager: Manage family types\n"
            "- Parameters: View/edit parameters\n"
            "- Health Check: Analyze issues\n\n"
            "Bottom buttons work based on current tab:\n"
            "- Rename: Families tab or Type Manager\n"
            "- Delete: Families tab or Type Manager\n"
            "- All/Clear: Select/deselect in current grid\n\n"
            "(c) Dang Quoc Truong (DQT)",
            title="Help"
        )
    
    def edit_family(self, sender, args):
        if self.dataGrid.SelectedItems.Count == 1:
            item = self.dataGrid.SelectedItem
            if item.family and item.family.IsEditable:
                try:
                    self.doc.EditFamily(item.family)
                except:
                    pass
    
    def select_unused(self, sender, args):
        self.dataGrid.UnselectAll()
        for i in self.filtered:
            if i.is_unused:
                self.dataGrid.SelectedItems.Add(i)
    
    def purge_unused(self, sender, args):
        unused = [i for i in self.items if i.is_unused and not i.is_in_place]
        if not unused:
            forms.alert("No unused families found", title="Info")
            return
        
        if not forms.alert("Delete {} unused families?".format(len(unused)), yes=True, no=True):
            return
        
        count = 0
        try:
            with revit.Transaction("Purge Unused"):
                for i in unused:
                    try:
                        self.doc.Delete(i.family.Id)
                        count += 1
                    except:
                        pass
            forms.alert("Purged {} families".format(count), title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
        
        self.load_data()
        self.update_ui()
    
    def rename_families(self, sender, args):
        """Rename Family Name (Families tab only manages Family names)"""
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select families first", title="Info")
            return
        
        selected = [item for item in self.dataGrid.SelectedItems]
        
        # Filter: Loadable families use Family.Name, System/Groups use _system_type.Name
        dlg = RenameDialog(selected, is_types=False, rename_family=True)
        dlg.ShowDialog()
        
        if dlg.result:
            count = 0
            errors = []
            try:
                with revit.Transaction("DQT - Rename Families"):
                    for i, item in enumerate(selected):
                        try:
                            old_name = item.family_name
                            new_name = dlg.get_new_name(old_name, "", i)
                            if new_name and new_name != old_name:
                                if item.family:
                                    # Loadable family - rename Family object
                                    item.family.Name = new_name
                                    count += 1
                                elif hasattr(item, '_system_type') and item._system_type:
                                    # System family or Group - rename type directly
                                    item._system_type.Name = new_name
                                    count += 1
                        except Exception as ex:
                            errors.append("{}: {}".format(item.family_name[:20], str(ex)[:30]))
                
                msg = "Renamed {} families".format(count)
                if errors:
                    msg += "\n\nErrors ({}):\n- {}".format(len(errors), "\n- ".join(errors[:3]))
                forms.alert(msg, title="Done")
            except Exception as ex:
                forms.alert("Error: {}".format(str(ex)), title="Error")
            
            self.load_data()
            self.update_ui()
    
    def export_families(self, sender, args):
        """Export loadable families with optional auto purge"""
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select families first", title="Info")
            return
        
        # Get selected items - only Loadable families can be exported
        selected = []
        skipped = 0
        for item in self.dataGrid.SelectedItems:
            if item.family_type == "Loadable" and item.family:
                selected.append(item)
            else:
                skipped += 1
        
        if not selected:
            forms.alert("Only Loadable families can be exported.\nSystem families and Groups cannot be exported.", title="Info")
            return
        
        # Show export options dialog
        opt_dlg = ExportOptionsDialog(len(selected))
        opt_dlg.ShowDialog()
        
        if not opt_dlg.result:
            return
        
        # Select folder
        from System.Windows.Forms import FolderBrowserDialog, DialogResult
        folder_dlg = FolderBrowserDialog()
        folder_dlg.Description = "Select folder to export families"
        
        if folder_dlg.ShowDialog() != DialogResult.OK:
            return
        
        export_path = folder_dlg.SelectedPath
        
        # Export families
        exported = 0
        purged_total = 0
        errors = []
        
        for item in selected:
            try:
                # Open family for editing
                fam_doc = self.doc.EditFamily(item.family)
                if not fam_doc:
                    errors.append("{}: Could not open".format(item.family_name))
                    continue
                
                # Auto purge if requested
                if opt_dlg.auto_purge:
                    try:
                        t = Transaction(fam_doc, "Purge Family")
                        t.Start()
                        success, purged, err = purge_family_document(fam_doc)
                        if success:
                            purged_total += purged
                            t.Commit()
                        else:
                            t.RollBack()
                    except:
                        pass
                
                # Save family
                safe_name = re.sub(r'[<>:"/\\|?*]', '_', item.family_name)
                file_path = os.path.join(export_path, "{}.rfa".format(safe_name))
                
                if os.path.exists(file_path) and not opt_dlg.overwrite:
                    fam_doc.Close(False)
                    errors.append("{}: File exists (skipped)".format(item.family_name))
                    continue
                
                opts = SaveAsOptions()
                opts.OverwriteExistingFile = True
                fam_doc.SaveAs(file_path, opts)
                fam_doc.Close(False)
                exported += 1
                
            except Exception as ex:
                errors.append("{}: {}".format(item.family_name, str(ex)))
        
        # Show results
        msg = "Exported {} of {} families".format(exported, len(selected))
        if opt_dlg.auto_purge:
            msg += "\nAuto-purged {} unused elements".format(purged_total)
        if skipped > 0:
            msg += "\nSkipped {} non-Loadable items".format(skipped)
        if errors:
            msg += "\n\nErrors ({}):\n- {}".format(len(errors), "\n- ".join(errors[:5]))
            if len(errors) > 5:
                msg += "\n... and {} more".format(len(errors) - 5)
        
        forms.alert(msg, title="Export Complete")
    
    def import_families(self, sender, args):
        from System.Windows.Forms import OpenFileDialog, DialogResult
        dlg = OpenFileDialog()
        dlg.Filter = "Revit Family|*.rfa"
        dlg.Multiselect = True
        dlg.Title = "Select families to import"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        count = 0
        try:
            with revit.Transaction("Import Families"):
                for f in dlg.FileNames:
                    try:
                        if self.doc.LoadFamily(f):
                            count += 1
                    except:
                        pass
            forms.alert("Imported {} families".format(count), title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
        
        self.load_data()
        self.update_ui()
    
    def delete_families(self, sender, args):
        """Delete selected families"""
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select families first", title="Info")
            return
        
        if not forms.alert("Delete {} families?".format(self.dataGrid.SelectedItems.Count), yes=True, no=True):
            return
        
        selected = [item for item in self.dataGrid.SelectedItems]
        count = 0
        errors = []
        try:
            with revit.Transaction("DQT - Delete Families"):
                for item in selected:
                    try:
                        if item.family:
                            # Loadable family - delete Family
                            self.doc.Delete(item.family.Id)
                            count += 1
                        elif hasattr(item, '_system_type') and item._system_type:
                            # System family or Group - delete type
                            self.doc.Delete(item._system_type.Id)
                            count += 1
                    except Exception as ex:
                        errors.append("{}: {}".format(item.family_name[:20], str(ex)[:30]))
            
            msg = "Deleted {} families".format(count)
            if errors:
                msg += "\n\nErrors ({}):\n- {}".format(len(errors), "\n- ".join(errors[:3]))
            forms.alert(msg, title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
        
        self.load_data()
        self.update_ui()
    
    def export_csv(self, sender, args):
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "CSV|*.csv"
        dlg.FileName = "Families.csv"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        try:
            with codecs.open(dlg.FileName, 'w', 'utf-8-sig') as f:
                f.write("ID,Family Name,Category,Kind,Types,Instances\n")
                for i in self.dataGrid.Items:
                    f.write("{},{},{},{},{},{}\n".format(
                        i.element_id, i.family_name, i.category_name,
                        i.family_type_display, i.type_count, i.instance_count
                    ))
            forms.alert("Exported!", title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def export_html(self, sender, args):
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "HTML|*.html"
        dlg.FileName = "Family_Report.html"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        try:
            html = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{font-family:Arial;padding:20px}h1{color:#F0CC88}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px}
th{background:#F0CC88}</style></head>
<body><h1>Family Report</h1>
<p>Total: {} families | Generated: {}</p>
<table><tr><th>Family Name</th><th>Category</th><th>Kind</th><th>Types</th><th>Instances</th></tr>""".format(
                len(self.items), datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            
            for i in self.items:
                html += "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    i.family_name, i.category_name, i.family_type_display, i.type_count, i.instance_count
                )
            
            html += "</table><p style='color:#888;margin-top:20px'>(c) Dang Quoc Truong (DQT)</p></body></html>"
            
            with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
                f.write(html)
            
            forms.alert("Report saved!", title="Done")
            os.startfile(dlg.FileName)
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def refresh(self, sender, args):
        self.load_data()
        self.update_ui()
        forms.alert("Found {} families".format(len(self.items)), title="Refresh")
    
    # ==================== TYPE MANAGER ====================
    def filter_type_families(self, sender, args):
        search = (self.txtTypeSearch.Text or "").lower()
        self.lstFamiliesForTypes.Items.Clear()
        for fam in self.type_family_list:
            if search in fam.family_name.lower():
                self.lstFamiliesForTypes.Items.Add("{} ({})".format(fam.family_name, fam.type_count))
    
    def load_types(self, sender, args):
        idx = self.lstFamiliesForTypes.SelectedIndex
        if idx < 0:
            return
        
        search = (self.txtTypeSearch.Text or "").lower()
        filtered_families = [f for f in self.type_family_list if search in f.family_name.lower()]
        
        if idx >= len(filtered_families):
            return
        
        self.cur_fam_types = filtered_families[idx]
        self.cur_types = get_family_types(self.doc, self.cur_fam_types.family)
        
        self.txtSelectedFamily.Text = self.cur_fam_types.family_name
        self.txtTypeCount.Text = "({} types)".format(len(self.cur_types))
        
        self.dataGridTypes.Items.Clear()
        for t in self.cur_types:
            self.dataGridTypes.Items.Add(t)
    
    def rename_types(self, sender, args):
        if self.dataGridTypes.SelectedItems.Count == 0:
            forms.alert("Select types first", title="Info")
            return
        
        selected = [t for t in self.dataGridTypes.SelectedItems]
        dlg = RenameDialog(selected, is_types=True, rename_family=False)
        dlg.ShowDialog()
        
        if dlg.result:
            count = 0
            try:
                with revit.Transaction("DQT - Rename Types"):
                    for i, t in enumerate(selected):
                        try:
                            new_name = dlg.get_new_name(t.type_name, t.family_name, i)
                            if new_name and new_name != t.type_name:
                                t.symbol.Name = new_name
                                count += 1
                        except:
                            pass
                forms.alert("Renamed {} types".format(count), title="Done")
            except Exception as ex:
                forms.alert("Error: {}".format(str(ex)), title="Error")
            
            self.load_types(None, None)
    
    def duplicate_types(self, sender, args):
        if self.dataGridTypes.SelectedItems.Count == 0:
            forms.alert("Select types first", title="Info")
            return
        
        suffix = forms.ask_for_string(prompt="Enter suffix:", default="_Copy", title="Duplicate")
        if not suffix:
            return
        
        count = 0
        try:
            with revit.Transaction("Duplicate Types"):
                for t in self.dataGridTypes.SelectedItems:
                    try:
                        t.symbol.Duplicate(t.type_name + suffix)
                        count += 1
                    except:
                        pass
            forms.alert("Duplicated {} types".format(count), title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
        
        self.load_types(None, None)
        self.load_data()
        self.update_ui()
    
    def delete_types(self, sender, args):
        if self.dataGridTypes.SelectedItems.Count == 0:
            forms.alert("Select types first", title="Info")
            return
        
        if not forms.alert("Delete {} types?".format(self.dataGridTypes.SelectedItems.Count), yes=True, no=True):
            return
        
        selected = [t for t in self.dataGridTypes.SelectedItems]
        count = 0
        try:
            with revit.Transaction("Delete Types"):
                for t in selected:
                    try:
                        self.doc.Delete(t.symbol.Id)
                        count += 1
                    except:
                        pass
            forms.alert("Deleted {} types".format(count), title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
        
        self.load_types(None, None)
        self.load_data()
        self.update_ui()
    
    def activate_type(self, sender, args):
        if self.dataGridTypes.SelectedItems.Count != 1:
            forms.alert("Select one type", title="Info")
            return
        
        t = self.dataGridTypes.SelectedItem
        try:
            with revit.Transaction("Activate Type"):
                t.symbol.Activate()
            forms.alert("Type '{}' activated".format(t.type_name), title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def select_instances(self, sender, args):
        if self.dataGridTypes.SelectedItems.Count == 0:
            forms.alert("Select types first", title="Info")
            return
        
        ids = List[ElementId]()
        selected_type_ids = set()
        for t in self.dataGridTypes.SelectedItems:
            selected_type_ids.add(t.symbol.Id)
        
        collector = FilteredElementCollector(self.doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
        for inst in collector:
            try:
                if inst.Symbol and inst.Symbol.Id in selected_type_ids:
                    ids.Add(inst.Id)
            except:
                pass
        
        if ids.Count > 0:
            self.uidoc.Selection.SetElementIds(ids)
            forms.alert("Selected {} instances".format(ids.Count), title="Done")
        else:
            forms.alert("No instances found", title="Info")
    
    # ==================== PARAMETER MANAGER ====================
    def filter_param_families(self, sender, args):
        search = (self.txtParamFamilySearch.Text or "").lower()
        self.lstFamiliesForParams.Items.Clear()
        for fam in self.param_family_list:
            if search in fam.family_name.lower():
                self.lstFamiliesForParams.Items.Add("{} ({})".format(fam.family_name, fam.type_count))
    
    def load_param_types(self, sender, args):
        idx = self.lstFamiliesForParams.SelectedIndex
        if idx < 0:
            return
        
        search = (self.txtParamFamilySearch.Text or "").lower()
        filtered_families = [f for f in self.param_family_list if search in f.family_name.lower()]
        
        if idx >= len(filtered_families):
            return
        
        self.cur_fam_params = filtered_families[idx]
        self._param_types = get_family_types(self.doc, self.cur_fam_params.family)
        
        self.lstTypesForParams.Items.Clear()
        for t in self._param_types:
            self.lstTypesForParams.Items.Add(t.type_name)
        
        if self._param_types:
            self.lstTypesForParams.SelectedIndex = 0
    
    def load_params(self, sender, args):
        idx = self.lstTypesForParams.SelectedIndex
        if idx < 0 or not self._param_types:
            return
        
        if idx >= len(self._param_types):
            return
        
        self.cur_type_params = self._param_types[idx]
        self.cur_params = get_type_parameters(self.cur_type_params.symbol, True)
        
        self.txtSelectedType.Text = "{} : {}".format(self.cur_fam_params.family_name, self.cur_type_params.type_name)
        self.txtParamCount.Text = "({} params)".format(len(self.cur_params))
        
        self.filter_params(None, None)
    
    def filter_params(self, sender, args):
        if not self.cur_params:
            return
        
        search = (self.txtParamNameSearch.Text or "").lower()
        fi = self.cmbParamFilter.SelectedIndex
        
        self.dataGridParams.Items.Clear()
        for p in self.cur_params:
            if fi == 1 and p.is_instance:
                continue
            if fi == 2 and not p.is_instance:
                continue
            if fi == 3 and not p.is_shared:
                continue
            if search and search not in p.name.lower():
                continue
            self.dataGridParams.Items.Add(p)
    
    def edit_param(self, sender, args):
        if self.dataGridParams.SelectedItems.Count != 1:
            forms.alert("Select one parameter", title="Info")
            return
        
        p = self.dataGridParams.SelectedItem
        if p.is_read_only:
            forms.alert("Parameter is read-only", title="Info")
            return
        
        dlg = EditParamDialog(p)
        dlg.ShowDialog()
        
        if dlg.result:
            try:
                with revit.Transaction("Edit Parameter"):
                    param = p.parameter
                    st = param.StorageType
                    if st == StorageType.String:
                        param.Set(dlg.new_value)
                    elif st == StorageType.Integer:
                        param.Set(int(dlg.new_value))
                    elif st == StorageType.Double:
                        param.Set(float(dlg.new_value))
                forms.alert("Parameter updated!", title="Done")
                self.load_params(None, None)
            except Exception as ex:
                forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def copy_params(self, sender, args):
        if self.dataGridParams.SelectedItems.Count == 0:
            forms.alert("Select parameters first", title="Info")
            return
        
        if not self.cur_fam_params or not self._param_types:
            return
        
        others = [t for t in self._param_types if t.type_name != self.cur_type_params.type_name]
        if not others:
            forms.alert("No other types available", title="Info")
            return
        
        names = forms.SelectFromList.show([t.type_name for t in others], title="Select Target Types", multiselect=True)
        if not names:
            return
        
        targets = [t for t in others if t.type_name in names]
        params = [p for p in self.dataGridParams.SelectedItems if not p.is_instance and not p.is_read_only]
        
        if not params:
            forms.alert("No copyable type parameters selected", title="Info")
            return
        
        count = 0
        try:
            with revit.Transaction("Copy Parameters"):
                for t in targets:
                    for pd in params:
                        try:
                            tp = t.symbol.LookupParameter(pd.name)
                            if tp and not tp.IsReadOnly:
                                src = pd.parameter
                                st = src.StorageType
                                if st == StorageType.String:
                                    tp.Set(src.AsString() or "")
                                elif st == StorageType.Integer:
                                    tp.Set(src.AsInteger())
                                elif st == StorageType.Double:
                                    tp.Set(src.AsDouble())
                                elif st == StorageType.ElementId:
                                    tp.Set(src.AsElementId())
                                count += 1
                        except:
                            pass
            forms.alert("Copied {} values".format(count), title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def export_params(self, sender, args):
        if not self.cur_fam_params or not self._param_types:
            forms.alert("Select a family first", title="Info")
            return
        
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "CSV|*.csv"
        dlg.FileName = "{}_Params.csv".format(self.cur_fam_params.name)
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        try:
            types = self._param_types
            all_params = set()
            type_params = {}
            
            for t in types:
                ps = get_type_parameters(t.symbol, False)
                type_params[t.type_name] = {p.name: p.value for p in ps}
                for p in ps:
                    all_params.add(p.name)
            
            param_list = sorted(list(all_params))
            
            with codecs.open(dlg.FileName, 'w', 'utf-8-sig') as f:
                f.write("Type," + ",".join(param_list) + "\n")
                for t in types:
                    vals = [str(type_params[t.type_name].get(p, "")) for p in param_list]
                    f.write(t.type_name + "," + ",".join(vals) + "\n")
            
            forms.alert("Exported!", title="Done")
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def import_params(self, sender, args):
        if not self.cur_fam_params or not self._param_types:
            forms.alert("Select a family first", title="Info")
            return
        
        from System.Windows.Forms import OpenFileDialog, DialogResult
        dlg = OpenFileDialog()
        dlg.Filter = "CSV|*.csv"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        try:
            types = self._param_types
            type_dict = {t.type_name: t for t in types}
            
            count = 0
            with codecs.open(dlg.FileName, 'r', 'utf-8-sig') as f:
                lines = f.readlines()
                if not lines:
                    return
                
                header = lines[0].strip().split(',')
                param_names = header[1:]
                
                with revit.Transaction("Import Parameters"):
                    for line in lines[1:]:
                        parts = line.strip().split(',')
                        if not parts:
                            continue
                        
                        type_name = parts[0]
                        if type_name not in type_dict:
                            continue
                        
                        symbol = type_dict[type_name].symbol
                        for i, pn in enumerate(param_names):
                            if i + 1 >= len(parts):
                                continue
                            
                            value = parts[i + 1]
                            param = symbol.LookupParameter(pn)
                            
                            if param and not param.IsReadOnly:
                                try:
                                    st = param.StorageType
                                    if st == StorageType.String:
                                        param.Set(value)
                                    elif st == StorageType.Integer:
                                        param.Set(int(value))
                                    elif st == StorageType.Double:
                                        param.Set(float(value))
                                    count += 1
                                except:
                                    pass
            
            forms.alert("Updated {} values".format(count), title="Done")
            self.load_params(None, None)
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")
    
    def compare_params(self, sender, args):
        if not self.cur_fam_params or not self._param_types:
            forms.alert("Select a family first", title="Info")
            return
        
        types = self._param_types
        if len(types) < 2:
            forms.alert("Need at least 2 types to compare", title="Info")
            return
        
        CompareDialog(types, self.doc).ShowDialog()
    
    # ==================== HEALTH CHECK ====================
    def run_health(self, sender, args):
        self.txtHealthStatus.Text = "Analyzing..."
        self.healthPanel.Children.Clear()
        
        results = []
        
        # Large families (estimated size > 5MB)
        large = [f for f in self.items if f.estimated_size_kb >= Config.err_size_kb]
        if large:
            results.append(("Large Families ({})".format(len(large)), [f.family_name for f in large[:10]], "#FF9800"))
        
        # Unused families
        unused = [f for f in self.items if f.is_unused and not f.is_in_place]
        if unused:
            results.append(("Unused Families ({})".format(len(unused)), [f.family_name for f in unused[:10]], "#2196F3"))
        
        # Non-standard names (only for Loadable families)
        bad = [f for f in self.items if f.family_type == "Loadable" and not any(re.match(p, f.family_name) for p in Config.patterns)]
        if bad:
            results.append(("Non-Standard Names ({})".format(len(bad)), [f.family_name for f in bad[:10]], "#9C27B0"))
        
        # In-Place families
        inp = [f for f in self.items if f.is_in_place]
        if inp:
            results.append(("In-Place Families ({})".format(len(inp)), [f.family_name for f in inp[:10]], "#FF5722"))
        
        if not results:
            tb = System.Windows.Controls.TextBlock()
            tb.Text = "All families look healthy!"
            tb.Foreground = System.Windows.Media.Brushes.Green
            tb.FontWeight = System.Windows.FontWeights.SemiBold
            self.healthPanel.Children.Add(tb)
        else:
            for title, items, color in results:
                title_tb = System.Windows.Controls.TextBlock()
                title_tb.Text = title
                title_tb.FontWeight = System.Windows.FontWeights.SemiBold
                title_tb.Margin = System.Windows.Thickness(0, 10, 0, 4)
                try:
                    title_tb.Foreground = System.Windows.Media.BrushConverter().ConvertFromString(color)
                except:
                    pass
                self.healthPanel.Children.Add(title_tb)
                
                for item in items:
                    item_tb = System.Windows.Controls.TextBlock()
                    item_tb.Text = "  - " + item
                    item_tb.Foreground = System.Windows.Media.Brushes.Gray
                    self.healthPanel.Children.Add(item_tb)
        
        total_issues = sum(len(r[1]) for r in results)
        self.txtHealthStatus.Text = "Found {} issues".format(total_issues)
        self.btnExportHealth.IsEnabled = len(results) > 0
    
    def export_health(self, sender, args):
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "HTML|*.html"
        dlg.FileName = "Health_Report.html"
        
        if dlg.ShowDialog() != DialogResult.OK:
            return
        
        try:
            # Count issues
            large_count = len([f for f in self.items if f.estimated_size_kb >= Config.err_size_kb])
            unused_count = len([f for f in self.items if f.is_unused])
            nonstandard_count = len([f for f in self.items if f.family_type == "Loadable" and not any(re.match(p, f.family_name) for p in Config.patterns)])
            inplace_count = len([f for f in self.items if f.is_in_place])
            
            html = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{font-family:Arial;padding:20px}h1{color:#F0CC88}</style></head>
<body><h1>Family Health Report</h1>
<p>Generated: {}</p>
<p>Total families: {}</p>
<h2>Summary</h2>
<ul>
<li>Large: {}</li>
<li>Unused: {}</li>
<li>Non-standard names: {}</li>
<li>In-Place: {}</li>
</ul>
<p style="color:#888;margin-top:30px">(c) Dang Quoc Truong (DQT)</p>
</body></html>""".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                len(self.items),
                large_count,
                unused_count,
                nonstandard_count,
                inplace_count
            )
            
            with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
                f.write(html)
            
            forms.alert("Report saved!", title="Done")
            os.startfile(dlg.FileName)
        except Exception as ex:
            forms.alert("Error: {}".format(str(ex)), title="Error")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first", title="Family Manager")
        else:
            FamilyManagerWindow().ShowDialog()
    except Exception as ex:
        forms.alert("Error: {}".format(str(ex)), title="Family Manager Error")