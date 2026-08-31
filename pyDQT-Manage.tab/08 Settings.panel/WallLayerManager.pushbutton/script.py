# -*- coding: utf-8 -*-
"""
Wall Layer Manager v1.0 - DQT

Lists every layer of every Basic wall type in one table, and changes the
Function of the layers you tick - across many types at once.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "Wall Layer\nManager"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("List the layers of every Basic wall type and batch-change their "
           "Function, e.g. Structure [1] -> Substrate [2].")

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('PresentationFramework')

import System
from System.Collections.ObjectModel import ObservableCollection

from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    Transaction, TransactionGroup, WallType, MaterialFunctionAssignment
)

import codecs
import datetime
import os
import sys

# Shared batch rename dialog (extension lib/). Imported softly: it powers one
# button, so a broken install should not stop the whole manager from opening -
# the button reports it instead. Matches the pattern Dimension Manager
# already uses for the same shared dialog.
_script_dir = os.path.dirname(__file__)
_extension_dir = os.path.dirname(os.path.dirname(os.path.dirname(_script_dir)))
_lib_path = os.path.join(_extension_dir, 'lib')
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)
try:
    from batch_rename_dialog import BatchRenameDialog
except ImportError:
    BatchRenameDialog = None

doc = revit.doc
uidoc = revit.uidoc


# ============================================================================
# LAYER FUNCTIONS
#
# The bracketed numbers are Revit's own priority labels, shown in Edit
# Assembly. Membrane and Structural Deck carry no number there, so they are
# listed without one rather than being given a made-up value.
# ============================================================================
FUNCTION_ORDER = [
    ("Structure", "Structure [1]"),
    ("Substrate", "Substrate [2]"),
    ("Insulation", "Thermal/Air Layer [3]"),
    ("Finish1", "Finish 1 [4]"),
    ("Finish2", "Finish 2 [5]"),
    ("Membrane", "Membrane Layer"),
    ("StructuralDeck", "Structural Deck"),
]


def _function_enum(name):
    """The MaterialFunctionAssignment member, or None when this Revit build
    does not have it - StructuralDeck is not present everywhere."""
    return getattr(MaterialFunctionAssignment, name, None)


def available_functions():
    """(enum_name, display) for every function this Revit build supports."""
    return [(name, label) for name, label in FUNCTION_ORDER
            if _function_enum(name) is not None]


def function_display(function_value):
    """Revit's label for a layer function value."""
    raw = str(function_value)
    for name, label in FUNCTION_ORDER:
        if raw == name:
            return label
    return raw


# ============================================================================
# DATA MODEL
# ============================================================================
class LayerRow(object):
    """One layer of one wall type.

    Bound straight into the DataGrid, so every displayed value is a plain
    attribute. `mark` is text rather than a checkbox column: an editable
    DataGridCheckBoxColumn crashes IronPython, so the tick is drawn and
    toggled by double-click instead."""

    def __init__(self):
        self.selected = False
        self.mark = u"☐"
        self.type_id = 0
        self.type_name = ""
        self.layer_index = 0
        self.position = ""          # 1-based, as Edit Assembly numbers them
        self.function = ""          # enum name, e.g. "Structure"
        self.function_display = ""
        self.material = ""
        self.thickness = ""
        self.core = ""
        self.structural = ""
        self.width_internal = 0.0

    def toggle(self):
        self.selected = not self.selected
        self.mark = u"☑" if self.selected else u"☐"


class WallTypeRenameItem(object):
    """One Wall Type, wrapped for the shared Batch Rename dialog (lib/
    batch_rename_dialog.py) - it looks for .name and .Element on whatever
    item list it's given."""

    def __init__(self, wall_type):
        self.Element = wall_type
        self.name = _type_name(wall_type)


# ============================================================================
# READING
# ============================================================================
def _length_display(value_internal):
    """Internal feet as a millimetre string, matching Edit Assembly."""
    try:
        from Autodesk.Revit.DB import UnitUtils
        try:
            from Autodesk.Revit.DB import UnitTypeId
            mm = UnitUtils.ConvertFromInternalUnits(value_internal,
                                                    UnitTypeId.Millimeters)
        except Exception:
            from Autodesk.Revit.DB import DisplayUnitType
            mm = UnitUtils.ConvertFromInternalUnits(
                value_internal, DisplayUnitType.DUT_MILLIMETERS)
    except Exception:
        mm = value_internal * 304.8
    return str(round(mm, 1))


