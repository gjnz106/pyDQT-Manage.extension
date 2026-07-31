# -*- coding: utf-8 -*-
"""Dimension Manager v1.0
Author: Dang Quoc Truong (DQT)

Lists every Dimension Type with how many instances are placed, so an
unused type (a purge candidate) or a heavily-used one is visible at a
glance. Selecting a type and clicking Detail shows exactly which view
each of its instances lives in - every Dimension is view-specific, so
that lookup is always instant, unlike Model Groups.
"""
__title__ = "Dimension\nManager"
__author__ = "DQT"

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from pyrevit import revit, forms, script, HOST_APP, DB
from pyrevit.forms import WPFWindow
from pyrevit.compat import get_elementid_value_func
from Autodesk.Revit.DB import *
from System.Collections.Generic import List
import codecs
import datetime

get_elementid_value = get_elementid_value_func()


def _eid_int(eid):
    """Get integer value from ElementId - compatible with Revit 2024-2026"""
    if eid is None:
        return -1
    return get_elementid_value(eid)


# ============================================================================
# DATA MODEL
# ============================================================================
class DimensionTypeSummary(object):
    def __init__(self):
        self.type_id = 0
        self.name = "<Unnamed>"
        self.style = "-"            # "Linear" / "Angular" / ... best-effort
        self.text_size = "-"
        self.text_font = "-"
        self.width_factor = "-"
        self.instance_count = 0
        self.created_by = "-"
        self.workset = "-"
        self.instance_ids = []      # ElementId of every placed instance


class DimensionInstanceDetail(object):
    def __init__(self):
        self.instance_id = 0
        self.view_name = "-"
        self.workset = "-"
        self.element_id = None      # ElementId, kept for navigation


def _dim_type_name(dt):
    """DimensionType names are ordinary user-given names - plain .Name
    usually works, Element.Name.GetValue is the version-safe fallback this
    suite already relies on for other element types."""
    try:
        if dt.Name:
            return dt.Name
    except:
        pass
    try:
        name = DB.Element.Name.GetValue(dt)
        if name:
            return name
    except:
        pass
    return "<Unnamed> (ID {})".format(_eid_int(dt.Id))


def _dim_type_style(dt):
    """Best-effort "Linear" / "Angular" / "Radial" / ... label.

    DimensionType.StyleType is the documented property for this, but is
    read defensively (never lets a style lookup fail the whole row) in
    case a given Revit build behaves differently - unlike List Dimension,
    nothing here depends on getting this right, it is purely informational."""
    try:
        return str(dt.StyleType)
    except:
        pass
    return "-"


def _resolve_bip(name):
    """A BuiltInParameter by member name, or None if this Revit build
    doesn't have it - degrades to the by-name LookupParameter fallback in
    _param_by_bip_or_name() instead of throwing on every type."""
    try:
        return getattr(BuiltInParameter, name)
    except AttributeError:
        return None


# Resolved once: the same "Text" appearance parameters this suite's
# FamilyFont tool already relies on (TEXT_FONT, TEXT_WIDTH_SCALE), plus
# TEXT_SIZE which List Text Styles already reads directly off
# TextNoteType - Dimension Types expose the same shared "Text" group.
_BIP_TEXT_SIZE = _resolve_bip("TEXT_SIZE")
_BIP_TEXT_FONT = _resolve_bip("TEXT_FONT")
_BIP_WIDTH_FACTOR = _resolve_bip("TEXT_WIDTH_SCALE")


def _param_by_bip_or_name(elem, bip, display_name):
    """A parameter found first by BuiltInParameter, falling back to a
    by-name lookup for whichever a given Revit build exposes it as -
    mirrors the same defensive resolution this suite's FamilyFont tool
    already relies on for these exact Text-appearance parameters."""
    if bip is not None:
        try:
            p = elem.get_Parameter(bip)
            if p is not None:
                return p
        except:
            pass
    try:
        return elem.LookupParameter(display_name)
    except:
        return None


def _dim_text_size(dt):
    """Text Size, unit-formatted (e.g. "2.5 mm") - "-" if this type has no
    usable Text Size parameter."""
    p = _param_by_bip_or_name(dt, _BIP_TEXT_SIZE, "Text Size")
    if p is None:
        return "-"
    try:
        val = p.AsValueString()
        if val:
            return val
    except:
        pass
    return "-"


