# -*- coding: utf-8 -*-
"""Group Manager v1.0
Author: Dang Quoc Truong (DQT)

Lists every Model Group and Detail Group TYPE in the model with how many
instances are actually placed, so an unused group type (a purge candidate)
or an over-used one is visible at a glance instead of hunting through the
Project Browser. View and Sheet columns say where each type is used;
selecting a type and clicking Detail shows exactly which view and sheet each
of its instances lives in. Delete removes the selected group types.
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
from dqt_sheet_utils import build_view_sheet_map, sheets_of_view, summarize
import codecs
import datetime

get_elementid_value = get_elementid_value_func()


def _open_help_page(html_filename):
    """Open this tool's page from the shared _Manage_Help folder in the
    default browser. Returns True on success, False if the caller should
    fall back to the in-app help text (e.g. the folder went missing)."""
    try:
        panel_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(panel_dir, "_Manage_Help", html_filename)
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
SCAN_NEEDED = "(scan needed)"


class GroupTypeSummary(object):
    def __init__(self):
        self.type_id = 0
        self.name = "<Unnamed>"
        self.category = "?"        # "Model" or "Detail"
        self.instance_count = 0
        self.created_by = "-"
        self.workset = "-"
        self.instance_ids = []     # ElementId of every placed instance
        self.type_element_id = None   # the GroupType's own ElementId, for Delete
        # Where its instances are used. view_names / sheet_names are the
        # full lists (search, CSV); views / sheets are the grid text.
        self.view_names = []
        self.sheet_names = []
        self.views = "-"
        self.sheets = "-"

    def set_usage(self, view_names, sheet_names, empty_text="-"):
        """Set the views / sheets this type's instances are in. No views at
        all reads empty_text; views that are on no sheet read "Not on a
        sheet"."""
        self.view_names = sorted(set(n for n in view_names if n))
        self.sheet_names = sorted(set(n for n in sheet_names if n))
        if not self.view_names:
            self.views = self.sheets = empty_text
            return
        self.views = summarize(self.view_names)
        self.sheets = summarize(self.sheet_names) if self.sheet_names else "Not on a sheet"

    def set_needs_scan(self):
        """A Model Group type: its views are only known once it has been
        selected and scanned (Scan Selected)."""
        self.view_names = []
        self.sheet_names = []
        self.views = self.sheets = SCAN_NEEDED

    @property
    def views_csv(self):
        return "; ".join(self.view_names) if self.view_names else self.views

    @property
    def sheets_csv(self):
        return "; ".join(self.sheet_names) if self.sheet_names else self.sheets


class GroupInstanceDetail(object):
    def __init__(self):
        self.instance_id = 0
        self.views = "-"
        self.sheets = "-"
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


def _fill_type_usage(doc, item, owner_ids, view_sheet_map, view_cache):
    """View / Sheet text for one type, from what needs no scan: a Detail
    Group instance carries the one view it was placed into (OwnerViewId).
    A Model Group instance carries none - it is shown in every view that
    sees it - so a Model type stays "(scan needed)" until it has been
    selected and scanned with Scan Selected (see apply_model_group_usage)."""
    if item.instance_count == 0:
        item.set_usage([], [])
        return
    if item.category != "Detail":
        item.set_needs_scan()
        return
    names = []
    sheets = []
    for owner_id in owner_ids:
        key = _eid_int(owner_id)
        if key not in view_cache:
            try:
                view_cache[key] = doc.GetElement(owner_id)
            except:
                view_cache[key] = None
        view = view_cache[key]
        if view is None:
            continue
        try:
            name = view.Name
        except:
            name = None
        if name:
            names.append(name)
        sheets.extend(sheets_of_view(view, view_sheet_map))
    item.set_usage(names, sheets)


def apply_model_group_usage(items, membership, view_sheet_map, scanned_type_ids):
    """Fill View / Sheet on the Model types that have been scanned
    (scanned_type_ids) from the view-membership scan ({group instance id:
    [(view id, view name), ...]}) - the sheets are the ones those views are
    placed on. A type that was never scanned is left as it is."""
    for item in items:
        if item.category == "Detail" or item.instance_count == 0:
            continue
        if item.type_id not in scanned_type_ids:
            continue
        names = []
        sheets = []
        for eid in item.instance_ids:
            for view_id, view_name in membership.get(_eid_int(eid), []):
                names.append(view_name)
                sheets.extend(view_sheet_map.get(view_id, []))
        item.set_usage(names, sheets, empty_text="(no view found)")


