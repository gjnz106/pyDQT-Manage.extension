# -*- coding: utf-8 -*-
"""IFC-SG Subtype Definer - Define IFC Entity & Predefined Type for CORENET X.
Loads mapping from the official IFC+SG Industry Mapping Excel (COP edition 3)
and batch-assigns IFC Export Class and Predefined Type to Revit elements.
"""

__title__ = "IFC-SG\nSubtype"
__author__ = "DQT"

import clr
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System
from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows import Window, Thickness, Visibility
from System.Windows import MessageBox as WPFMessageBox
from System.Windows import MessageBoxButton, MessageBoxResult, MessageBoxImage
from System.Windows.Markup import XamlReader
from System.Windows.Media import BrushConverter, SolidColorBrush, Color
from System.Windows.Controls import DataGridTextColumn
from System.Windows.Data import Binding
from System.Windows.Forms import OpenFileDialog, DialogResult as WFDialogResult

import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInParameter, BuiltInCategory,
    Transaction, ElementId
)
from pyrevit import script

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()

# ==============================================================================
# DQT Color Scheme - Synced with Contains Manager
# ==============================================================================

class Config(object):
    PRIMARY = "#F0CC88"        # Gold - header bg, column headers
    SECONDARY = "#E5B85C"      # Darker gold - selected, hover
    BACKGROUND = "#FEF8E7"     # Cream - main background
    CARD_BG = "#FFFFFF"        # White - card/panel backgrounds
    BORDER = "#D4B87A"         # Gold border
    TEXT_PRIMARY = "#333333"   # Dark text
    TEXT_SECONDARY = "#888888" # Gray text
    TEXT_DARK = "#5D4E37"      # Brown - footer text
    SUCCESS = "#4CAF50"
    WARNING = "#FF9800"
    ERROR = "#FF6B6B"
    ROW_ALT = "#FFFDF5"       # Alternating row
    FOOTER_BG = "#F0CC88"     # Gold footer
    BUTTON_PRIMARY_BG = "#E5B85C"
    BUTTON_PRIMARY_FG = "#FFFFFF"
    BUTTON_SECONDARY_BG = "#F5E6C8"
    BUTTON_SECONDARY_FG = "#5D4E37"

bc = BrushConverter()


# ==============================================================================
# Revit Category Name -> BuiltInCategory
# ==============================================================================

def _bic(*names):
    """First BuiltInCategory that exists in this Revit version.

    Category enum members come and go between releases - OST_Toposolid only
    exists from Revit 2024 - so resolve by name and fall back rather than
    referencing a member that may not be there (which would crash the whole
    script at import time, before the window even opens)."""
    for name in names:
        try:
            value = getattr(BuiltInCategory, name, None)
            if value is not None:
                return value
        except:
            pass
    return None


REVIT_CAT_MAP = {
    "Areas": [_bic("OST_Areas")],
    "Casework": [_bic("OST_Casework")],
    "Ceilings": [_bic("OST_Ceilings")],
    "Columns": [_bic("OST_Columns")],
    "Curtain Systems": [_bic("OST_CurtainWallPanels")],
    "Curtain Wall Panels": [_bic("OST_CurtainWallPanels")],
    "Curtain Wall Mullions": [_bic("OST_CurtainWallMullions")],
    "Doors": [_bic("OST_Doors")],
    "Duct Accessories": [_bic("OST_DuctAccessory")],
    "Duct Fittings": [_bic("OST_DuctFitting")],
    "Ducts": [_bic("OST_DuctCurves")],
    "Electrical Equipment": [_bic("OST_ElectricalEquipment")],
    "Electrical Fixtures": [_bic("OST_ElectricalFixtures")],
    "Fire Alarm Devices": [_bic("OST_FireAlarmDevices")],
    "Floors": [_bic("OST_Floors")],
    "Furniture": [_bic("OST_Furniture")],
    "Generic Models": [_bic("OST_GenericModel")],
    "Levels": [_bic("OST_Levels")],
    "Lighting Fixtures": [_bic("OST_LightingFixtures")],
    "Mechanical Equipment": [_bic("OST_MechanicalEquipment")],
    "Parking": [_bic("OST_Parking")],
    "Pipe Accessories": [_bic("OST_PipeAccessory")],
    "Pipe Fittings": [_bic("OST_PipeFitting")],
    "Pipes": [_bic("OST_PipeCurves")],
    "Planting": [_bic("OST_Planting")],
    "Plumbing Fixtures": [_bic("OST_PlumbingFixtures")],
    "Railings": [_bic("OST_StairsRailing")],
    "Ramps": [_bic("OST_Ramps")],
    "Roofs": [_bic("OST_Roofs")],
    "Rooms": [_bic("OST_Rooms")],
    "Shaft Openings": [_bic("OST_ShaftOpening")],
    "Spaces": [_bic("OST_MEPSpaces")],
    "Specialty Equipment": [_bic("OST_SpecialityEquipment")],
    "Sprinklers": [_bic("OST_Sprinklers")],
    "Stairs": [_bic("OST_Stairs")],
    "Structural Columns": [_bic("OST_StructuralColumns")],
    "Structural Foundations": [_bic("OST_StructuralFoundation")],
    "Structural Framing": [_bic("OST_StructuralFraming")],
    # Toposolid (Revit 2024+) is its own category - OST_Topography is the old
    # toposurface and finds nothing in a toposolid-based External Works model.
    "Toposolid": [_bic("OST_Toposolid", "OST_Topography")],
    "Toposolids": [_bic("OST_Toposolid", "OST_Topography")],
    "Topography": [_bic("OST_Topography")],
    "Walls": [_bic("OST_Walls")],
    "Windows": [_bic("OST_Windows")],
}
# Drop any entry a Revit version doesn't have (kept None by _bic) so a
# lookup falls through to "unmapped" instead of collecting on None.
REVIT_CAT_MAP = dict((k, [b for b in v if b is not None])
                      for k, v in REVIT_CAT_MAP.items())

# Case/whitespace-insensitive lookup - the government Excel's "Suggested
# Revit Representation" column is hand-typed and inconsistent (extra spaces,
# different casing), and an exact-match miss used to fail silently: the
# component would just show 0 elements with no indication why.
REVIT_CAT_LOOKUP = dict((k.strip().lower(), k) for k in REVIT_CAT_MAP)


def resolve_revit_categories(name):
    """BuiltInCategory list for an Excel category name, or [] if unknown."""
    key = REVIT_CAT_LOOKUP.get(str(name).strip().lower())
    return REVIT_CAT_MAP.get(key, []) if key else []


# ==============================================================================
# Excel Reader (COM Interop) + Column Mapping Dialog
# ==============================================================================