def _dim_text_font(dt):
    """Text Font name - "-" if this type has no usable Text Font parameter."""
    p = _param_by_bip_or_name(dt, _BIP_TEXT_FONT, "Text Font")
    if p is None:
        return "-"
    try:
        val = p.AsString()
        if val:
            return val
    except:
        pass
    return "-"


def _dim_width_factor(dt):
    """Width Factor - "-" if this type has no usable Width Factor
    parameter (not every dimension style has one)."""
    p = _param_by_bip_or_name(dt, _BIP_WIDTH_FACTOR, "Width Factor")
    if p is None:
        return "-"
    try:
        val = p.AsValueString()
        if val:
            return val
    except:
        pass
    try:
        return str(round(p.AsDouble(), 3))
    except:
        pass
    return "-"


def _get_created_by(doc, elem):
    """Who created this element, from worksharing tooltip info.

    WorksharingUtils only answers on a workshared model - callers are
    expected to have already checked doc.IsWorkshared."""
    try:
        info = WorksharingUtils.GetWorksharingTooltipInfo(doc, elem.Id)
        if info and info.Creator:
            return info.Creator
    except:
        pass
    return "-"


def _get_workset(doc, elem):
    if not doc.IsWorkshared:
        return "-"
    try:
        ws = doc.GetWorksetTable().GetWorkset(elem.WorksetId)
        if ws:
            return ws.Name
    except:
        pass
    return "-"


def get_dimension_types(doc):
    """One row per DimensionType, with how many placed instances reference
    it. Types with zero instances are listed too - an unused dimension
    type sitting in the model is exactly what this tool is for finding.

    Counting is a single pass matching each Dimension instance to its type
    via GetTypeId() - the same pattern this suite's GroupManager and
    FamilyManager tools already use - rather than re-scanning all
    instances once per type."""
    counts = {}
    instances_of = {}
    for inst in FilteredElementCollector(doc).OfClass(Dimension):
        try:
            tid = _eid_int(inst.GetTypeId())
        except:
            continue
        counts[tid] = counts.get(tid, 0) + 1
        instances_of.setdefault(tid, []).append(inst.Id)

    items = []
    for dt in FilteredElementCollector(doc).OfClass(DimensionType):
        try:
            item = DimensionTypeSummary()
            item.type_id = _eid_int(dt.Id)
            item.name = _dim_type_name(dt)
            item.style = _dim_type_style(dt)
            item.text_size = _dim_text_size(dt)
            item.text_font = _dim_text_font(dt)
            item.width_factor = _dim_width_factor(dt)
            item.instance_count = counts.get(item.type_id, 0)
            item.instance_ids = instances_of.get(item.type_id, [])
            item.created_by = _get_created_by(doc, dt)
            item.workset = _get_workset(doc, dt)
            items.append(item)
        except:
            continue
    return items


def get_dimension_instance_details(doc, type_summary):
    """Per-instance rows for one DimensionType: which view each instance
    lives in. Every Dimension is view-specific, so OwnerViewId always
    answers this directly - unlike Model Groups, no scanning is ever
    needed here."""
    rows = []
    for eid in type_summary.instance_ids:
        inst = doc.GetElement(eid)
        if inst is None:
            continue
        row = DimensionInstanceDetail()
        row.instance_id = _eid_int(eid)
        row.element_id = eid
        row.workset = _get_workset(doc, inst)
        try:
            owner_id = inst.OwnerViewId
            view = doc.GetElement(owner_id) if owner_id is not None else None
            name = getattr(view, "Name", None) if view else None
            row.view_name = name if name else "-"
        except:
            row.view_name = "-"
        rows.append(row)
    return rows


def _rename_type(doc, dt, new_name):
    """Rename a DimensionType, the version-safe way this suite already
    relies on for other element types (Element.Name.SetValue first, plain
    .Name as the fallback for whichever a given Revit build refuses)."""
    try:
        DB.Element.Name.SetValue(dt, new_name)
        return True
    except Exception:
        pass
    try:
        dt.Name = new_name
        return True
    except Exception as ex:
        forms.alert("Could not rename: {}".format(ex), title="DQT - Dimension Manager")
        return False


