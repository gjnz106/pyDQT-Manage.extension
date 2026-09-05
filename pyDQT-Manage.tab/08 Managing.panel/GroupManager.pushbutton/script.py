# -*- coding: utf-8 -*-
"""Group Manager v1.0
Author: Dang Quoc Truong (DQT)

Lists every Model Group and Detail Group TYPE in the model with how many
instances are actually placed, so an unused group type (a purge candidate)
or an over-used one is visible at a glance instead of hunting through the
Project Browser. Selecting a type and clicking Detail shows exactly which
view each of its instances lives in.
"""
__title__ = "Group\nManager"
__author__ = "DQT"

import os
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


def _open_help_page(html_filename):
    """Open this tool's page from the shared _Managing_Help folder in the
    default browser. Returns True on success, False if the caller should
    fall back to the in-app help text (e.g. the folder went missing)."""
    try:
        panel_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(panel_dir, "_Managing_Help", html_filename)
        if not os.path.isfile(path):
            return False
        os.startfile(path)
        return True
    except Exception:
        return False


def _eid_int(eid):
    """Get integer value from ElementId - compatible with Revit 2024-2026"""
    if eid is None:
        return -1
    return get_elementid_value(eid)


# ============================================================================
# DATA MODEL
# ============================================================================
class GroupTypeSummary(object):
    def __init__(self):
        self.type_id = 0
        self.name = "<Unnamed>"
        self.category = "?"        # "Model" or "Detail"
        self.instance_count = 0
        self.created_by = "-"
        self.workset = "-"
        self.instance_ids = []     # ElementId of every placed instance


class GroupInstanceDetail(object):
    def __init__(self):
        self.instance_id = 0
        self.views = "-"
        self.workset = "-"
        self.element_id = None     # ElementId, kept for navigation


def _group_type_name(gt):
    """GroupType names are ordinary user-given names, so plain .Name
    usually works - Element.Name.GetValue is the version-safe fallback this
    suite already relies on for other element types."""
    try:
        if gt.Name:
            return gt.Name
    except:
        pass
    try:
        name = DB.Element.Name.GetValue(gt)
        if name:
            return name
    except:
        pass
    return "<Unnamed> (ID {})".format(_eid_int(gt.Id))


def _group_category(cat_id):
    """"Model" / "Detail" from a group (type or instance) Category id."""
    try:
        cid = _eid_int(cat_id)
    except:
        return "?"
    if cid == int(BuiltInCategory.OST_IOSModelGroups):
        return "Model"
    if cid == int(BuiltInCategory.OST_IOSDetailGroups):
        return "Detail"
    return "?"


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


def get_group_types(doc):
    """One row per GroupType (Model or Detail), with how many placed
    instances reference it. Types with zero instances are listed too - an
    unused group type sitting in the model is exactly what this tool is
    for finding.

    Counting is done in one pass over every Group instance (matching each
    to its type via GetTypeId(), the same pattern this suite's own
    FamilyManager tool already uses) rather than re-scanning all instances
    once per type."""
    counts = {}
    instances_of = {}
    for inst in FilteredElementCollector(doc).OfClass(Group):
        try:
            tid = _eid_int(inst.GetTypeId())
        except:
            continue
        counts[tid] = counts.get(tid, 0) + 1
        instances_of.setdefault(tid, []).append(inst.Id)

    items = []
    for gt in FilteredElementCollector(doc).OfClass(GroupType):
        try:
            item = GroupTypeSummary()
            item.type_id = _eid_int(gt.Id)
            item.name = _group_type_name(gt)
            item.category = _group_category(gt.Category.Id) if gt.Category else "?"
            item.instance_count = counts.get(item.type_id, 0)
            item.instance_ids = instances_of.get(item.type_id, [])
            item.created_by = _get_created_by(doc, gt)
            item.workset = _get_workset(doc, gt)
            items.append(item)
        except:
            continue
    return items