def read_excel_headers(filepath):
    """Read sheet names and column headers from Excel without full parse.

    A COP mapping workbook typically has several sheets (cover, notes,
    pilot list, mapping...) and not all of them hold a normal data table -
    a chart sheet or one with no UsedRange used to abort the ENTIRE read on
    the first bad sheet, discarding headers already read from good ones.
    Each sheet is now read independently and a bad one is skipped."""
    clr.AddReference("Microsoft.Office.Interop.Excel")
    import Microsoft.Office.Interop.Excel as Excel

    app = None
    wb = None
    result = {"sheets": [], "headers": {}}
    skipped = []

    try:
        app = Excel.ApplicationClass()
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(filepath)

        for i in range(1, wb.Sheets.Count + 1):
            sname = "sheet {}".format(i)
            try:
                ws = wb.Sheets[i]
                sname = ws.Name
                headers = []
                used = ws.UsedRange
                col_count = used.Columns.Count if used is not None else 0
                for c in range(1, min(col_count + 1, 30)):
                    val = ws.Cells[1, c].Value2
                    if val is None:
                        h = "(empty)"
                    else:
                        h = str(val).strip().replace("\n", " ")
                        if h == "":
                            h = "(empty)"
                    headers.append(h)
                result["sheets"].append(sname)
                result["headers"][sname] = headers
            except Exception as ex:
                skipped.append("{} ({})".format(sname, str(ex)))
                continue

        wb.Close(False)
        wb = None
    except Exception as ex:
        output.print_md("**Excel Error:** {}".format(str(ex)))
        return None
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except:
            pass
        try:
            if app is not None:
                app.Quit()
        except:
            pass

    if skipped:
        output.print_md("**Skipped {} sheet(s) that could not be read:** {}".format(
            len(skipped), ", ".join(skipped)))
    if not result["sheets"]:
        output.print_md("**Excel Error:** no readable sheets found in the file.")
        return None
    return result


def show_column_mapping_dialog(excel_info, filepath):
    """Show a WPF dialog for user to pick which column maps to which field.
    Returns dict with keys: sheet, component, entity, subtype, revit, agency
    Each value is a column index (1-based) or 0 if not mapped.
    """
    MAP_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Column Mapping | IFC-SG Subtype Definer"
        Width="560" Height="460" WindowStartupLocation="CenterScreen"
        Background="%%BG%%">
    <Grid Margin="16">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Text="Map Excel Columns to IFC-SG Fields" FontSize="15"
                   FontWeight="Bold" Foreground="%%TEXT%%" Margin="0,0,0,8"/>

        <StackPanel Grid.Row="1" Margin="0,0,0,10">
            <TextBlock Text="Sheet:" FontSize="11" FontWeight="SemiBold"
                       Foreground="%%TEXT%%" Margin="0,0,0,3"/>
            <ComboBox x:Name="cmbSheet" FontSize="12" Height="28"/>
        </StackPanel>

        <Grid Grid.Row="2">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="160"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Grid.RowDefinitions>
                <RowDefinition Height="32"/>
                <RowDefinition Height="32"/>
                <RowDefinition Height="32"/>
                <RowDefinition Height="32"/>
                <RowDefinition Height="32"/>
                <RowDefinition Height="32"/>
            </Grid.RowDefinitions>

            <TextBlock Text="Component Name *" Grid.Row="0" VerticalAlignment="Center"
                       FontWeight="SemiBold" Foreground="%%TEXT%%"/>
            <ComboBox x:Name="cmbComponent" Grid.Row="0" Grid.Column="1" Margin="4,2"/>

            <TextBlock Text="IFC4 Entity *" Grid.Row="1" VerticalAlignment="Center"
                       FontWeight="SemiBold" Foreground="%%TEXT%%"/>
            <ComboBox x:Name="cmbEntity" Grid.Row="1" Grid.Column="1" Margin="4,2"/>

            <TextBlock Text="IFC Sub Types" Grid.Row="2" VerticalAlignment="Center"
                       Foreground="%%TEXT%%"/>
            <ComboBox x:Name="cmbSubtype" Grid.Row="2" Grid.Column="1" Margin="4,2"/>

            <TextBlock Text="Revit Representation" Grid.Row="3" VerticalAlignment="Center"
                       Foreground="%%TEXT%%"/>
            <ComboBox x:Name="cmbRevit" Grid.Row="3" Grid.Column="1" Margin="4,2"/>

            <TextBlock Text="Agency" Grid.Row="4" VerticalAlignment="Center"
                       Foreground="%%TEXT%%"/>
            <ComboBox x:Name="cmbAgency" Grid.Row="4" Grid.Column="1" Margin="4,2"/>

            <TextBlock Text="* = Required" Grid.Row="5" Foreground="%%GRAY%%"
                       FontSize="10" VerticalAlignment="Center"/>
        </Grid>

        <StackPanel Grid.Row="3" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,10,0,0">
            <Button x:Name="btnOK" Content="OK" Width="90" Height="30"
                    Background="%%BTN_BG%%" Foreground="%%BTN_FG%%"
                    FontWeight="Bold" BorderThickness="0" Cursor="Hand"
                    Margin="0,0,8,0"/>
            <Button x:Name="btnCancel" Content="Cancel" Width="90" Height="30"
                    Background="%%BTN2_BG%%" Foreground="%%BTN2_FG%%"
                    BorderBrush="%%BORDER%%" BorderThickness="1" Cursor="Hand"/>
        </StackPanel>
    </Grid>