def _navigate_to(uidoc, doc, ids):
    """Select these elements and, for a single element, switch straight to
    its owning view instead of asking Revit to search for one - every
    Dimension is view-specific, so this always succeeds for one element."""
    try:
        uidoc.Selection.SetElementIds(ids)
    except Exception as ex:
        forms.alert(str(ex), title="DQT - Dimension Manager")
        return

    if len(ids) == 1:
        el = doc.GetElement(ids[0])
        owner_id = None
        try:
            owner_id = el.OwnerViewId if el else None
        except:
            owner_id = None
        if owner_id is not None and _eid_int(owner_id) > 0:
            owner_view = doc.GetElement(owner_id)
            if owner_view is not None:
                try:
                    uidoc.ActiveView = owner_view
                    uidoc.Selection.SetElementIds(ids)
                    uidoc.RefreshActiveView()
                    return
                except:
                    pass

    try:
        uidoc.ShowElements(ids)
    except Exception as ex:
        forms.alert("Selected, but Revit could not find a view to zoom "
                    "to: {}".format(ex), title="DQT - Dimension Manager")


# ============================================================================
# XAML - DETAIL DIALOG
# ============================================================================
DETAIL_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Dimension Detail - DQT"
        Height="500" Width="600"
        WindowStartupLocation="CenterScreen"
        Background="#FEF8E7">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#F0CC88" CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
            <StackPanel>
                <TextBlock x:Name="txtTitle" Text="Dimension Detail" FontSize="16" FontWeight="Bold"/>
                <TextBlock Text="Double-click ID to copy it. Double-click elsewhere on a row to select + zoom to that instance." FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0" TextWrapping="Wrap"/>
            </StackPanel>
        </Border>

        <DataGrid Grid.Row="1" x:Name="dataGrid"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  SelectionMode="Extended" SelectionUnit="FullRow"
                  CanUserSortColumns="True"
                  Background="White" BorderBrush="#D4B87A"
                  GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#EEE"
                  RowBackground="White" AlternatingRowBackground="#FFFDF5">
            <DataGrid.Columns>
                <DataGridTextColumn x:Name="colId" Header="Instance ID" Binding="{Binding instance_id}" Width="100" SortMemberPath="instance_id"/>
                <DataGridTextColumn Header="View" Binding="{Binding view_name}" Width="*" SortMemberPath="view_name"/>
                <DataGridTextColumn Header="Workset" Binding="{Binding workset}" Width="140" SortMemberPath="workset"/>
            </DataGrid.Columns>
        </DataGrid>

        <Border Grid.Row="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8" Margin="0,10,0,0">
            <Grid>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
                    <Button x:Name="btnSelectAll" Content="Select All" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnClear" Content="Clear" Padding="10,5" Margin="2" Background="White"/>
                </StackPanel>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="btnSelectInModel" Content="Select in Model" Padding="10,5" Margin="2" Background="#F0CC88"/>
                    <Button x:Name="btnZoom" Content="Zoom To" Padding="10,5" Margin="2" Background="#F0CC88"/>
                    <Button x:Name="btnClose" Content="Close" Padding="10,5" Margin="2" Background="White"/>
                </StackPanel>
            </Grid>
        </Border>

        <Border Grid.Row="3" Background="#F0CC88" CornerRadius="3" Padding="8,5" Margin="0,8,0,0">
            <TextBlock Text="Dang Quoc Truong - DQT (c) 2026" FontSize="10" FontWeight="SemiBold" HorizontalAlignment="Center" Foreground="#5D4E37"/>
        </Border>
    </Grid>