def get_group_types(doc, view_sheet_map=None):
    """One row per GroupType (Model or Detail), with how many placed
    instances reference it and the views / sheets they are in. Types with
    zero instances are listed too - an unused group type sitting in the
    model is exactly what this tool is for finding.

    Counting is done in one pass over every Group instance (matching each
    to its type via GetTypeId(), the same pattern this suite's own
    FamilyManager tool already uses) rather than re-scanning all instances
    once per type. The same pass collects each instance's owner view, so
    Detail Group views cost nothing extra. view_sheet_map is
    build_view_sheet_map(doc)."""
    if view_sheet_map is None:
        view_sheet_map = {}
    counts = {}
    instances_of = {}
    owner_views_of = {}
    for inst in FilteredElementCollector(doc).OfClass(Group):
        try:
            tid = _eid_int(inst.GetTypeId())
        except:
            continue
        counts[tid] = counts.get(tid, 0) + 1
        instances_of.setdefault(tid, []).append(inst.Id)
        try:
            owner_id = inst.OwnerViewId
            if owner_id is not None and _eid_int(owner_id) > 0:
                owner_views_of.setdefault(tid, []).append(owner_id)
        except:
            pass

    view_cache = {}
    items = []
    for gt in FilteredElementCollector(doc).OfClass(GroupType):
        try:
            item = GroupTypeSummary()
            item.type_id = _eid_int(gt.Id)
            item.type_element_id = gt.Id
            item.name = _group_type_name(gt)
            item.category = _group_category(gt.Category.Id) if gt.Category else "?"
            item.instance_count = counts.get(item.type_id, 0)
            item.instance_ids = instances_of.get(item.type_id, [])
            item.created_by = _get_created_by(doc, gt)
            item.workset = _get_workset(doc, gt)
            _fill_type_usage(doc, item, owner_views_of.get(item.type_id, []),
                             view_sheet_map, view_cache)
            items.append(item)
        except:
            continue
    return items


def _owner_view(doc, inst):
    """The single view a Detail Group instance was placed into - Detail
    Groups are view-specific, so OwnerViewId always answers this directly
    without needing to scan anything. None if it has no owner view. Never
    raises."""
    try:
        owner_id = inst.OwnerViewId
        if owner_id is not None and _eid_int(owner_id) > 0:
            return doc.GetElement(owner_id)
    except:
        pass
    return None


# View types that can never show a Model Group instance: no model geometry
# in them, so asking them what they contain is wasted time (sheets alone are
# often a large share of a big model's views). Looked up by name so one
# missing in this Revit version (or spelled differently) cannot break the
# tool.
_NON_MODEL_VIEW_TYPES = set(
    getattr(ViewType, name) for name in (
        "Undefined", "Internal", "ProjectBrowser", "SystemBrowser",
        "DrawingSheet", "Schedule", "Legend", "DraftingView",
        "PanelSchedule", "ColumnSchedule", "CostReport", "LoadsReport",
        "PresureLossReport", "PressureLossReport", "Report",
        "SystemsAnalysisReport")
    if hasattr(ViewType, name))


def _is_model_view(v):
    """A non-template view that can show model elements."""
    try:
        if getattr(v, "IsTemplate", False):
            return False
        return v.ViewType not in _NON_MODEL_VIEW_TYPES
    except:
        return False


def build_model_group_view_membership(doc, instance_ids, cancel_check=None,
                                      progress_cb=None):
    """{group_instance_id_int: [(view_id_int, view_name), ...]} for the given
    Model Group instances only - which views show each one.

    A Model Group instance carries no OwnerView - unlike a Detail Group, it
    can appear in many views at once - so the only way to know which views
    actually show one is to ask each view what it contains. That is one
    FilteredElementCollector per VIEW (not per instance and not per group
    type). Two things keep it light on a big model:
      - each view is asked only about instance_ids, through an
        ElementIdSetFilter, and answers with ElementIds (ToElementIds) - no
        Group element object is created for any group in any view. Walking
        every group in every view with OfClass(Group) built one element
        wrapper per group per view, which on a large model is what ran
        Revit out of memory;
      - only views that can hold model elements are asked (see
        _NON_MODEL_VIEW_TYPES).
    instance_ids is a list of ElementId."""
    membership = {}
    if not instance_ids:
        return membership
    id_filter = ElementIdSetFilter(List[ElementId](instance_ids))
    views = [(_eid_int(v.Id), v.Name, v.Id)
             for v in FilteredElementCollector(doc).OfClass(View)
             if _is_model_view(v)]
    total = len(views)
    for i, (view_id, view_name, view_eid) in enumerate(views):
        if cancel_check and cancel_check():
            break
        if progress_cb:
            progress_cb(i + 1, total)
        try:
            for eid in FilteredElementCollector(doc, view_eid) \
                    .WherePasses(id_filter).ToElementIds():
                membership.setdefault(_eid_int(eid), []).append((view_id, view_name))
        except:
            continue
    return membership