</Window>
""".replace("%%BG%%", Config.BACKGROUND) \
   .replace("%%TEXT%%", Config.TEXT_PRIMARY) \
   .replace("%%GRAY%%", Config.TEXT_SECONDARY) \
   .replace("%%BORDER%%", Config.BORDER) \
   .replace("%%BTN_BG%%", Config.BUTTON_PRIMARY_BG) \
   .replace("%%BTN_FG%%", Config.BUTTON_PRIMARY_FG) \
   .replace("%%BTN2_BG%%", Config.BUTTON_SECONDARY_BG) \
   .replace("%%BTN2_FG%%", Config.BUTTON_SECONDARY_FG)

    stream = MemoryStream(Encoding.UTF8.GetBytes(MAP_XAML))
    win = XamlReader.Load(stream)
    stream.Close()

    cmbSheet = win.FindName("cmbSheet")
    field_combos = {
        "component": win.FindName("cmbComponent"),
        "entity": win.FindName("cmbEntity"),
        "subtype": win.FindName("cmbSubtype"),
        "revit": win.FindName("cmbRevit"),
        "agency": win.FindName("cmbAgency"),
    }

    result = {"ok": False}

    # Auto-detect keywords for each field
    AUTO_KEYWORDS = {
        "component": ["identified component", "component", "element name"],
        "entity": ["ifc4", "ifc entity", "entities"],
        "subtype": ["ifc sub", "sub type", "predefined"],
        "revit": ["suggested revit", "revit representation", "revit"],
        "agency": ["agency"],
    }

    def populate_combos(sheet_name):
        headers = excel_info["headers"].get(sheet_name, [])
        for field, cmb in field_combos.items():
            cmb.Items.Clear()
            cmb.Items.Add("(not mapped)")
            best_idx = 0
            for i, h in enumerate(headers):
                cmb.Items.Add("Col {}: {}".format(i + 1, h))
                # Auto-detect
                h_lower = h.lower()
                for kw in AUTO_KEYWORDS.get(field, []):
                    if kw in h_lower and best_idx == 0:
                        best_idx = i + 1
            cmb.SelectedIndex = best_idx

    # A flag rather than relying on handler-attachment order: WPF can defer
    # a ComboBox's SelectionChanged until the control is actually loaded
    # into the visual tree, which happens during ShowDialog() below - by
    # then the handler IS attached, so the "set SelectedIndex before
    # wiring the handler" ordering doesn't reliably prevent a double fire.
    # This is what let an unguarded exception from that first, unexpected
    # fire escape all the way out through ShowDialog() and crash the tool.
    ready = {"flag": False}

    def safe_handler(fn):
        """Swallow and report anything a dialog event handler raises,
        instead of letting it unwind through ShowDialog() and crash the
        whole tool - the exact way this dialog used to be able to bring the
        entire window down from what looks like a single button click."""
        def wrapped(s, e):
            if not ready["flag"]:
                return
            try:
                fn(s, e)
            except Exception as ex:
                import traceback
                output.print_md("**Column Mapping dialog error:**")
                output.print_md("```\n{}\n```".format(traceback.format_exc()))
                WPFMessageBox.Show(
                    "Something went wrong in the column mapping dialog:\n{}".format(str(ex)),
                    "Error", MessageBoxButton.OK, MessageBoxImage.Error)
        return wrapped

    # Populate sheets
    for sname in excel_info["sheets"]:
        cmbSheet.Items.Add(sname)
    # Auto-select sheet with "mapping" or "pilot" in name
    best_sheet = 0
    for i, sname in enumerate(excel_info["sheets"]):
        if "pilot" in sname.lower() or "mapping" in sname.lower():
            best_sheet = i
            break

    def on_sheet_changed(s, e):
        sel = cmbSheet.SelectedItem
        if sel:
            populate_combos(str(sel))

    cmbSheet.SelectionChanged += safe_handler(on_sheet_changed)
    cmbSheet.SelectedIndex = best_sheet
    populate_combos(excel_info["sheets"][best_sheet])

    def on_ok(s, e):
        # Validate required fields
        comp_idx = field_combos["component"].SelectedIndex
        ent_idx = field_combos["entity"].SelectedIndex
        if comp_idx == 0 or ent_idx == 0:
            WPFMessageBox.Show("Component Name and IFC4 Entity are required.",
                               "Missing Fields", MessageBoxButton.OK,
                               MessageBoxImage.Warning)
            return
        result["ok"] = True
        result["sheet"] = str(cmbSheet.SelectedItem)
        for field, cmb in field_combos.items():
            idx = cmb.SelectedIndex
            result[field] = idx if idx > 0 else 0  # 0 = not mapped, else 1-based col
        win.Close()

    def on_cancel(s, e):
        win.Close()

    win.FindName("btnOK").Click += safe_handler(on_ok)
    win.FindName("btnCancel").Click += safe_handler(on_cancel)
    # Only now let the handlers actually run - the manual populate_combos()
    # call just above already did the initial fill, so a deferred replay of
    # the SelectedIndex assignment before this point is intentionally a
    # no-op rather than a second, uncontrolled pass.
    ready["flag"] = True
    win.ShowDialog()
    return result


def load_mapping_with_dialog(filepath):
    """Load Excel with Column Mapping Dialog."""
    excel_info = read_excel_headers(filepath)
    if not excel_info:
        return None

    col_result = show_column_mapping_dialog(excel_info, filepath)
    if not col_result.get("ok"):
        return None

    # Now parse with user-selected columns
    clr.AddReference("Microsoft.Office.Interop.Excel")
    import Microsoft.Office.Interop.Excel as Excel

    app = None
    wb = None
    mapping = {}
    bad_rows = []

    try:
        app = Excel.ApplicationClass()
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(filepath)
        ws = wb.Sheets[col_result["sheet"]]
        rows = ws.UsedRange.Rows.Count

        c_comp = col_result["component"]
        c_ent = col_result["entity"]
        c_sub = col_result.get("subtype", 0)
        c_rev = col_result.get("revit", 0)
        c_agency = col_result.get("agency", 0)

        for r in range(2, rows + 1):
            # One malformed row (a merged cell, a stray chart object) used to
            # abort the whole import and discard every row already read.
            try:
                raw_comp = ws.Cells[r, c_comp].Value2
                if raw_comp is None:
                    continue
                comp = str(raw_comp).strip()
                if not comp:
                    continue

                raw_entity = ws.Cells[r, c_ent].Value2
                entity = str(raw_entity).strip() if raw_entity is not None else ""

                subtypes_in_cell = []
                if c_sub:
                    raw_sub = ws.Cells[r, c_sub].Value2
                    if raw_sub is not None and str(raw_sub).strip() not in \
                            ("N.A", "N.A.", "nan", ""):
                        for s in str(raw_sub).split(","):
                            s = s.strip()
                            if s and s not in ("N.A", "N.A."):
                                subtypes_in_cell.append(s)

                revit_cat = ""
                if c_rev:
                    raw_revit = ws.Cells[r, c_rev].Value2
                    revit_cat = str(raw_revit).strip() if raw_revit is not None else ""

                agency = ""
                if c_agency:
                    raw_ag = ws.Cells[r, c_agency].Value2
                    agency = str(raw_ag).strip() if raw_ag is not None else ""

                if comp not in mapping:
                    mapping[comp] = {
                        "ifc_entities": set(), "subtypes": set(),
                        "revit_categories": set(), "agencies": set(),
                    }
                m = mapping[comp]
                if entity:
                    m["ifc_entities"].add(entity)
                for st in subtypes_in_cell:
                    m["subtypes"].add(st)
                if revit_cat and revit_cat not in ("N.A", "N.A."):
                    m["revit_categories"].add(revit_cat)
                if agency:
                    m["agencies"].add(agency)
            except Exception as ex:
                bad_rows.append("row {}: {}".format(r, str(ex)))
                continue

        wb.Close(False)
        wb = None
    except Exception as ex:
        output.print_md("**Excel Error:** {}".format(str(ex)))
        return None
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except:
            pass
        try:
            if app is not None:
                app.Quit()
        except:
            pass

    if bad_rows:
        output.print_md("**Skipped {} row(s) that could not be read:**".format(
            len(bad_rows)))
        for line in bad_rows[:30]:
            output.print_md("- " + line)

    for comp, m in mapping.items():
        m["ifc_entities"] = sorted(m["ifc_entities"])
        m["subtypes"] = sorted(m["subtypes"])
        m["revit_categories"] = sorted(m["revit_categories"])
        m["agencies"] = sorted(m["agencies"])

    return mapping


# ==============================================================================
# IFC Parameter Helpers
# ==============================================================================

def _try_bip_get(elem, bip_name):
    try:
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            p = elem.get_Parameter(bip)
            if p and p.HasValue:
                v = p.AsString()
                if v:
                    return v
    except:
        pass
    return None

def _try_lookup_get(elem, name):
    try:
        p = elem.LookupParameter(name)
        if p and p.HasValue:
            v = p.AsString()
            if v:
                return v
    except:
        pass
    return None

def _try_bip_set(elem, bip_name, value):
    try:
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            p = elem.get_Parameter(bip)
            if p and not p.IsReadOnly:
                p.Set(value)
                return True
    except:
        pass
    return False

def _try_lookup_set(elem, name, value):
    try:
        p = elem.LookupParameter(name)
        if p and not p.IsReadOnly:
            p.Set(value)
            return True
    except:
        pass
    return False

def get_ifc_export_as(elem):
    return (_try_bip_get(elem, "IFC_EXPORT_ELEMENT_TYPE_AS")
            or _try_bip_get(elem, "IFC_EXPORT_ELEMENT_AS")
            or _try_lookup_get(elem, "IfcExportAs")
            or _try_lookup_get(elem, "Export to IFC As")
            or "")

def get_ifc_predefined_type(elem):
    return (_try_bip_get(elem, "IFC_EXPORT_PREDEFINEDTYPE_TYPE")
            or _try_bip_get(elem, "IFC_EXPORT_PREDEFINEDTYPE")
            or _try_lookup_get(elem, "IfcExportType")
            or _try_lookup_get(elem, "IFC Predefined Type")
            or "")

def set_ifc_export_as(elem, value, use_type=True):
    """Try ALL known IFC Export As parameters. Log which one succeeds."""
    # Try built-in type-level
    if _try_bip_set(elem, "IFC_EXPORT_ELEMENT_TYPE_AS", value):
        return True
    # Try built-in instance-level
    if _try_bip_set(elem, "IFC_EXPORT_ELEMENT_AS", value):
        return True
    # Try various display/shared names
    for name in ["Export to IFC As", "Export Type to IFC As",
                 "IfcExportAs", "IFCExportAs"]:
        if _try_lookup_set(elem, name, value):
            return True
    return False

def set_ifc_predefined_type(elem, value, use_type=True):
    """Try ALL known IFC Predefined Type parameters."""
    # Try built-in type-level
    if _try_bip_set(elem, "IFC_EXPORT_PREDEFINEDTYPE_TYPE", value):
        return True
    # Try built-in instance-level
    if _try_bip_set(elem, "IFC_EXPORT_PREDEFINEDTYPE", value):
        return True
    # Try various display/shared names
    for name in ["IFC Predefined Type", "Type IFC Predefined Type",
                 "IfcExportType", "IFCExportType"]:
        if _try_lookup_set(elem, name, value):
            return True
    return False

def set_ifc_object_type(elem, value, use_type=True):
    for name in ["IfcObjectType", "IFCObjectType", "ObjectType"]:
        if _try_lookup_set(elem, name, value):
            return True
    return False


# ==============================================================================
# Data Classes
# ==============================================================================

class TypeRow(object):
    """DataGrid row item."""
    def __init__(self, family, type_name, count, cur_entity, cur_subtype,
                 status, type_elem, items):
        self.Family = family
        self.TypeName = type_name
        self.Count = count
        self.CurEntity = cur_entity
        self.CurSubtype = cur_subtype
        self.Status = status
        self._type_elem = type_elem
        self._items = items


# ==============================================================================
# Collect & Group Elements
# ==============================================================================

def collect_elements_for_bics(bic_list):
    elems = []
    for bic in bic_list:
        try:
            found = FilteredElementCollector(doc).OfCategory(bic) \
                .WhereElementIsNotElementType().ToElements()
            for e in found:
                elems.append(e)
        except:
            pass
    return elems


def build_type_rows(elems):
    """Group elements by Family/Type -> list of TypeRow objects."""
    type_groups = {}
    for e in elems:
        type_id = e.GetTypeId()
        type_elem = doc.GetElement(type_id) if type_id != ElementId.InvalidElementId else None
        fam_name = "N/A"
        type_name = "N/A"
        if type_elem:
            try:
                fam_name = type_elem.get_Parameter(
                    BuiltInParameter.ALL_MODEL_FAMILY_NAME).AsString() or "N/A"
            except:
                pass
            try:
                type_name = type_elem.get_Parameter(
                    BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString() or "N/A"
            except:
                pass

        cur_entity = ""
        cur_subtype = ""
        if type_elem:
            cur_entity = get_ifc_export_as(type_elem)
            cur_subtype = get_ifc_predefined_type(type_elem)
        if not cur_entity:
            cur_entity = get_ifc_export_as(e)
        if not cur_subtype:
            cur_subtype = get_ifc_predefined_type(e)

        key = (fam_name, type_name)
        if key not in type_groups:
            type_groups[key] = {
                "family": fam_name, "type": type_name,
                "count": 0, "cur_entity": cur_entity,
                "cur_subtype": cur_subtype,
                "type_elem": type_elem, "items": [],
            }
        type_groups[key]["count"] += 1
        type_groups[key]["items"].append({"elem": e, "type_elem": type_elem})

    rows = []
    for key in sorted(type_groups.keys()):
        g = type_groups[key]
        if g["cur_entity"] and g["cur_subtype"]:
            status = "OK"
        elif g["cur_entity"]:
            status = "No Sub"
        else:
            status = "Not Set"
        rows.append(TypeRow(
            family=g["family"],
            type_name=g["type"],
            count=g["count"],
            cur_entity=g["cur_entity"] or "(default)",
            cur_subtype=g["cur_subtype"] or "(none)",
            status=status,
            type_elem=g["type_elem"],
            items=g["items"],
        ))
    return rows


# ==============================================================================
# XAML - Uses %%PLACEHOLDER%% to avoid {Binding} conflicts
# DataGrid columns created in code to handle {Binding} safely
# ==============================================================================

XAML_STR = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="IFC-SG Subtype Definer v1.1 | pyDQT"
        Width="1150" Height="740"
        WindowStartupLocation="CenterScreen"
        Background="%%BACKGROUND%%">
    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="52"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="26"/>
        </Grid.RowDefinitions>

        <!-- HEADER -->
        <Border Grid.Row="0" Background="%%PRIMARY%%">
            <Grid Margin="16,0">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel VerticalAlignment="Center">
                    <TextBlock Text="IFC-SG Subtype Definer" FontSize="17"
                               FontWeight="Bold" Foreground="%%TEXT_PRIMARY%%"/>
                    <TextBlock x:Name="txtHeader"
                               Text="Load Industry Mapping Excel to start"
                               FontSize="10.5" Foreground="%%TEXT_DARK%%" Opacity="0.8"/>
                </StackPanel>
                <StackPanel Grid.Column="1" Orientation="Horizontal"
                            VerticalAlignment="Center">
                    <Button x:Name="btnAutoAssign" Content="Auto-Assign"
                            Padding="12,6" Margin="0,0,8,0"
                            Background="%%BUTTON_PRI_BG%%" Foreground="%%BUTTON_PRI_FG%%"
                            FontWeight="Bold" BorderThickness="0" Cursor="Hand"/>
                    <Button x:Name="btnLoadExcel"
                            Content="Load Mapping Excel" Padding="12,6"
                            Background="%%BUTTON_SEC_BG%%" Foreground="%%BUTTON_SEC_FG%%"
                            FontWeight="SemiBold" BorderBrush="%%BORDER%%" BorderThickness="1"
                            Cursor="Hand"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- MAIN -->
        <Grid Grid.Row="1" Margin="10,6,10,6">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="265"/>
                <ColumnDefinition Width="8"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- LEFT PANEL -->
            <Border Grid.Column="0" BorderBrush="%%BORDER%%" BorderThickness="1"
                    Background="%%CARD_BG%%">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="34"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <Border Background="%%PRIMARY%%">
                        <TextBlock Text="IFC-SG Components" Foreground="%%TEXT_PRIMARY%%"
                                   FontWeight="SemiBold" FontSize="12" Margin="10,0"
                                   VerticalAlignment="Center"/>
                    </Border>
                    <TextBox x:Name="txtFilter" Grid.Row="1" Margin="6,4"
                             Height="24" FontSize="11" Padding="4,0"
                             VerticalContentAlignment="Center"
                             BorderBrush="%%BORDER%%" BorderThickness="1"/>
                    <ListBox x:Name="lstComponents" Grid.Row="2"
                             BorderThickness="0" Background="Transparent"/>
                    <TextBlock x:Name="txtSummary" Grid.Row="3" FontSize="9.5"
                               Foreground="%%TEXT_SECONDARY%%" Margin="8,4"
                               TextWrapping="Wrap"/>
                </Grid>
            </Border>

            <!-- RIGHT PANEL -->
            <Grid Grid.Column="2">
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>

                <!-- Info + Assign bar -->
                <Border Grid.Row="0" Background="%%CARD_BG%%" BorderBrush="%%BORDER%%"
                        BorderThickness="1" Padding="10,6" Margin="0,0,0,4">
                    <Grid>
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="*"/>
                                <ColumnDefinition Width="Auto"/>
                            </Grid.ColumnDefinitions>
                            <StackPanel>
                                <TextBlock x:Name="txtCompName" FontSize="14"
                                           FontWeight="Bold" Foreground="%%TEXT_PRIMARY%%"
                                           Text="Select a component from the left panel"/>
                                <TextBlock x:Name="txtCompInfo" FontSize="11"
                                           Foreground="%%TEXT_SECONDARY%%" TextWrapping="Wrap"/>
                            </StackPanel>
                            <TextBlock x:Name="txtAgencies" Grid.Column="1" FontSize="10"
                                       Foreground="%%TEXT_SECONDARY%%" TextAlignment="Right"
                                       VerticalAlignment="Top"/>
                        </Grid>
                        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,6,0,0">
                            <TextBlock Text="Assign Subtype:" FontSize="12"
                                       VerticalAlignment="Center" Margin="0,0,6,0"
                                       FontWeight="SemiBold" Foreground="%%TEXT_PRIMARY%%"/>
                            <ComboBox x:Name="cmbSubtype" Width="280" FontSize="12"
                                      VerticalAlignment="Center"/>
                            <Button x:Name="btnApply" Content="Apply to Selected"
                                    Margin="8,0,0,0" Padding="12,5"
                                    Background="%%BUTTON_PRI_BG%%" Foreground="%%BUTTON_PRI_FG%%"
                                    FontWeight="Bold" BorderThickness="0" Cursor="Hand"/>
                            <Button x:Name="btnApplyAll" Content="Apply to ALL"
                                    Margin="6,0,0,0" Padding="12,5"
                                    Background="%%BUTTON_PRI_BG%%" Foreground="%%BUTTON_PRI_FG%%"
                                    FontWeight="Bold" BorderThickness="0" Cursor="Hand"/>
                        </StackPanel>
                    </Grid>
                </Border>

                <!-- DataGrid -->
                <Border Grid.Row="1" BorderBrush="%%BORDER%%" BorderThickness="1"
                        Background="%%CARD_BG%%">
                    <DataGrid x:Name="dgTypes" AutoGenerateColumns="False"
                              IsReadOnly="True" SelectionMode="Extended"
                              CanUserSortColumns="True"
                              GridLinesVisibility="Horizontal"
                              HorizontalGridLinesBrush="#E8E8E8"
                              BorderThickness="0" RowHeaderWidth="0"
                              AlternatingRowBackground="%%ROW_ALT%%"
                              HeadersVisibility="Column"/>
                </Border>

                <!-- Bottom controls -->
                <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,5,0,0">
                    <CheckBox x:Name="chkApplyType" Content="Apply to Type"
                              IsChecked="True" FontSize="11" Margin="0,0,14,0"
                              Foreground="%%TEXT_PRIMARY%%"/>
                    <CheckBox x:Name="chkApplyEntity" Content="Also set IFC Entity"
                              IsChecked="True" FontSize="11" Margin="0,0,14,0"
                              Foreground="%%TEXT_PRIMARY%%"/>
                    <CheckBox x:Name="chkSetObjectType"
                              Content="Set ObjectType for USERDEFINED"
                              IsChecked="True" FontSize="11"
                              Foreground="%%TEXT_PRIMARY%%"/>
                    <TextBlock Text="  |  Ctrl+Click to multi-select in grid"
                               FontSize="10" Foreground="%%TEXT_SECONDARY%%"
                               VerticalAlignment="Center"/>
                </StackPanel>
            </Grid>
        </Grid>

        <!-- FOOTER -->
        <Border Grid.Row="2" Background="%%FOOTER_BG%%">
            <TextBlock Text="Copyright (c) 2026 by Dang Quoc Truong (DQT)"
                       Foreground="%%TEXT_DARK%%" FontSize="10"
                       HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
    </Grid>
</Window>
"""