</Window>
"""


class DimensionDetailWindow(WPFWindow):
    def __init__(self, doc, uidoc, type_name, rows):
        WPFWindow.__init__(self, DETAIL_XAML, literal_string=True)
        self.doc = doc
        self.uidoc = uidoc
        self.rows = rows

        self.txtTitle.Text = "Dimension Detail - {}".format(type_name)
        for row in rows:
            self.dataGrid.Items.Add(row)

        self.dataGrid.MouseDoubleClick += self.on_double_click
        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnSelectInModel.Click += self.select_in_model
        self.btnZoom.Click += self.zoom_to
        self.btnClose.Click += self.close_window

    def _cell_under(self, source):
        try:
            from System.Windows.Media import VisualTreeHelper
            from System.Windows.Controls import DataGridCell
        except:
            return None
        node = source
        while node is not None and not isinstance(node, DataGridCell):
            try:
                node = VisualTreeHelper.GetParent(node)
            except:
                return None
        return node

    def _copy_id(self, row):
        text = str(row.instance_id)
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(text)
        except Exception:
            try:
                from System.Windows.Forms import Clipboard as WFClipboard
                WFClipboard.SetText(text)
            except Exception as ex:
                forms.alert("Could not copy ID to clipboard: {}".format(ex),
                            title="DQT - Dimension Manager")

    def on_double_click(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            return
        row = self.dataGrid.SelectedItem
        cell = self._cell_under(e.OriginalSource)
        if cell is not None and cell.Column is self.colId:
            self._copy_id(row)
            return
        ids = List[ElementId]()
        ids.Add(row.element_id)
        _navigate_to(self.uidoc, self.doc, ids)

    def select_all(self, s, e):
        self.dataGrid.SelectAll()

    def select_none(self, s, e):
        self.dataGrid.UnselectAll()

    def select_in_model(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one instance first.", title="DQT - Dimension Manager")
            return
        ids = List[ElementId]()
        for row in self.dataGrid.SelectedItems:
            ids.Add(row.element_id)
        try:
            self.uidoc.Selection.SetElementIds(ids)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Dimension Manager")

    def zoom_to(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one instance first.", title="DQT - Dimension Manager")
            return
        ids = List[ElementId]()
        for row in self.dataGrid.SelectedItems:
            ids.Add(row.element_id)
        _navigate_to(self.uidoc, self.doc, ids)

    def close_window(self, s, e):
        self.Close()


# ============================================================================
# XAML - MAIN WINDOW
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Dimension Manager - DQT"
        Height="620" Width="1280"
        WindowStartupLocation="CenterScreen"
        Background="#FEF8E7">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Header -->
        <Border Grid.Row="0" Background="#F0CC88" CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
            <StackPanel>
                <TextBlock Text="Dimension Manager" FontSize="17" FontWeight="Bold"/>
                <TextBlock Text="Dimension types in this model - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
            </StackPanel>
        </Border>

        <!-- Summary cards -->
        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
                <StackPanel><TextBlock Text="TOTAL TYPES" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtTotal" Text="0" FontSize="22" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="UNUSED (0)" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtUnused" Text="0" FontSize="22" FontWeight="Bold" Foreground="#FF6B6B"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
                <StackPanel><TextBlock Text="SELECTED" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtSelected" Text="0" FontSize="22" FontWeight="Bold" Foreground="#5D4E37"/></StackPanel>
            </Border>
        </Grid>

        <!-- Content -->
        <Grid Grid.Row="2">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="170"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- Left Panel -->
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8" Margin="0,0,8,0">
                <StackPanel>
                    <TextBlock Text="SEARCH" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <TextBox x:Name="txtSearch" Padding="6,4" Margin="0,0,0,10" ToolTip="Name, style, font, creator or workset"/>
                    <TextBlock Text="Select a type and click Detail to see which view each instance is used in." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
                </StackPanel>
            </Border>

            <!-- DataGrid -->
            <DataGrid Grid.Column="1" x:Name="dataGrid"
                      AutoGenerateColumns="False" IsReadOnly="True"
                      SelectionMode="Extended" SelectionUnit="FullRow"
                      CanUserSortColumns="True"
                      Background="White" BorderBrush="#D4B87A"
                      GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#EEE"
                      RowBackground="White" AlternatingRowBackground="#FFFDF5">
                <DataGrid.Columns>
                    <DataGridTextColumn x:Name="colId" Header="ID" Binding="{Binding type_id}" Width="70" SortMemberPath="type_id"/>
                    <DataGridTextColumn Header="Name" Binding="{Binding name}" Width="*" SortMemberPath="name"/>
                    <DataGridTextColumn Header="Style" Binding="{Binding style}" Width="90" SortMemberPath="style"/>
                    <DataGridTextColumn Header="Text Size" Binding="{Binding text_size}" Width="80" SortMemberPath="text_size"/>
                    <DataGridTextColumn Header="Text Font" Binding="{Binding text_font}" Width="130" SortMemberPath="text_font"/>
                    <DataGridTextColumn Header="Width Factor" Binding="{Binding width_factor}" Width="90" SortMemberPath="width_factor"/>
                    <DataGridTextColumn Header="Instances" Binding="{Binding instance_count}" Width="80" SortMemberPath="instance_count"/>
                    <DataGridTextColumn Header="Created By" Binding="{Binding created_by}" Width="120" SortMemberPath="created_by"/>
                    <DataGridTextColumn Header="Workset" Binding="{Binding workset}" Width="120" SortMemberPath="workset"/>
                </DataGrid.Columns>
            </DataGrid>
        </Grid>

        <!-- Action Buttons -->
        <Border Grid.Row="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8" Margin="0,10,0,0">
            <Grid>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
                    <Button x:Name="btnSelectAll" Content="Select All" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnClear" Content="Clear" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnRefresh" Content="Refresh" Padding="10,5" Margin="2" Background="White"/>
                </StackPanel>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="btnSelectInModel" Content="Select in Model" Padding="10,5" Margin="2" Background="#F0CC88"/>
                    <Button x:Name="btnZoom" Content="Zoom To" Padding="10,5" Margin="2" Background="#F0CC88"/>
                    <Button x:Name="btnDetail" Content="Detail" Padding="10,5" Margin="2" Background="#F0CC88" FontWeight="SemiBold"/>
                    <Button x:Name="btnRename" Content="Rename" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnExportCSV" Content="Export CSV" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnClose" Content="Close" Padding="10,5" Margin="2" Background="White"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- Footer -->
        <Border Grid.Row="4" Background="#F0CC88" CornerRadius="3" Padding="8,5" Margin="0,8,0,0">
            <TextBlock Text="Dang Quoc Truong - DQT (c) 2026" FontSize="10" FontWeight="SemiBold" HorizontalAlignment="Center" Foreground="#5D4E37"/>
        </Border>
    </Grid>
</Window>
"""