def _detail_group_owner_view(doc, inst):
    """The single view a Detail Group instance was placed into - Detail
    Groups are view-specific, so OwnerViewId always answers this directly
    without needing to scan anything. Never raises."""
    try:
        owner_id = inst.OwnerViewId
        if owner_id is not None and _eid_int(owner_id) > 0:
            view = doc.GetElement(owner_id)
            name = getattr(view, "Name", None) if view else None
            if name:
                return name
    except:
        pass
    return None


def build_model_group_view_membership(doc, cancel_check=None, progress_cb=None):
    """{group_instance_id_int: [view_name, ...]} for every Group instance
    Revit shows in each view.

    A Model Group instance carries no OwnerView - unlike a Detail Group, it
    can appear in many views at once - so the only way to know which views
    actually show one is to ask each view what it contains. This costs one
    FilteredElementCollector per VIEW (not per instance and not per group
    type), which is what keeps it affordable to run on demand rather than
    a collector per group per view."""
    membership = {}
    views = [v for v in FilteredElementCollector(doc).OfClass(View)
             if not getattr(v, "IsTemplate", False)]
    total = len(views)
    for i, v in enumerate(views):
        if cancel_check and cancel_check():
            break
        if progress_cb:
            progress_cb(i + 1, total)
        try:
            for g in FilteredElementCollector(doc, v.Id).OfClass(Group):
                gid = _eid_int(g.Id)
                membership.setdefault(gid, []).append(v.Name)
        except:
            continue
    return membership


def get_group_instance_details(doc, type_summary, model_group_views=None):
    """Per-instance rows for one GroupType: which view(s) each instance is
    used in.

    Detail Group instances resolve instantly via OwnerViewId. Model Group
    instances need the (expensive, caller-supplied/cached) view-membership
    map - model_group_views is None until the caller has actually built it,
    in which case every Model Group instance is reported as not-yet-scanned
    rather than the tool pretending to have an answer it does not."""
    rows = []
    for eid in type_summary.instance_ids:
        inst = doc.GetElement(eid)
        if inst is None:
            continue
        row = GroupInstanceDetail()
        row.instance_id = _eid_int(eid)
        row.element_id = eid
        row.workset = _get_workset(doc, inst)

        if type_summary.category == "Detail":
            view_name = _detail_group_owner_view(doc, inst)
            row.views = view_name if view_name else "-"
        else:
            if model_group_views is None:
                row.views = "(not scanned)"
            else:
                names = model_group_views.get(row.instance_id)
                row.views = ", ".join(sorted(set(names))) if names else "(no view found)"
        rows.append(row)
    return rows


def _navigate_to(uidoc, doc, ids):
    """Select these elements and, for a single element with a known owning
    view (a Detail Group instance), switch straight to it instead of
    asking Revit to search for one; otherwise fall back to ShowElements."""
    try:
        uidoc.Selection.SetElementIds(ids)
    except Exception as ex:
        forms.alert(str(ex), title="DQT - Group Manager")
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
                    "to: {}".format(ex), title="DQT - Group Manager")


# ============================================================================
# XAML - DETAIL DIALOG
# ============================================================================
DETAIL_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Group Detail - DQT"
        Height="500" Width="650"
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
                <TextBlock x:Name="txtTitle" Text="Group Detail" FontSize="16" FontWeight="Bold"/>
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
                <DataGridTextColumn Header="View(s)" Binding="{Binding views}" Width="*" SortMemberPath="views"/>
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