def get_group_instance_details(doc, type_summary, model_group_views=None,
                               view_sheet_map=None):
    """Per-instance rows for one GroupType: which view(s) and sheet(s) each
    instance is used in.

    Detail Group instances resolve instantly via OwnerViewId. Model Group
    instances need the (expensive, caller-supplied/cached) view-membership
    map - model_group_views is None until the caller has actually built it,
    in which case every Model Group instance is reported as not-yet-scanned
    rather than the tool pretending to have an answer it does not."""
    if view_sheet_map is None:
        view_sheet_map = {}
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
            view = _owner_view(doc, inst)
            view_name = getattr(view, "Name", None) if view else None
            row.views = view_name if view_name else "-"
            sheets = sheets_of_view(view, view_sheet_map)
            if view_name:
                row.sheets = "; ".join(sheets) if sheets else "Not on a sheet"
        else:
            if model_group_views is None:
                row.views = row.sheets = "(not scanned)"
            else:
                pairs = model_group_views.get(row.instance_id)
                if pairs:
                    names = sorted(set(name for _, name in pairs))
                    sheets = sorted(set(label for view_id, _ in pairs
                                        for label in view_sheet_map.get(view_id, [])))
                    row.views = "; ".join(names)
                    row.sheets = "; ".join(sheets) if sheets else "Not on a sheet"
                else:
                    row.views = "(no view found)"
        rows.append(row)
    return rows