# ============================================================================
# MAIN WINDOW
# ============================================================================
class DimensionManagerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.items = []
        self.filtered = []

        self.txtSearch.TextChanged += self.on_filter
        self.dataGrid.SelectionChanged += self.on_selection
        self.dataGrid.MouseDoubleClick += self.on_double_click

        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnRefresh.Click += self.refresh
        self.btnSelectInModel.Click += self.select_in_model
        self.btnZoom.Click += self.zoom_to
        self.btnDetail.Click += self.show_detail
        self.btnRename.Click += self.rename_selected
        self.btnExportCSV.Click += self.export_csv
        self.btnClose.Click += self.close_window

        self.load_data()
        self.update_ui()

    def load_data(self):
        self.items = get_dimension_types(self.doc)
        self.filtered = list(self.items)

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtUnused.Text = str(len([i for i in self.items if i.instance_count == 0]))
        self.txtSelected.Text = "0"
        self.update_grid()

    def update_grid(self):
        self.dataGrid.Items.Clear()
        for item in self.filtered:
            self.dataGrid.Items.Add(item)

    def on_filter(self, s, e):
        search = self.txtSearch.Text.lower().strip() if self.txtSearch.Text else ""
        self.filtered = []
        for item in self.items:
            if search and search not in "{} {} {} {} {}".format(
                    item.name, item.style, item.text_font, item.created_by,
                    item.workset).lower():
                continue
            self.filtered.append(item)
        self.update_grid()

    def on_selection(self, s, e):
        self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)

    def _cell_under(self, source):
        try:
            from System.Windows.Media import VisualTreeHelper
            from System.Windows.Controls import DataGridCell
        except:
            return None
        node = source
        while node is not None and not isinstance(node, DataGridCell):
            try:
                node = VisualTreeHelper.GetParent(node)
            except:
                return None
        return node

    def _copy_id(self, item):
        text = str(item.type_id)
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(text)
        except Exception:
            try:
                from System.Windows.Forms import Clipboard as WFClipboard
                WFClipboard.SetText(text)
            except Exception as ex:
                forms.alert("Could not copy ID to clipboard: {}".format(ex),
                            title="DQT - Dimension Manager")

    def _selected_instance_ids(self):
        ids = List[ElementId]()
        for item in self.dataGrid.SelectedItems:
            for eid in item.instance_ids:
                ids.Add(eid)
        return ids

    def on_double_click(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            return
        item = self.dataGrid.SelectedItem
        cell = self._cell_under(e.OriginalSource)
        if cell is not None and cell.Column is self.colId:
            self._copy_id(item)
            return
        ids = self._selected_instance_ids()
        if len(ids) == 0:
            forms.alert("'{}' has no placed instances to zoom to.".format(item.name),
                        title="DQT - Dimension Manager")
            return
        _navigate_to(self.uidoc, self.doc, ids)

    def select_all(self, s, e):
        self.dataGrid.SelectAll()

    def select_none(self, s, e):
        self.dataGrid.UnselectAll()

    def refresh(self, s, e):
        self.load_data()
        self.on_filter(None, None)
        self.txtTotal.Text = str(len(self.items))
        self.txtUnused.Text = str(len([i for i in self.items if i.instance_count == 0]))

    def select_in_model(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one dimension type first.", title="DQT - Dimension Manager")
            return
        ids = self._selected_instance_ids()
        if len(ids) == 0:
            forms.alert("The selected type(s) have no placed instances.",
                        title="DQT - Dimension Manager")
            return
        try:
            self.uidoc.Selection.SetElementIds(ids)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Dimension Manager")

    def zoom_to(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one dimension type first.", title="DQT - Dimension Manager")
            return
        ids = self._selected_instance_ids()
        if len(ids) == 0:
            forms.alert("The selected type(s) have no placed instances.",
                        title="DQT - Dimension Manager")
            return
        _navigate_to(self.uidoc, self.doc, ids)

    def show_detail(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            forms.alert("Select exactly one dimension type to see its detail.",
                        title="DQT - Dimension Manager")
            return
        item = self.dataGrid.SelectedItem
        if item.instance_count == 0:
            forms.alert("'{}' has no placed instances in this model.".format(item.name),
                        title="DQT - Dimension Manager")
            return
        rows = get_dimension_instance_details(self.doc, item)
        dlg = DimensionDetailWindow(self.doc, self.uidoc, item.name, rows)
        dlg.ShowDialog()

    def rename_selected(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            forms.alert("Select exactly one dimension type to rename.",
                        title="DQT - Dimension Manager")
            return
        item = self.dataGrid.SelectedItem
        new_name = forms.ask_for_string(
            default=item.name, prompt="New name:",
            title="DQT - Rename Dimension Type")
        if not new_name or new_name == item.name:
            return

        dt = self.doc.GetElement(ElementId(item.type_id))
        if dt is None:
            forms.alert("This dimension type no longer exists - refresh and try again.",
                        title="DQT - Dimension Manager")
            return

        try:
            with revit.Transaction("DQT - Rename Dimension Type"):
                ok = _rename_type(self.doc, dt, new_name)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Dimension Manager")
            return

        if ok:
            self.refresh(s, e)

    def export_csv(self, s, e):
        current_items = [item for item in self.dataGrid.Items]
        if not current_items:
            forms.alert("No data to export.", title="DQT - Dimension Manager")
            return

        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "CSV Files|*.csv"
        dlg.FileName = "DimensionTypes_{}.csv".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

        if dlg.ShowDialog() == DialogResult.OK:
            try:
                with codecs.open(dlg.FileName, 'w', 'utf-8-sig') as f:
                    f.write("ID,Name,Style,Text Size,Text Font,Width Factor,"
                            "Instances,Created By,Workset\n")
                    for item in current_items:
                        f.write('{},"{}",{},{},"{}",{},{},{},{}\n'.format(
                            item.type_id, item.name.replace('"', '""'),
                            item.style, item.text_size,
                            item.text_font.replace('"', '""'),
                            item.width_factor, item.instance_count,
                            item.created_by, item.workset))
                forms.alert("Exported {} row(s).".format(len(current_items)),
                            title="DQT - Dimension Manager")
            except Exception as ex:
                forms.alert(str(ex), title="DQT - Dimension Manager")

    def close_window(self, s, e):
        self.Close()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first.", title="DQT - Dimension Manager")
        else:
            DimensionManagerWindow().ShowDialog()
    except Exception as ex:
        forms.alert("Error: {}".format(str(ex)), title="DQT - Dimension Manager Error")