class GroupDetailWindow(WPFWindow):
    def __init__(self, doc, uidoc, type_name, rows):
        WPFWindow.__init__(self, DETAIL_XAML, literal_string=True)
        self.doc = doc
        self.uidoc = uidoc
        self.rows = rows

        self.txtTitle.Text = "Group Detail - {}".format(type_name)
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
                            title="DQT - Group Manager")

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
            forms.alert("Select at least one instance first.", title="DQT - Group Manager")
            return
        ids = List[ElementId]()
        for row in self.dataGrid.SelectedItems:
            ids.Add(row.element_id)
        try:
            self.uidoc.Selection.SetElementIds(ids)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Group Manager")

    def zoom_to(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one instance first.", title="DQT - Group Manager")
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
        Title="Group Manager - DQT"
        Height="620" Width="1020"
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
            <Grid>
                <StackPanel>
                    <TextBlock Text="Group Manager" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="Model and Detail group types in this model - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
                </StackPanel>
                <Button x:Name="btnHelp" Content="? Help" Padding="10,4" Background="White"
                        HorizontalAlignment="Right" VerticalAlignment="Center"/>
            </Grid>
        </Border>

        <!-- Summary cards -->
        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
                <StackPanel><TextBlock Text="TOTAL TYPES" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtTotal" Text="0" FontSize="22" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="MODEL" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtModel" Text="0" FontSize="22" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="DETAIL" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtDetail" Text="0" FontSize="22" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
            </Border>
            <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
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
                    <TextBox x:Name="txtSearch" Padding="6,4" Margin="0,0,0,10" ToolTip="Name, creator or workset"/>
                    <TextBlock Text="CATEGORY" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <ComboBox x:Name="cmbFilter" Padding="6,4" Margin="0,0,0,10" SelectedIndex="0">
                        <ComboBoxItem Content="All"/>
                        <ComboBoxItem Content="Model only"/>
                        <ComboBoxItem Content="Detail only"/>
                    </ComboBox>
                    <TextBlock Text="Select a type and click Detail to see which view(s) its instances are used in." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
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
                    <DataGridTextColumn Header="Category" Binding="{Binding category}" Width="80" SortMemberPath="category"/>
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
class GroupManagerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.items = []
        self.filtered = []
        self._model_group_views = None     # lazy cache, see _ensure_model_group_view_cache

        self.txtSearch.TextChanged += self.on_filter
        self.cmbFilter.SelectionChanged += self.on_filter
        self.dataGrid.SelectionChanged += self.on_selection
        self.dataGrid.MouseDoubleClick += self.on_double_click

        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnRefresh.Click += self.refresh
        self.btnSelectInModel.Click += self.select_in_model
        self.btnZoom.Click += self.zoom_to
        self.btnDetail.Click += self.show_detail
        self.btnExportCSV.Click += self.export_csv
        self.btnClose.Click += self.close_window
        self.btnHelp.Click += self.on_help

        self.load_data()
        self.update_ui()

    def load_data(self):
        self.items = get_group_types(self.doc)
        self.filtered = list(self.items)

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtModel.Text = str(len([i for i in self.items if i.category == "Model"]))
        self.txtDetail.Text = str(len([i for i in self.items if i.category == "Detail"]))
        self.txtSelected.Text = "0"
        self.update_grid()

    def update_grid(self):
        self.dataGrid.Items.Clear()
        for item in self.filtered:
            self.dataGrid.Items.Add(item)

    def on_filter(self, s, e):
        search = self.txtSearch.Text.lower().strip() if self.txtSearch.Text else ""
        fi = self.cmbFilter.SelectedIndex

        self.filtered = []
        for item in self.items:
            if fi == 1 and item.category != "Model":
                continue
            if fi == 2 and item.category != "Detail":
                continue
            if search and search not in "{} {} {}".format(
                    item.name, item.created_by, item.workset).lower():
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
                            title="DQT - Group Manager")

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
                        title="DQT - Group Manager")
            return
        _navigate_to(self.uidoc, self.doc, ids)

    def select_all(self, s, e):
        self.dataGrid.SelectAll()

    def select_none(self, s, e):
        self.dataGrid.UnselectAll()

    def refresh(self, s, e):
        self._model_group_views = None     # placements may have changed
        self.load_data()
        self.on_filter(None, None)
        self.txtTotal.Text = str(len(self.items))
        self.txtModel.Text = str(len([i for i in self.items if i.category == "Model"]))
        self.txtDetail.Text = str(len([i for i in self.items if i.category == "Detail"]))

    def select_in_model(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one group type first.", title="DQT - Group Manager")
            return
        ids = self._selected_instance_ids()
        if len(ids) == 0:
            forms.alert("The selected group type(s) have no placed instances.",
                        title="DQT - Group Manager")
            return
        try:
            self.uidoc.Selection.SetElementIds(ids)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Group Manager")

    def zoom_to(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one group type first.", title="DQT - Group Manager")
            return
        ids = self._selected_instance_ids()
        if len(ids) == 0:
            forms.alert("The selected group type(s) have no placed instances.",
                        title="DQT - Group Manager")
            return
        _navigate_to(self.uidoc, self.doc, ids)

    def _ensure_model_group_view_cache(self):
        """Build (once, cached) {instance_id: [view_name,...]} for every
        Model Group instance. Returns None if the user cancels the scan."""
        if self._model_group_views is not None:
            return self._model_group_views

        cancelled = {"flag": False}
        with forms.ProgressBar(
                title="DQT - Scanning views for Model Group usage: "
                      "{value} of {max_value}",
                cancellable=True) as pb:
            def _cancel_check():
                cancelled["flag"] = pb.cancelled
                return cancelled["flag"]

            result = build_model_group_view_membership(
                self.doc, cancel_check=_cancel_check,
                progress_cb=lambda i, total: pb.update_progress(i, total))

        if cancelled["flag"]:
            forms.alert("Scan cancelled - Detail needs the full scan to show "
                        "Model Group usage.", title="DQT - Group Manager")
            return None
        self._model_group_views = result
        return result

    def show_detail(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            forms.alert("Select exactly one group type to see its detail.",
                        title="DQT - Group Manager")
            return
        item = self.dataGrid.SelectedItem
        if item.instance_count == 0:
            forms.alert("'{}' has no placed instances in this model.".format(item.name),
                        title="DQT - Group Manager")
            return

        model_group_views = None
        if item.category != "Detail":
            model_group_views = self._ensure_model_group_view_cache()
            if model_group_views is None:
                return      # user cancelled the scan

        rows = get_group_instance_details(self.doc, item, model_group_views)
        dlg = GroupDetailWindow(self.doc, self.uidoc, item.name, rows)
        dlg.ShowDialog()

    def export_csv(self, s, e):
        current_items = [item for item in self.dataGrid.Items]
        if not current_items:
            forms.alert("No data to export.", title="DQT - Group Manager")
            return

        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "CSV Files|*.csv"
        dlg.FileName = "GroupTypes_{}.csv".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

        if dlg.ShowDialog() == DialogResult.OK:
            try:
                with codecs.open(dlg.FileName, 'w', 'utf-8-sig') as f:
                    f.write("ID,Name,Category,Instances,Created By,Workset\n")
                    for item in current_items:
                        f.write('{},"{}",{},{},{},{}\n'.format(
                            item.type_id, item.name.replace('"', '""'),
                            item.category, item.instance_count,
                            item.created_by, item.workset))
                forms.alert("Exported {} row(s).".format(len(current_items)),
                            title="DQT - Group Manager")
            except Exception as ex:
                forms.alert(str(ex), title="DQT - Group Manager")

    def close_window(self, s, e):
        self.Close()

    def on_help(self, s, e):
        if _open_help_page("group_manager.html"):
            return
        forms.alert(
            "Group Manager\n\n"
            "Lists every Model Group and Detail Group TYPE with how many "
            "instances are actually placed, so an unused type (a purge "
            "candidate) or an over-used one is visible at a glance.\n\n"
            "STAT CARDS\n"
            "  TOTAL TYPES  - group types found\n"
            "  MODEL        - Model Group types\n"
            "  DETAIL       - Detail Group types\n"
            "  SELECTED     - rows currently selected in the grid\n\n"
            "WORKFLOW\n"
            "  Search / Type filter narrow the list.\n"
            "  Select in Model / Zoom To act on the ticked types' instances.\n"
            "  Detail shows exactly which view each instance of the "
            "selected type lives in.\n"
            "  Export CSV saves the visible list.",
            title="Group Manager - Help")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first.", title="DQT - Group Manager")
        else:
            GroupManagerWindow().ShowDialog()
    except Exception as ex:
        forms.alert("Error: {}".format(str(ex)), title="DQT - Group Manager Error")