def delete_confirm_message(selected):
    """(message, placed) for the Delete confirmation: placed is the selected
    types that still have instances. Deleting a group type deletes every
    instance of it and the elements inside those groups, so those are named
    up front; a selection of unused types says nothing else goes with it."""
    placed = [i for i in selected if i.instance_count > 0]
    unused = [i for i in selected if i.instance_count == 0]
    if placed:
        lines = ["   - {} ({}, {} instance(s))".format(
            i.name, i.category, i.instance_count) for i in placed[:8]]
        if len(placed) > 8:
            lines.append("   ... and {} more".format(len(placed) - 8))
        msg = ("Delete {} group type(s)?\n\nWARNING: {} of them are PLACED in "
               "the model ({} instance(s) in all):\n{}\n\nDeleting a group "
               "type also deletes every instance of it, and the elements "
               "inside those groups, from the model.").format(
                   len(selected), len(placed),
                   sum(i.instance_count for i in placed), "\n".join(lines))
        if unused:
            msg += ("\n\nThe other {} have no instances, so nothing else goes "
                    "with them.").format(len(unused))
        msg += ("\n\nUndo (Ctrl+Z) restores everything right after if "
                "needed.\n\nDelete anyway?")
    else:
        msg = ("Delete {} unused group type(s)?\n\nNone of them is placed in "
               "the model, so nothing else is removed.\n\nUndo (Ctrl+Z) "
               "restores them right after if needed.").format(len(selected))
    return msg, placed


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
        Height="500" Width="900"
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
                <DataGridTextColumn Header="Sheet(s)" Binding="{Binding sheets}" Width="240" SortMemberPath="sheets"/>
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
        Height="620" Width="1300"
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
                    <TextBox x:Name="txtSearch" Padding="6,4" Margin="0,0,0,10" ToolTip="Name, creator, workset, view or sheet"/>
                    <TextBlock Text="CATEGORY" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <ComboBox x:Name="cmbFilter" Padding="6,4" Margin="0,0,0,10" SelectedIndex="0">
                        <ComboBoxItem Content="All"/>
                        <ComboBoxItem Content="Model only"/>
                        <ComboBoxItem Content="Detail only"/>
                    </ComboBox>
                    <TextBlock Text="View / Sheet: Detail Group types fill in at once. A Model Group shows in many views, so select the Model type(s) you want and click Scan Selected - only those are scanned. Detail scans just the one type you select." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
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
                    <DataGridTextColumn Header="View" Binding="{Binding views}" Width="200" SortMemberPath="views"/>
                    <DataGridTextColumn Header="Sheet" Binding="{Binding sheets}" Width="200" SortMemberPath="sheets"/>
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
                    <Button x:Name="btnScan" Content="Scan Selected" Padding="10,5" Margin="2" Background="#F0CC88" ToolTip="Find the views and sheets of the SELECTED Model Group types. Only those are scanned; the result is kept until Refresh."/>
                    <Button x:Name="btnDetail" Content="Detail" Padding="10,5" Margin="2" Background="#F0CC88" FontWeight="SemiBold"/>
                    <Button x:Name="btnExportCSV" Content="Export CSV" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnDelete" Content="Delete" Padding="10,5" Margin="2" Background="#FF6B6B" Foreground="White" ToolTip="Delete the selected group types. A type that is placed also loses its instances - you are asked to confirm first."/>
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
        # Model Group view scan, kept per scanned type until Refresh (see
        # _scan_types): {instance id: [(view id, view name), ...]} and the
        # ids of the types it covers.
        self._model_group_views = {}
        self._scanned_types = set()
        self._view_sheet_map = {}          # view id -> sheet labels, built per load

        self.txtSearch.TextChanged += self.on_filter
        self.cmbFilter.SelectionChanged += self.on_filter
        self.dataGrid.SelectionChanged += self.on_selection
        self.dataGrid.MouseDoubleClick += self.on_double_click

        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnRefresh.Click += self.refresh
        self.btnSelectInModel.Click += self.select_in_model
        self.btnZoom.Click += self.zoom_to
        self.btnScan.Click += self.scan_views
        self.btnDetail.Click += self.show_detail
        self.btnExportCSV.Click += self.export_csv
        self.btnDelete.Click += self.delete_selected
        self.btnClose.Click += self.close_window
        self.btnHelp.Click += self.on_help

        self.load_data()
        self.update_ui()

    def load_data(self):
        self._view_sheet_map = build_view_sheet_map(self.doc)
        self.items = get_group_types(self.doc, self._view_sheet_map)
        if self._scanned_types:
            apply_model_group_usage(self.items, self._model_group_views,
                                    self._view_sheet_map, self._scanned_types)
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
            if search and search not in "{} {} {} {} {}".format(
                    item.name, item.created_by, item.workset,
                    "; ".join(item.view_names), "; ".join(item.sheet_names)).lower():
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
        self._model_group_views = {}       # placements may have changed
        self._scanned_types = set()
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

    def _scan_types(self, items):
        """Scan the views of these Model Group types (the ones not scanned
        yet) and keep the result. Returns False if the user cancels - nothing
        from a cancelled scan is kept, so a type is never half-filled."""
        todo = [i for i in items
                if i.category != "Detail" and i.instance_count > 0
                and i.type_id not in self._scanned_types]
        if not todo:
            return True
        instance_ids = [eid for i in todo for eid in i.instance_ids]

        cancelled = {"flag": False}
        with forms.ProgressBar(
                title="DQT - Scanning views for " + str(len(instance_ids)) +
                      " Model Group instance(s): {value} of {max_value}",
                cancellable=True) as pb:
            def _cancel_check():
                cancelled["flag"] = pb.cancelled
                return cancelled["flag"]

            result = build_model_group_view_membership(
                self.doc, instance_ids, cancel_check=_cancel_check,
                progress_cb=lambda i, total: pb.update_progress(i, total))

        if cancelled["flag"]:
            forms.alert("Scan cancelled - nothing was kept for the type(s) "
                        "being scanned.", title="DQT - Group Manager")
            return False
        self._model_group_views.update(result)
        self._scanned_types.update(i.type_id for i in todo)
        return True

    def _apply_scan_to_grid(self):
        """Put the view-membership scan's results on the scanned Model rows
        and redraw, keeping the current selection."""
        apply_model_group_usage(self.items, self._model_group_views,
                                self._view_sheet_map, self._scanned_types)
        keep = set(i.type_id for i in self.dataGrid.SelectedItems)
        self.update_grid()
        for item in self.filtered:
            if item.type_id in keep:
                self.dataGrid.SelectedItems.Add(item)

    def scan_views(self, s, e):
        """Scan Selected - only the Model Group types ticked in the grid."""
        selected = list(self.dataGrid.SelectedItems)
        if not selected:
            forms.alert("Select the Model Group type(s) to scan first. Only "
                        "the selected types are scanned.",
                        title="DQT - Group Manager")
            return
        model_items = [i for i in selected
                       if i.category != "Detail" and i.instance_count > 0]
        if not model_items:
            forms.alert("Nothing to scan in the selection: Detail Group types "
                        "are filled in already, and a type with no instances "
                        "has nothing to scan.", title="DQT - Group Manager")
            return
        todo = [i for i in model_items if i.type_id not in self._scanned_types]
        if not todo:
            forms.alert("The selected Model Group type(s) are already "
                        "scanned. Use Refresh to scan again after placements "
                        "change.", title="DQT - Group Manager")
            return
        if not self._scan_types(todo):
            return      # user cancelled the scan
        self._apply_scan_to_grid()

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
            if item.type_id not in self._scanned_types:
                if not self._scan_types([item]):    # just this one type
                    return      # user cancelled the scan
                self._apply_scan_to_grid()      # the grid's View/Sheet too
            model_group_views = self._model_group_views

        rows = get_group_instance_details(self.doc, item, model_group_views,
                                          self._view_sheet_map)
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
                    f.write("ID,Name,Category,Instances,View,Sheet,Created By,Workset\n")
                    for item in current_items:
                        f.write('{},"{}",{},{},"{}","{}",{},{}\n'.format(
                            item.type_id, item.name.replace('"', '""'),
                            item.category, item.instance_count,
                            item.views_csv.replace('"', '""'),
                            item.sheets_csv.replace('"', '""'),
                            item.created_by, item.workset))
                forms.alert("Exported {} row(s).".format(len(current_items)),
                            title="DQT - Group Manager")
            except Exception as ex:
                forms.alert(str(ex), title="DQT - Group Manager")

    def delete_selected(self, s, e):
        selected = list(self.dataGrid.SelectedItems)
        if not selected:
            forms.alert("Select at least one group type first.",
                        title="DQT - Group Manager")
            return

        msg, placed = delete_confirm_message(selected)
        if not forms.alert(msg, title="DQT - Group Manager: Confirm Delete",
                           yes=True, no=True, warn_icon=bool(placed)):
            return

        deleted, failed = self._delete_items(selected)

        result = "Deleted {} of {} group type(s).".format(len(deleted), len(selected))
        removed_instances = sum(i.instance_count for i in deleted)
        if removed_instances:
            result += "\nThat removed {} placed instance(s) with them.".format(
                removed_instances)
        if failed:
            lines = failed[:8]
            more = "" if len(failed) <= 8 else "\n... and {} more".format(len(failed) - 8)
            result += "\n\nCould not delete:\n{}{}".format("\n".join(lines), more)
        forms.alert(result, title="DQT - Group Manager")

        self.refresh(s, e)

    def _delete_items(self, items):
        """Delete these group types in one transaction. Returns (deleted
        items, failure descriptions).

        Each type is deleted on its own inside the transaction, so one Revit
        refuses (a pinned instance, an element another user has checked out)
        is reported and the rest still go. A type Revit already removed along
        with an earlier one (a group nested in another) counts as deleted
        rather than as a failure. If the transaction itself fails it is
        rolled back, so nothing is reported as deleted."""
        deleted = []
        failed = []
        gone = set()
        try:
            with revit.Transaction("DQT - Delete Group(s)"):
                for item in items:
                    if item.type_id in gone:
                        deleted.append(item)
                        continue
                    if item.type_element_id is None:
                        failed.append("{} (ID {}) - no element id".format(
                            item.name, item.type_id))
                        continue
                    try:
                        removed = self.doc.Delete(item.type_element_id)
                        for eid in removed:
                            gone.add(_eid_int(eid))
                        deleted.append(item)
                    except Exception as ex:
                        failed.append("{} (ID {}) - {}".format(
                            item.name, item.type_id, ex))
        except Exception as ex:
            deleted = []
            failed.append("transaction failed and was rolled back: {}".format(ex))
        return deleted, failed

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
            "VIEW / SHEET COLUMNS\n"
            "  View  - the view(s) the type's instances are in.\n"
            "  Sheet - the sheet(s) those views are on; 'Not on a sheet' "
            "if none is.\n"
            "  Detail Group types fill in at once. A Model Group shows in "
            "many views, so its cells read '(scan needed)' until you select "
            "the Model type(s) and click Scan Selected. Only the selected "
            "types are scanned (progress bar, cancellable), and the result "
            "is kept until Refresh. A long list shows the first 3 and "
            "'(+N more)'; Detail and Export CSV have all of them.\n\n"
            "WORKFLOW\n"
            "  Search matches name, creator, workset, view or sheet.\n"
            "  Category filter narrows the list.\n"
            "  Select in Model / Zoom To act on the ticked types' instances.\n"
            "  Detail shows exactly which view and sheet each instance of "
            "the selected type lives in (for a Model type it scans just "
            "that one type).\n"
            "  Export CSV saves the visible list.\n"
            "  Delete removes the selected group types, after asking. A "
            "type with no instances is removed on its own; a type that is "
            "placed also takes every instance of it, and the elements "
            "inside those groups, with it - the confirmation names those "
            "types first. Undo (Ctrl+Z) restores it right after.",
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