def _type_name(wall_type):
    try:
        name = wall_type.get_Parameter(
            BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
        if name:
            return name
    except Exception:
        pass
    try:
        return wall_type.Name
    except Exception:
        return "<unnamed>"


def _eid_int(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def basic_wall_types(document):
    """Only Basic walls - Curtain and Stacked walls have no editable
    compound structure."""
    types = []
    collector = (FilteredElementCollector(document)
                 .OfCategory(BuiltInCategory.OST_Walls)
                 .OfClass(WallType)
                 .WhereElementIsElementType())
    for wall_type in collector:
        try:
            if str(wall_type.Kind) != "Basic":
                continue
        except Exception:
            continue
        types.append(wall_type)
    return types


def read_layers(document):
    """Every layer of every Basic wall type, as LayerRow objects."""
    rows = []
    for wall_type in basic_wall_types(document):
        try:
            structure = wall_type.GetCompoundStructure()
        except Exception:
            structure = None
        if structure is None:
            continue

        try:
            layers = list(structure.GetLayers())
        except Exception:
            continue

        first_core, last_core = _core_range(structure)
        structural_index = _structural_index(structure)
        name = _type_name(wall_type)

        for index, layer in enumerate(layers):
            row = LayerRow()
            row.type_id = _eid_int(wall_type.Id)
            row.type_name = name
            row.layer_index = index
            row.position = str(index + 1)

            try:
                row.function = str(layer.Function)
            except Exception:
                row.function = ""
            row.function_display = function_display(row.function)

            try:
                material = document.GetElement(layer.MaterialId)
                row.material = material.Name if material else "<By Category>"
            except Exception:
                row.material = "<By Category>"

            try:
                row.width_internal = layer.Width
            except Exception:
                row.width_internal = 0.0
            row.thickness = _length_display(row.width_internal)

            in_core = (first_core is not None
                       and first_core <= index <= last_core)
            row.core = u"✔" if in_core else ""
            row.structural = u"✔" if index == structural_index else ""

            rows.append(row)
    return rows


def _core_range(structure):
    """(first, last) layer index of the core, or (None, None).

    Read through GetFirstCoreLayerIndex/GetLastCoreLayerIndex where present,
    otherwise derived from the shell layer counts."""
    try:
        return (structure.GetFirstCoreLayerIndex(),
                structure.GetLastCoreLayerIndex())
    except Exception:
        pass
    try:
        exterior = structure.GetNumberOfShellLayers(DB.ShellLayerType.Exterior)
        interior = structure.GetNumberOfShellLayers(DB.ShellLayerType.Interior)
        total = len(list(structure.GetLayers()))
        return exterior, total - interior - 1
    except Exception:
        return None, None


def _structural_index(structure):
    try:
        return structure.StructuralMaterialIndex
    except Exception:
        return -1


# ============================================================================
# APPLYING
#
# Revit's own validator decides whether a change is allowed. Rather than
# encoding rules about what a core may contain - which have moved between
# releases - the new structure is handed to CompoundStructure.IsValid() and
# the failure it reports is passed straight through to the user.
# ============================================================================
def validate_structure(structure, document):
    """(ok, message). IsValid takes two out-parameters, which IronPython
    returns as a tuple; older builds expose a one-argument form, so both
    shapes are tried before falling back to 'let SetCompoundStructure
    decide'."""
    try:
        result = structure.IsValid(document)
    except TypeError:
        try:
            return bool(structure.IsValid()), ""
        except Exception:
            return True, ""
    except Exception:
        return True, ""

    if isinstance(result, bool):
        return result, "" if result else "Revit rejected the layer structure"

    try:
        ok = bool(result[0])
        error_map = result[1] if len(result) > 1 else None
    except Exception:
        return True, ""

    if ok:
        return True, ""

    reasons = _error_reasons(error_map)
    return False, "; ".join(reasons) or "Revit rejected the layer structure"


def _error_reasons(error_map):
    """Revit's {layerIndex: CompoundStructureError} as readable text.

    IronPython hands back a .NET IDictionary, which exposes .Keys and yields
    KeyValuePair objects when iterated directly - so neither plain iteration
    nor .Keys alone covers every shape this can arrive in."""
    if error_map is None:
        return []

    try:
        keys = list(error_map.Keys)
    except AttributeError:
        try:
            keys = list(error_map.keys())
        except Exception:
            return []
    except Exception:
        return []

    reasons = []
    for key in keys:
        try:
            reasons.append("layer {}: {}".format(key + 1, error_map[key]))
        except Exception:
            pass
    return reasons


def apply_function_change(document, rows, new_function_name):
    """Set the chosen function on every ticked layer, one wall type at a time.

    Returns (changed_layers, changed_types, failures) where failures is a list
    of (type_name, reason). A type Revit refuses is left exactly as it was and
    the rest of the batch continues."""
    function_value = _function_enum(new_function_name)
    if function_value is None:
        return 0, 0, [("-", "this Revit build has no {} function".format(
            new_function_name))]

    by_type = {}
    for row in rows:
        by_type.setdefault(row.type_id, []).append(row)

    changed_layers = 0
    changed_types = 0
    failures = []

    group = TransactionGroup(document, "DQT - Wall Layer Function")
    group.Start()
    try:
        for type_id, type_rows in by_type.items():
            name = type_rows[0].type_name
            wall_type = document.GetElement(DB.ElementId(type_id))
            if wall_type is None:
                failures.append((name, "wall type no longer exists"))
                continue

            transaction = Transaction(document, "DQT - Wall Layer Function")
            transaction.Start()
            try:
                structure = wall_type.GetCompoundStructure()
                if structure is None:
                    raise Exception("no compound structure")

                touched = 0
                for row in type_rows:
                    if row.function == new_function_name:
                        continue
                    structure.SetLayerFunction(row.layer_index, function_value)
                    touched += 1

                if touched == 0:
                    transaction.RollBack()
                    continue

                ok, reason = validate_structure(structure, document)
                if not ok:
                    transaction.RollBack()
                    failures.append((name, reason))
                    continue

                wall_type.SetCompoundStructure(structure)
                transaction.Commit()
                changed_layers += touched
                changed_types += 1
            except Exception as error:
                try:
                    transaction.RollBack()
                except Exception:
                    pass
                failures.append((name, str(error)))
        group.Assimilate()
    except Exception as error:
        try:
            group.RollBack()
        except Exception:
            pass
        return 0, 0, [("-", str(error))]

    return changed_layers, changed_types, failures


# ============================================================================
# XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Wall Layer Manager v1.0 - DQT"
        Width="1180" Height="760"
        WindowStartupLocation="CenterScreen" Background="#FFFFFF">
  <Grid>
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#F0CC88" BorderBrush="#D4B87A"
            BorderThickness="0,0,0,2" Padding="16,10">
      <Grid>
        <StackPanel>
          <TextBlock Text="Wall Layer Manager v1.0" FontSize="17"
                     FontWeight="Bold" Foreground="#5D4E37"/>
          <TextBlock Text="by Dang Quoc Truong (DQT)" FontSize="10"
                     Foreground="#666"/>
        </StackPanel>
        <Button Name="btnHelp" Content="? Help" Padding="10,4" Background="White"
                BorderBrush="#D4B87A" HorizontalAlignment="Right"/>
      </Grid>
    </Border>

    <Grid Grid.Row="1" Margin="12,10,12,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A"
              BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
        <StackPanel>
          <TextBlock Text="WALL TYPES" FontSize="9" Foreground="#888"/>
          <TextBlock Name="txtTypes" Text="0" FontSize="20" FontWeight="Bold"
                     Foreground="#5D4E37"/>
        </StackPanel>
      </Border>
      <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A"
              BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,4,0">
        <StackPanel>
          <TextBlock Text="LAYERS" FontSize="9" Foreground="#888"/>
          <TextBlock Name="txtLayers" Text="0" FontSize="20" FontWeight="Bold"
                     Foreground="#5D4E37"/>
        </StackPanel>
      </Border>
      <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A"
              BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,4,0">
        <StackPanel>
          <TextBlock Text="VISIBLE" FontSize="9" Foreground="#888"/>
          <TextBlock Name="txtVisible" Text="0" FontSize="20" FontWeight="Bold"
                     Foreground="#5DADE2"/>
        </StackPanel>
      </Border>
      <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A"
              BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
        <StackPanel>
          <TextBlock Text="TICKED" FontSize="9" Foreground="#888"/>
          <TextBlock Name="txtTicked" Text="0" FontSize="20" FontWeight="Bold"
                     Foreground="#E5B85C"/>
        </StackPanel>
      </Border>
    </Grid>

    <Border Grid.Row="2" Background="White" BorderBrush="#D4B87A"
            BorderThickness="1" CornerRadius="4" Padding="8" Margin="12,10,12,0">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Search type" VerticalAlignment="Center"
                   Foreground="#333" Margin="0,0,6,0"/>
        <TextBox Name="txtSearch" Width="180" Height="26"
                 VerticalContentAlignment="Center" BorderBrush="#D4B87A"/>
        <TextBlock Text="Function" VerticalAlignment="Center"
                   Foreground="#333" Margin="14,0,6,0"/>
        <ComboBox Name="cmbFilterFunction" Width="150" Height="26"
                  VerticalContentAlignment="Center"/>
        <CheckBox Name="chkCoreOnly" Content="Core layers only"
                  VerticalAlignment="Center" Margin="14,0,0,0"/>
        <Button Name="btnSelectVisible" Content="Tick all visible" Padding="10,4"
                Margin="18,0,0,0" Background="White" BorderBrush="#D4B87A"/>
        <Button Name="btnClear" Content="Clear ticks" Padding="10,4"
                Margin="6,0,0,0" Background="White" BorderBrush="#D4B87A"/>
      </StackPanel>
    </Border>

    <DataGrid Grid.Row="3" Name="dataGrid" Margin="12,10,12,0"
              AutoGenerateColumns="False" IsReadOnly="True"
              HeadersVisibility="Column" GridLinesVisibility="All"
              Background="White" RowBackground="White"
              AlternatingRowBackground="#FAF3E0"
              BorderBrush="#D4B87A" BorderThickness="1"
              HorizontalGridLinesBrush="#E0E0E0" VerticalGridLinesBrush="#E0E0E0"
              CanUserSortColumns="True" SelectionMode="Extended">
      <DataGrid.Columns>
        <DataGridTextColumn Header="" Binding="{Binding mark}" Width="34"/>
        <DataGridTextColumn Header="Wall Type" Binding="{Binding type_name}" Width="*"/>
        <DataGridTextColumn Header="#" Binding="{Binding position}" Width="40"/>
        <DataGridTextColumn Header="Function" Binding="{Binding function_display}" Width="150"/>
        <DataGridTextColumn Header="Material" Binding="{Binding material}" Width="220"/>
        <DataGridTextColumn Header="Thickness" Binding="{Binding thickness}" Width="90"/>
        <DataGridTextColumn Header="Core" Binding="{Binding core}" Width="50"/>
        <DataGridTextColumn Header="Struct" Binding="{Binding structural}" Width="55"/>
      </DataGrid.Columns>
    </DataGrid>

    <Border Grid.Row="4" Background="#FAF3E0" BorderBrush="#D4B87A"
            BorderThickness="1" CornerRadius="4" Padding="10,8" Margin="12,10,12,0">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Set the ticked layers to" VerticalAlignment="Center"
                   Foreground="#5D4E37" FontWeight="SemiBold"/>
        <ComboBox Name="cmbNewFunction" Width="170" Height="26" Margin="8,0,0,0"
                  VerticalContentAlignment="Center"/>
        <Button Name="btnApply" Content="Apply" Padding="18,5" Margin="10,0,0,0"
                Background="#F0CC88" BorderBrush="#D4B87A" FontWeight="SemiBold"/>
        <TextBlock Name="txtStatus" Text="Double-click a row to tick it."
                   VerticalAlignment="Center" Margin="16,0,0,0" Foreground="#666"/>
      </StackPanel>
    </Border>

    <Grid Grid.Row="5" Margin="12,10,12,10">
      <TextBlock Text="Dang Quoc Truong - DQT (c) 2026" FontSize="10"
                 Foreground="#5D4E37" VerticalAlignment="Center"/>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
        <Button Name="btnBatchRenameTypes" Content="Batch Rename Types..." Padding="10,5"
                Margin="0,0,6,0" Background="White" BorderBrush="#D4B87A"/>
        <Button Name="btnExport" Content="Export CSV" Padding="10,5"
                Margin="0,0,6,0" Background="White" BorderBrush="#D4B87A"/>
        <Button Name="btnRefresh" Content="Refresh" Padding="10,5"
                Margin="0,0,6,0" Background="White" BorderBrush="#D4B87A"/>
        <Button Name="btnClose" Content="Close" Padding="10,5"
                Background="White" BorderBrush="#D4B87A"/>
      </StackPanel>
    </Grid>
  </Grid>
</Window>
"""


# ============================================================================
# WINDOW
# ============================================================================
class WallLayerManagerWindow(WPFWindow):

    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = doc
        self.all_rows = []
        self.filtered = []

        self.functions = available_functions()

        self.cmbFilterFunction.Items.Clear()
        self.cmbFilterFunction.Items.Add("All functions")
        for _, label in self.functions:
            self.cmbFilterFunction.Items.Add(label)
        self.cmbFilterFunction.SelectedIndex = 0

        self.cmbNewFunction.Items.Clear()
        for _, label in self.functions:
            self.cmbNewFunction.Items.Add(label)
        self.cmbNewFunction.SelectedIndex = 0

        self.txtSearch.TextChanged += self.on_filter
        self.cmbFilterFunction.SelectionChanged += self.on_filter
        self.chkCoreOnly.Checked += self.on_filter
        self.chkCoreOnly.Unchecked += self.on_filter
        self.dataGrid.MouseDoubleClick += self.on_toggle
        self.btnSelectVisible.Click += self.on_select_visible
        self.btnClear.Click += self.on_clear
        self.btnApply.Click += self.on_apply
        self.btnBatchRenameTypes.Click += self.on_batch_rename_types
        self.btnExport.Click += self.on_export
        self.btnRefresh.Click += self.on_refresh
        self.btnClose.Click += lambda s, e: self.Close()
        self.btnHelp.Click += self.on_help

        self.load_data()

    # -- data ---------------------------------------------------------------
    def load_data(self):
        self.all_rows = read_layers(self.doc)
        type_ids = set(row.type_id for row in self.all_rows)
        self.txtTypes.Text = str(len(type_ids))
        self.txtLayers.Text = str(len(self.all_rows))
        self.apply_filters()

    def apply_filters(self):
        search = (self.txtSearch.Text or "").lower()
        core_only = bool(self.chkCoreOnly.IsChecked)

        wanted_function = None
        index = self.cmbFilterFunction.SelectedIndex
        if index > 0 and index - 1 < len(self.functions):
            wanted_function = self.functions[index - 1][0]

        self.filtered = []
        for row in self.all_rows:
            if search and search not in row.type_name.lower():
                continue
            if wanted_function and row.function != wanted_function:
                continue
            if core_only and not row.core:
                continue
            self.filtered.append(row)

        collection = ObservableCollection[object]()
        for row in self.filtered:
            collection.Add(row)
        self.dataGrid.ItemsSource = collection

        self.update_counts()

    def update_counts(self):
        self.txtVisible.Text = str(len(self.filtered))
        self.txtTicked.Text = str(sum(1 for r in self.all_rows if r.selected))

    def ticked_rows(self):
        return [row for row in self.all_rows if row.selected]

    # -- events -------------------------------------------------------------
    def on_filter(self, sender, args):
        try:
            self.apply_filters()
        except Exception:
            pass

    def on_toggle(self, sender, args):
        try:
            row = self.dataGrid.SelectedItem
            if row is not None:
                row.toggle()
                self.dataGrid.Items.Refresh()
                self.update_counts()
        except Exception:
            pass

    def on_select_visible(self, sender, args):
        for row in self.filtered:
            if not row.selected:
                row.toggle()
        self.dataGrid.Items.Refresh()
        self.update_counts()

    def on_clear(self, sender, args):
        for row in self.all_rows:
            if row.selected:
                row.toggle()
        self.dataGrid.Items.Refresh()
        self.update_counts()

    def on_refresh(self, sender, args):
        self.load_data()
        self.txtStatus.Text = "Reloaded."

    def on_batch_rename_types(self, sender, args):
        """Batch-rename the Wall Types behind the ticked layers - grouped
        by type, since a tick lives on a layer row and several rows can
        share the same wall type."""
        if BatchRenameDialog is None:
            forms.alert(
                "The shared batch rename dialog could not be loaded from the "
                "extension's lib folder.",
                title="Wall Layer Manager")
            return

        ticked = self.ticked_rows()
        if not ticked:
            forms.alert("Tick at least one layer first - its wall type is "
                        "what gets renamed.",
                        title="Wall Layer Manager")
            return

        seen = set()
        items = []
        for row in ticked:
            if row.type_id in seen:
                continue
            seen.add(row.type_id)
            wall_type = self.doc.GetElement(DB.ElementId(row.type_id))
            if wall_type is not None:
                items.append(WallTypeRenameItem(wall_type))

        if not items:
            forms.alert("The ticked wall type(s) no longer exist - refresh "
                        "and try again.",
                        title="Wall Layer Manager")
            return

        dialog = BatchRenameDialog(self.doc, items, self)
        dialog.ShowDialog()
        self.load_data()
        self.txtStatus.Text = "Reloaded after batch rename."

    def on_help(self, sender, args):
        forms.alert(
            "Wall Layer Manager\n\n"
            "- Search filters by wall type name; Function narrows to one layer function.\n"
            "- Core layers only shows just the layers inside the core boundary.\n"
            "- Double-click a row (or 'Tick all visible') to tick it, then pick a new "
            "Function and click Apply to batch-change the ticked layers.\n"
            "- Batch Rename Types... renames the wall TYPE(S) behind the ticked "
            "layers (tick any one of a type's layers to include it).\n"
            "- This edits wall TYPES, so every wall using them changes too.\n\n"
            "Dang Quoc Truong - DQT (c) 2026",
            title="Wall Layer Manager")

    def on_apply(self, sender, args):
        rows = self.ticked_rows()
        if not rows:
            forms.alert("Tick the layers you want to change first.\n\n"
                        "Double-click a row, or use 'Tick all visible'.",
                        title="Wall Layer Manager")
            return

        index = self.cmbNewFunction.SelectedIndex
        if index < 0 or index >= len(self.functions):
            return
        new_name, new_label = self.functions[index]

        pending = [row for row in rows if row.function != new_name]
        if not pending:
            forms.alert("Every ticked layer is already {}.".format(new_label),
                        title="Wall Layer Manager")
            return

        type_count = len(set(row.type_id for row in pending))
        sample = "\n".join(
            u"  {} - layer {} ({} -> {})".format(
                row.type_name, row.position, row.function_display, new_label)
            for row in pending[:8])
        if len(pending) > 8:
            sample += u"\n  ... and {} more".format(len(pending) - 8)

        if not forms.alert(
                u"Change {} layer(s) across {} wall type(s) to {}?\n\n{}\n\n"
                u"This edits the wall TYPES, so every wall using them changes "
                u"too.".format(len(pending), type_count, new_label, sample),
                title="Confirm", yes=True, no=True):
            return

        changed_layers, changed_types, failures = apply_function_change(
            self.doc, pending, new_name)

        self.load_data()

        message = ["{} layer(s) changed across {} wall type(s).".format(
            changed_layers, changed_types)]
        if failures:
            message.append("")
            message.append("Revit refused {} type(s):".format(len(failures)))
            for name, reason in failures[:10]:
                message.append(u"  {} - {}".format(name, reason))
            if len(failures) > 10:
                message.append("  ... and {} more".format(len(failures) - 10))
        forms.alert("\n".join(message), title="Wall Layer Manager")

        self.txtStatus.Text = "{} layer(s) changed, {} type(s) refused.".format(
            changed_layers, len(failures))

    def on_export(self, sender, args):
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dialog = SaveFileDialog()
        dialog.Filter = "CSV|*.csv"
        dialog.FileName = "DQT_wall_layers_{}.csv".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        if dialog.ShowDialog() != DialogResult.OK:
            return

        try:
            with codecs.open(dialog.FileName, 'w', 'utf-8') as handle:
                handle.write("Wall Type,Layer,Function,Material,"
                             "Thickness (mm),In Core,Structural\n")
                for row in self.filtered:
                    handle.write(u'"{}",{},"{}","{}",{},{},{}\n'.format(
                        row.type_name.replace('"', '""'),
                        row.position,
                        row.function_display,
                        row.material.replace('"', '""'),
                        row.thickness,
                        "Yes" if row.core else "No",
                        "Yes" if row.structural else "No"))
            forms.alert("Exported {} row(s).".format(len(self.filtered)),
                        title="Wall Layer Manager")
            os.startfile(dialog.FileName)
        except Exception as error:
            forms.alert("Could not export:\n{}".format(error),
                        title="Wall Layer Manager")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    if not doc:
        forms.alert("Please open a project first.", title="Wall Layer Manager")
    else:
        WallLayerManagerWindow().ShowDialog()