# Apply color replacements
XAML = XAML_STR \
    .replace("%%BACKGROUND%%", Config.BACKGROUND) \
    .replace("%%PRIMARY%%", Config.PRIMARY) \
    .replace("%%TEXT_PRIMARY%%", Config.TEXT_PRIMARY) \
    .replace("%%TEXT_DARK%%", Config.TEXT_DARK) \
    .replace("%%TEXT_SECONDARY%%", Config.TEXT_SECONDARY) \
    .replace("%%BORDER%%", Config.BORDER) \
    .replace("%%CARD_BG%%", Config.CARD_BG) \
    .replace("%%ROW_ALT%%", Config.ROW_ALT) \
    .replace("%%FOOTER_BG%%", Config.FOOTER_BG) \
    .replace("%%BUTTON_PRI_BG%%", Config.BUTTON_PRIMARY_BG) \
    .replace("%%BUTTON_PRI_FG%%", Config.BUTTON_PRIMARY_FG) \
    .replace("%%BUTTON_SEC_BG%%", Config.BUTTON_SECONDARY_BG) \
    .replace("%%BUTTON_SEC_FG%%", Config.BUTTON_SECONDARY_FG)


# ==============================================================================
# Main Window
# ==============================================================================

class IFCSGSubtypeWindow(object):

    def __init__(self):
        stream = MemoryStream(Encoding.UTF8.GetBytes(XAML))
        self.window = XamlReader.Load(stream)
        stream.Close()

        # Controls
        self.txtHeader = self.window.FindName("txtHeader")
        self.txtFilter = self.window.FindName("txtFilter")
        self.lstComponents = self.window.FindName("lstComponents")
        self.txtSummary = self.window.FindName("txtSummary")
        self.txtCompName = self.window.FindName("txtCompName")
        self.txtCompInfo = self.window.FindName("txtCompInfo")
        self.txtAgencies = self.window.FindName("txtAgencies")
        self.cmbSubtype = self.window.FindName("cmbSubtype")
        self.dgTypes = self.window.FindName("dgTypes")
        self.chkApplyType = self.window.FindName("chkApplyType")
        self.chkApplyEntity = self.window.FindName("chkApplyEntity")
        self.chkSetObjectType = self.window.FindName("chkSetObjectType")

        # Setup DataGrid columns in code (avoids {Binding} in XAML string)
        self._setup_columns()

        # Style DataGrid column headers
        self._style_column_headers()

        # Events - _on_load_excel guards itself (it needs to restore txtHeader
        # on failure); every other handler is wrapped here so a bug in one
        # click can no longer bring the whole tool down mid-session the way
        # it did before.
        self.lstComponents.SelectionChanged += self._guard(self._on_comp_selected)
        self.window.FindName("btnLoadExcel").Click += self._on_load_excel
        self.window.FindName("btnAutoAssign").Click += self._guard(self._on_auto_assign)
        self.window.FindName("btnApply").Click += self._guard(self._on_apply_selected)
        self.window.FindName("btnApplyAll").Click += self._guard(self._on_apply_all)
        self.txtFilter.TextChanged += self._guard(self._on_filter_changed)

        # State
        self.mapping = {}
        self.current_comp = ""
        self.current_rows = []
        self._comp_names = []
        self._all_entries = []
        self._all_comp_names_list = []

    def _guard(self, handler):
        """Wrap a WPF event handler so it cannot crash the whole tool.

        Any exception raised inside a Click/SelectionChanged/TextChanged
        callback used to propagate straight out through WPF's dispatcher and
        take the entire window down - the pyRevit output panel would show a
        wall of CLR interpreter frames with no indication of what actually
        went wrong. This reports the real error instead and lets the window
        keep working."""
        def wrapped(sender, args):
            try:
                handler(sender, args)
            except Exception as ex:
                import traceback
                output.print_md("## Error")
                output.print_md("```\n{}\n```".format(traceback.format_exc()))
                try:
                    WPFMessageBox.Show(
                        "Something went wrong:\n{}\n\nSee the pyRevit output "
                        "window for the full error.".format(str(ex)),
                        "Error", MessageBoxButton.OK, MessageBoxImage.Error)
                except:
                    pass
        return wrapped

    def _setup_columns(self):
        """Create DataGrid columns programmatically."""
        from System.Windows.Controls import DataGridLength
        cols = [
            ("Family", "Family", 190),
            ("Type", "TypeName", 180),
            ("Qty", "Count", 45),
            ("Current IFC Entity", "CurEntity", 160),
            ("Current Subtype", "CurSubtype", 140),
            ("Status", "Status", 65),
        ]
        for header, binding_path, width in cols:
            col = DataGridTextColumn()
            col.Header = header
            col.Binding = Binding(binding_path)
            col.Width = DataGridLength(width)
            self.dgTypes.Columns.Add(col)

    def _populate_datagrid(self, rows):
        """Populate DataGrid using DataTable for reliable WPF binding."""
        for _asm in ("System.Data", "System.Data.Common"):
            try:
                clr.AddReference(_asm)
            except Exception:
                pass
        from System.Data import DataTable

        dt = DataTable()
        dt.Columns.Add("Family")
        dt.Columns.Add("TypeName")
        dt.Columns.Add("Count", System.Type.GetType("System.Int32"))
        dt.Columns.Add("CurEntity")
        dt.Columns.Add("CurSubtype")
        dt.Columns.Add("Status")

        for r in rows:
            row = dt.NewRow()
            row["Family"] = r.Family
            row["TypeName"] = r.TypeName
            row["Count"] = r.Count
            row["CurEntity"] = r.CurEntity
            row["CurSubtype"] = r.CurSubtype
            row["Status"] = r.Status
            dt.Rows.Add(row)

        self.dgTypes.ItemsSource = dt.DefaultView

    def _style_column_headers(self):
        """Style DataGrid column headers to match Contains Manager."""
        try:
            from System.Windows import Style as WPFStyle, Setter
            from System.Windows.Controls.Primitives import DataGridColumnHeader
            from System.Windows.Controls import Control
            style = WPFStyle(DataGridColumnHeader)
            style.Setters.Add(Setter(Control.BackgroundProperty,
                                     bc.ConvertFromString(Config.PRIMARY)))
            style.Setters.Add(Setter(Control.ForegroundProperty,
                                     bc.ConvertFromString(Config.TEXT_PRIMARY)))
            style.Setters.Add(Setter(Control.FontWeightProperty,
                                     System.Windows.FontWeights.SemiBold))
            style.Setters.Add(Setter(Control.PaddingProperty,
                                     Thickness(10, 8, 10, 8)))
            style.Setters.Add(Setter(Control.BorderBrushProperty,
                                     bc.ConvertFromString(Config.BORDER)))
            style.Setters.Add(Setter(Control.BorderThicknessProperty,
                                     Thickness(0, 0, 1, 1)))
            self.dgTypes.ColumnHeaderStyle = style
        except:
            pass

    def _on_load_excel(self, sender, args):
        dlg = OpenFileDialog()
        dlg.Title = "Select IFC-SG Industry Mapping Excel"
        dlg.Filter = "Excel Files|*.xlsx;*.xls"
        if dlg.ShowDialog() != WFDialogResult.OK:
            return

        self.txtHeader.Text = "Reading Excel headers..."
        self.window.UpdateLayout()

        # Nothing between here and the header text being restored below was
        # guarded before - any exception in the column-mapping dialog or the
        # parse crashed the whole tool with the status stuck on "Reading
        # Excel headers..." and no way to recover except restarting it.
        try:
            mapping = load_mapping_with_dialog(dlg.FileName)
        except Exception as ex:
            import traceback
            output.print_md("## Load Mapping Excel error")
            output.print_md("```\n{}\n```".format(traceback.format_exc()))
            WPFMessageBox.Show(
                "Could not load that Excel file:\n{}\n\nSee the pyRevit output "
                "window for the full error.".format(str(ex)),
                "Load Error", MessageBoxButton.OK, MessageBoxImage.Error)
            self.txtHeader.Text = "Load Industry Mapping Excel to start"
            return

        if not mapping:
            self.txtHeader.Text = "Load Industry Mapping Excel to start"
            return

        self.mapping = mapping
        import System.IO
        fname = System.IO.Path.GetFileName(dlg.FileName)
        self.txtHeader.Text = "Loaded: {} ({} components)".format(fname, len(mapping))
        self._populate_component_list()

    def _populate_component_list(self):
        """Build ListBox items programmatically with styled StackPanels."""
        from System.Windows.Controls import (
            ListBoxItem, StackPanel as WPFStackPanel,
            TextBlock as WPFTextBlock, Border as WPFBorder,
            Orientation
        )
        from System.Windows import Thickness as WPFThickness, HorizontalAlignment

        self._comp_names = []
        total_elems = 0
        entries = []  # (comp_name, count, entity_str, sub_count)
        unmapped_cats = set()

        for comp_name in sorted(self.mapping.keys()):
            m = self.mapping[comp_name]
            bics = []
            for rc in m["revit_categories"]:
                found = resolve_revit_categories(rc)
                if found:
                    bics.extend(found)
                else:
                    unmapped_cats.add(rc)
            elems = collect_elements_for_bics(bics) if bics else []
            count = len(elems)
            total_elems += count
            m["_bics"] = bics
            m["_elements"] = elems

            entity_str = ", ".join(m["ifc_entities"][:2])
            if len(m["ifc_entities"]) > 2:
                entity_str += "..."
            sub_count = len(m["subtypes"])

            entries.append((comp_name, count, entity_str, sub_count))

        self.lstComponents.Items.Clear()
        self._comp_names = []
        self._all_entries = entries
        self._all_comp_names_list = [e[0] for e in entries]

        for comp_name, count, entity_str, sub_count in entries:
            item = self._make_comp_listitem(comp_name, count, entity_str, sub_count)
            self.lstComponents.Items.Add(item)
            self._comp_names.append(comp_name)

        summary = "{} components | {} elements in model".format(
            len(self.mapping), total_elems)
        if unmapped_cats:
            summary += "  |  {} Revit category name(s) not recognised (see output)".format(
                len(unmapped_cats))
            output.print_md("**Revit categories from the Excel that this tool "
                            "does not recognise:** " + ", ".join(sorted(unmapped_cats)))
        self.txtSummary.Text = summary

    def _make_comp_listitem(self, comp_name, count, entity_str, sub_count):
        """Create a styled ListBoxItem for a component."""
        from System.Windows.Controls import (
            StackPanel as WPFStackPanel, TextBlock as WPFTextBlock,
            Border as WPFBorder, Orientation, DockPanel
        )
        from System.Windows import (
            Thickness as WPFThickness, HorizontalAlignment,
            VerticalAlignment as WPFVAlign, FontWeights
        )

        # Outer panel
        sp = WPFStackPanel()
        sp.Margin = WPFThickness(2, 3, 2, 3)

        # Row 1: Name + Count badge
        row1 = DockPanel()

        # Count badge (right-aligned)
        badge = WPFBorder()
        badge.Background = bc.ConvertFromString("#E8DCC8")
        badge.CornerRadius = System.Windows.CornerRadius(8)
        badge.Padding = WPFThickness(6, 1, 6, 1)
        badge.Margin = WPFThickness(4, 0, 0, 0)
        DockPanel.SetDock(badge, System.Windows.Controls.Dock.Right)
        badge_text = WPFTextBlock()
        badge_text.Text = str(count)
        badge_text.FontSize = 9.5
        badge_text.Foreground = bc.ConvertFromString(Config.TEXT_DARK)
        badge_text.HorizontalAlignment = HorizontalAlignment.Center
        badge.Child = badge_text
        row1.Children.Add(badge)

        # Component name (left, fills remaining)
        name_tb = WPFTextBlock()
        name_tb.Text = comp_name
        name_tb.FontSize = 12
        name_tb.FontWeight = FontWeights.SemiBold
        name_tb.Foreground = bc.ConvertFromString(Config.TEXT_PRIMARY)
        name_tb.TextTrimming = System.Windows.TextTrimming.CharacterEllipsis
        row1.Children.Add(name_tb)

        sp.Children.Add(row1)

        # Row 2: Entity + Subtypes (smaller, gray)
        info_parts = []
        if entity_str:
            info_parts.append(entity_str)
        if sub_count:
            info_parts.append("{} subtypes".format(sub_count))
        if info_parts:
            info_tb = WPFTextBlock()
            info_tb.Text = "  ".join(info_parts)
            info_tb.FontSize = 10
            info_tb.Foreground = bc.ConvertFromString(Config.TEXT_SECONDARY)
            info_tb.Margin = WPFThickness(0, 1, 0, 0)
            info_tb.TextTrimming = System.Windows.TextTrimming.CharacterEllipsis
            sp.Children.Add(info_tb)

        return sp

    def _on_filter_changed(self, sender, args):
        txt = self.txtFilter.Text.strip().lower()
        self.lstComponents.Items.Clear()
        self._comp_names = []

        for comp_name, count, entity_str, sub_count in self._all_entries:
            search_str = "{} {} {}".format(comp_name, entity_str, sub_count).lower()
            if txt and txt not in search_str:
                continue
            item = self._make_comp_listitem(comp_name, count, entity_str, sub_count)
            self.lstComponents.Items.Add(item)
            self._comp_names.append(comp_name)

    def _on_comp_selected(self, sender, args):
        idx = self.lstComponents.SelectedIndex
        if idx < 0 or idx >= len(self._comp_names):
            return

        comp_name = self._comp_names[idx]
        self.current_comp = comp_name
        m = self.mapping.get(comp_name, {})

        entities = ", ".join(m.get("ifc_entities", []))
        revit_cats = ", ".join(m.get("revit_categories", []))
        self.txtCompName.Text = comp_name
        self.txtCompInfo.Text = "IFC: {}  |  Revit: {}".format(entities, revit_cats)
        self.txtAgencies.Text = "Agencies: {}".format(", ".join(m.get("agencies", [])))

        # Subtypes combo
        self.cmbSubtype.Items.Clear()
        subtypes = m.get("subtypes", [])
        userdefined = sorted(s for s in subtypes if s.startswith("*"))
        standard = sorted(s for s in subtypes if not s.startswith("*"))
        for st in userdefined:
            self.cmbSubtype.Items.Add("[SG] " + st)
        for st in standard:
            self.cmbSubtype.Items.Add(st)
        if self.cmbSubtype.Items.Count > 0:
            self.cmbSubtype.SelectedIndex = 0

        # Build type rows (returns TypeRow objects, not dicts)
        elems = m.get("_elements", [])
        rows = build_type_rows(elems)
        self.current_rows = rows
        self._populate_datagrid(rows)

    def _get_subtype_info(self):
        sel = self.cmbSubtype.SelectedItem
        if not sel:
            return "", False
        sel_str = str(sel)
        if sel_str.startswith("[SG] "):
            sel_str = sel_str[5:]
        is_ud = sel_str.startswith("*")
        return sel_str, is_ud

    def _on_apply_selected(self, sender, args):
        # DataGrid uses DataTable - SelectedItems are DataRowView
        # Map selected indices back to TypeRow objects
        sel_indices = set()
        for item in self.dgTypes.SelectedItems:
            try:
                idx = self.dgTypes.Items.IndexOf(item)
                sel_indices.add(idx)
            except:
                pass
        if not sel_indices:
            WPFMessageBox.Show("Select types in the grid (Ctrl+Click for multi).",
                               "No Selection", MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        selected_rows = [self.current_rows[i] for i in sel_indices
                         if i < len(self.current_rows)]
        if not selected_rows:
            return
        self._apply_to_rows(selected_rows)

    def _on_apply_all(self, sender, args):
        if not self.current_rows:
            return
        subtype_str, _ = self._get_subtype_info()
        result = WPFMessageBox.Show(
            "Apply '{}' to ALL {} types in '{}'?".format(
                subtype_str, len(self.current_rows), self.current_comp),
            "Confirm", MessageBoxButton.YesNo, MessageBoxImage.Question)
        if result == MessageBoxResult.Yes:
            self._apply_to_rows(self.current_rows)

    def _apply_to_rows(self, rows):
        subtype_str, is_ud = self._get_subtype_info()
        if not subtype_str:
            WPFMessageBox.Show("Select a subtype first.", "No Subtype",
                               MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        use_type = self.chkApplyType.IsChecked == True
        also_entity = self.chkApplyEntity.IsChecked == True
        set_obj = self.chkSetObjectType.IsChecked == True

        m = self.mapping.get(self.current_comp, {})
        primary_entity = m["ifc_entities"][0] if m.get("ifc_entities") else ""

        if is_ud:
            pdt_value = "USERDEFINED"
            obj_value = subtype_str.lstrip("*")
        else:
            pdt_value = subtype_str
            obj_value = ""

        ok = 0
        fail = 0
        debug_lines = []

        t = Transaction(doc, "DQT - Set IFC-SG Subtypes")
        t.Start()
        try:
            for row in rows:
                # Try type element first, then instance elements
                targets_tried = []

                if use_type and row._type_elem:
                    te = row._type_elem
                    targets_tried.append(("Type", te))

                # Always also try first instance element
                if row._items:
                    inst = row._items[0]["elem"]
                    targets_tried.append(("Instance", inst))

                type_ok = False
                for target_label, target in targets_tried:
                    entity_ok = True
                    pdt_ok = True
                    obj_ok = True

                    if also_entity and primary_entity:
                        entity_ok = set_ifc_export_as(target, primary_entity, use_type)

                    pdt_ok = set_ifc_predefined_type(target, pdt_value, use_type)

                    if is_ud and set_obj and obj_value:
                        obj_ok = set_ifc_object_type(target, obj_value, use_type)

                    if entity_ok and pdt_ok and obj_ok:
                        type_ok = True
                        debug_lines.append("[OK] {} '{}' -> {} on {} (id:{})".format(
                            target_label, row.Family + ":" + row.TypeName,
                            pdt_value, target_label, target.Id.IntegerValue))
                        break  # Success on this target, skip next
                    else:
                        debug_lines.append("[FAIL] {} '{}' entity={} pdt={} obj={} on {} (id:{})".format(
                            target_label, row.Family + ":" + row.TypeName,
                            entity_ok, pdt_ok, obj_ok, target_label, target.Id.IntegerValue))

                if type_ok:
                    ok += 1
                else:
                    fail += 1

            t.Commit()
        except Exception as ex:
            t.RollBack()
            WPFMessageBox.Show("Error: " + str(ex), "Failed",
                               MessageBoxButton.OK, MessageBoxImage.Error)
            return

        self._refresh()

        # Show results with debug info
        msg = "Applied '{}' -> PredefinedType='{}'\n".format(subtype_str, pdt_value)
        if is_ud and obj_value:
            msg += "ObjectType = '{}'\n".format(obj_value)
        msg += "\nSuccess: {}  |  Failed: {}\n".format(ok, fail)

        # Print debug to pyrevit output
        if debug_lines:
            output.print_md("### IFC-SG Subtype Apply Log")
            for line in debug_lines:
                output.print_md("- " + line)

        if fail > 0:
            msg += "\nCheck pyRevit output for detailed log."

        WPFMessageBox.Show(msg, "Done", MessageBoxButton.OK, MessageBoxImage.Information)

    def _on_auto_assign(self, sender, args):
        """Auto-assign IFC entity + first subtype to all elements missing subtypes."""
        if not self.mapping:
            WPFMessageBox.Show("Load a mapping Excel first.",
                               "No Mapping", MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        # Build preview: for each component, find elements without subtype
        preview_lines = []
        auto_plan = []  # (comp_name, type_rows, entity, subtype_str, is_ud)

        for comp_name in sorted(self.mapping.keys()):
            m = self.mapping[comp_name]
            elems = m.get("_elements", [])
            if not elems:
                continue

            entity = m["ifc_entities"][0] if m.get("ifc_entities") else ""
            if not entity:
                continue

            # Pick first subtype (prefer USERDEFINED/SG, then standard)
            subtypes = m.get("subtypes", [])
            if not subtypes:
                # No subtype defined - just set entity
                subtype_str = ""
                is_ud = False
            else:
                ud = sorted(s for s in subtypes if s.startswith("*"))
                std = sorted(s for s in subtypes if not s.startswith("*"))
                subtype_str = (ud + std)[0] if (ud + std) else ""
                is_ud = subtype_str.startswith("*")

            # Find types without subtype set
            rows = build_type_rows(elems)
            unset = [r for r in rows if r.Status != "OK"]
            if not unset:
                continue

            total_instances = sum(r.Count for r in unset)
            pdt = "USERDEFINED" if is_ud else subtype_str
            obj = subtype_str.lstrip("*") if is_ud else ""

            line = "{}: {} types ({} instances) -> {} / {}".format(
                comp_name, len(unset), total_instances, entity, pdt)
            if obj:
                line += " [ObjectType={}]".format(obj)
            preview_lines.append(line)
            auto_plan.append((comp_name, unset, entity, subtype_str, is_ud))

        if not auto_plan:
            WPFMessageBox.Show(
                "All elements already have IFC Entity + Subtype assigned!",
                "Nothing to Auto-Assign", MessageBoxButton.OK,
                MessageBoxImage.Information)
            return

        # Show preview dialog
        preview_text = "Auto-Assign will update {} components:\n\n".format(len(auto_plan))
        preview_text += "\n".join(preview_lines)
        preview_text += "\n\nOnly elements with Status != 'OK' will be updated."
        preview_text += "\nExisting assignments will NOT be overwritten."
        preview_text += "\n\nProceed?"

        result = WPFMessageBox.Show(preview_text, "Auto-Assign Preview",
                                    MessageBoxButton.YesNo, MessageBoxImage.Question)
        if result != MessageBoxResult.Yes:
            return

        # Execute
        use_type = self.chkApplyType.IsChecked == True
        set_obj = self.chkSetObjectType.IsChecked == True
        total_ok = 0
        total_fail = 0

        t = Transaction(doc, "DQT - Auto-Assign IFC-SG Subtypes")
        t.Start()
        try:
            for comp_name, rows, entity, subtype_str, is_ud in auto_plan:
                if is_ud:
                    pdt_value = "USERDEFINED"
                    obj_value = subtype_str.lstrip("*")
                else:
                    pdt_value = subtype_str
                    obj_value = ""

                for row in rows:
                    if use_type and row._type_elem:
                        targets = [row._type_elem]
                    else:
                        targets = [it["elem"] for it in row._items]

                    for target in targets:
                        s = True
                        if entity:
                            if not set_ifc_export_as(target, entity, use_type):
                                s = False
                        if pdt_value:
                            if not set_ifc_predefined_type(target, pdt_value, use_type):
                                s = False
                        if is_ud and set_obj and obj_value:
                            set_ifc_object_type(target, obj_value, use_type)
                        if s:
                            total_ok += 1
                        else:
                            total_fail += 1

            t.Commit()
        except Exception as ex:
            t.RollBack()
            WPFMessageBox.Show("Error: " + str(ex), "Failed",
                               MessageBoxButton.OK, MessageBoxImage.Error)
            return

        # Refresh all
        self._populate_component_list()

        msg = "Auto-Assign complete!\n{} types updated successfully.".format(total_ok)
        if total_fail:
            msg += "\n{} failed (read-only or missing parameter).".format(total_fail)
        WPFMessageBox.Show(msg, "Auto-Assign Done",
                           MessageBoxButton.OK, MessageBoxImage.Information)

    def _refresh(self):
        if not self.current_comp:
            return
        m = self.mapping.get(self.current_comp, {})
        m["_elements"] = collect_elements_for_bics(m.get("_bics", []))
        rows = build_type_rows(m["_elements"])
        self.current_rows = rows
        self._populate_datagrid(rows)

    def show(self):
        self.window.ShowDialog()


# ==============================================================================
# Entry Point
# ==============================================================================

try:
    win = IFCSGSubtypeWindow()
    win.show()
except Exception as ex:
    import traceback
    output.print_md("## Error")
    output.print_md("```\n{}\n```".format(traceback.format_exc()))