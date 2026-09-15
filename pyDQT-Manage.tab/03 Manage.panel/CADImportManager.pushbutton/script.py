# -*- coding: utf-8 -*-
"""CAD Import Manager v1.2
Author: Dang Quoc Truong (DQT)

Lists every CAD file imported or linked into the model (ImportInstance
elements) with its file name, link type, creator, workset, host level and
the view it was placed into, so a stray or oversized CAD file can be found
and selected without hunting through every view.

Also finds and purges "unused" CAD Import/Link Types - a Type left with
zero instances after its last placement is deleted, which Revit never
auto-deletes on its own, and which ACC's Model Analytics (Insight) keeps
reporting as present since it reports CAD imports at the Type level.
"""
__title__ = "CAD Import\nManager"
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
from System.Windows import Visibility
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
class CADImportItem(object):
    def __init__(self):
        self.element_id = 0
        self.type_id = 0              # the CADLinkType's own Id - what ACC reports
        self.name = "<Unnamed>"
        self.link_type = "Import"     # "Import" or "Link"
        self.created_by = "-"
        self.workset = "-"
        self.level = "-"
        self.view_name = "-"
        self.element = None


def _cad_type_name(doc, elem):
    """The CAD file name, tried in the order this codebase's other CAD tools
    already rely on (Element.Name.GetValue on the type is the version-stable
    one; LookupParameter and the raw Id are fallbacks for whichever of those
    a given Revit build refuses)."""
    try:
        p = elem.LookupParameter("Name")
        if p and p.HasValue:
            val = p.AsString()
            if val:
                return val
    except:
        pass

    cad_type = None
    try:
        cad_type = doc.GetElement(elem.GetTypeId())
    except:
        pass
    if cad_type:
        try:
            val = DB.Element.Name.GetValue(cad_type)
            if val:
                return val
        except:
            pass
        try:
            p = cad_type.LookupParameter("Name")
            if p and p.HasValue:
                val = p.AsString()
                if val:
                    return val
        except:
            pass

    return "<Unnamed> (ID {})".format(_eid_int(elem.Id))


def _cad_type_type_name(doc, cad_type):
    """The CAD file name for a CADLinkType itself (not an instance) - same
    fallback order as _cad_type_name, applied directly since there is no
    further TypeId to chase from a type."""
    try:
        p = cad_type.LookupParameter("Name")
        if p and p.HasValue:
            val = p.AsString()
            if val:
                return val
    except:
        pass
    try:
        val = DB.Element.Name.GetValue(cad_type)
        if val:
            return val
    except:
        pass
    return "<Unnamed> (ID {})".format(_eid_int(cad_type.Id))


def _cad_type_of(doc, elem):
    """The CADLinkType behind an ImportInstance, or None."""
    try:
        return doc.GetElement(elem.GetTypeId())
    except:
        return None


def _is_linked(doc, elem):
    """True for a CAD Link, False for a CAD Import (embedded geometry).

    Asked in order of how definitive each answer is:

    1) Element.IsExternalFileReference() on the CAD type. A Link keeps an
       external .dwg on disk and reports True; a true Import embedded the
       geometry at import time and has no external file, so it reports
       False. This is the documented, version-stable way to ask, and it
       is asked first precisely because (2) is not reliable everywhere.
    2) ImportInstance.IsLinked, when (1) is unavailable - the instance
       level property, which this suite's CadtoWall tool found missing on
       some Revit 2026 builds.
    3) An external file reference that actually resolves to a path.

    The previous version started at (2) and treated ANY non-null return
    from GetExternalFileReference() as "Link". On a build where (2) is
    missing, that classified every CAD file in the model as a Link and
    left the IMPORTS card permanently at 0 - including for models where
    ACC's Model Analytics reports genuine imports. A reference object
    carrying no usable path is not a link."""
    cad_type = _cad_type_of(doc, elem)

    if cad_type is not None:
        try:
            return bool(cad_type.IsExternalFileReference())
        except:
            pass

    try:
        return bool(elem.IsLinked)
    except:
        pass

    if cad_type is not None:
        try:
            efr = cad_type.GetExternalFileReference()
        except:
            efr = None
        if efr is not None:
            try:
                path = efr.GetAbsolutePath()
                if path is not None and path.Empty:
                    return False
            except:
                pass
            return True

    return False


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


def _get_level(doc, elem):
    """Best-effort host level for a CAD import.

    ImportInstance carries no dedicated LevelId property, so this tries
    every route Revit exposes one through instead of relying on a single
    parameter name that might not exist on every Revit build:
      1) an instance parameter literally named "Level" - what Properties
         shows for an import Revit associated with one at placement time.
      2) the level of the view it was imported into, when that view is
         plan-based (an import placed in "all views" has no such view).
    Never raises - a level that cannot be determined is reported as "-"
    rather than failing the whole row."""
    try:
        for p in elem.Parameters:
            try:
                if p.Definition and p.Definition.Name.strip().lower() == "level":
                    val = p.AsValueString()
                    if val:
                        return val
                    eid = p.AsElementId()
                    if eid is not None and _eid_int(eid) > 0:
                        lv = doc.GetElement(eid)
                        if lv:
                            return lv.Name
            except:
                continue
    except:
        pass

    try:
        owner_id = elem.OwnerViewId
        if owner_id is not None and _eid_int(owner_id) > 0:
            view = doc.GetElement(owner_id)
            gen_level = getattr(view, "GenLevel", None) if view else None
            if gen_level:
                return gen_level.Name
    except:
        pass

    return "-"


def _get_view_name(doc, elem):
    """The view this CAD file was placed into, or "All views" when it was
    imported/linked without being restricted to one view (OwnerViewId is
    invalid in that case). Never raises."""
    try:
        owner_id = elem.OwnerViewId
        if owner_id is not None and _eid_int(owner_id) > 0:
            view = doc.GetElement(owner_id)
            name = getattr(view, "Name", None) if view else None
            if name:
                return name
    except:
        pass
    return "All views"


def _link_status_suffix(doc, elem, is_linked):
    """" (Unloaded)" / " (Not Found)" for a CAD Link whose external file
    is not currently loaded - empty string for an Import (no external file
    to be unloaded) or a normally loaded Link.

    This is what actually explains Revit's "No good view could be found"
    popup on Zoom To: an unloaded/missing link has no geometry anywhere in
    the model for ShowElements to navigate to. Flagging it here means the
    tool can skip calling ShowElements on it and explain why, instead of
    letting that native dialog surprise the user."""
    if not is_linked:
        return ""
    try:
        cad_type = doc.GetElement(elem.GetTypeId())
        efr = cad_type.GetExternalFileReference() if cad_type else None
        if efr is None:
            return ""
        name = str(efr.GetLinkedFileStatus())
        if "." in name:
            name = name.rsplit(".", 1)[-1]     # enum str() can be qualified
        if name and name != "Loaded":
            pretty = "".join(" " + c if c.isupper() else c
                              for c in name).strip()
            return " ({})".format(pretty)
    except:
        pass
    return ""


def get_cad_imports(doc):
    items = []
    collector = FilteredElementCollector(doc).OfClass(ImportInstance) \
        .WhereElementIsNotElementType()
    for elem in collector:
        try:
            item = CADImportItem()
            item.element = elem
            item.element_id = _eid_int(elem.Id)
            item.type_id = _eid_int(elem.GetTypeId())
            item.name = _cad_type_name(doc, elem)
            is_linked = _is_linked(doc, elem)
            item.link_type = ("Link" if is_linked else "Import") \
                + _link_status_suffix(doc, elem, is_linked)
            item.created_by = _get_created_by(doc, elem)
            item.workset = _get_workset(doc, elem)
            item.level = _get_level(doc, elem)
            item.view_name = _get_view_name(doc, elem)
            items.append(item)
        except:
            continue
    return items


def _get_closed_worksets(doc):
    """Names of user worksets that are NOT open in this session.

    This is the actual answer to "ACC Insight finds a CAD import this
    tool doesn't": Insight's Model Analytics reads the .rvt file itself
    server-side and always sees every workset, but a live Revit/pyRevit
    session never loads a closed workset's elements into the document at
    all - FilteredElementCollector has nothing to find there, no matter
    how this tool queries it. Reopening the model with every workset open
    is the only way to make those elements visible here too. Returns an
    empty list for a non-workshared model (nothing to be closed)."""
    if not doc.IsWorkshared:
        return []
    closed = []
    try:
        for ws in FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset):
            try:
                if not ws.IsOpen:
                    closed.append(ws.Name)
            except:
                continue
    except:
        pass
    return sorted(closed)


def _get_unused_cad_types(doc):
    """CADLinkType ("Import Symbol") types with zero placed instances left.

    Deleting every instance of a CAD import (one at a time, or via this
    tool's own Delete) does NOT delete the Type itself - Revit never
    auto-purges a Type just because its instance count reaches zero,
    exactly like a WallType or FamilySymbol left behind after its last
    instance is gone. Since ACC's Model Analytics reports CAD imports at
    the TYPE level (confirmed by comparing FilteredElementCollector
    output against the Element IDs ACC reports - they resolve to
    CADLinkType, not ImportInstance), an orphaned Type like this keeps
    showing up there indefinitely even though the model has zero
    instances of it. This is what "Purge Unused Types" cleans up."""
    used_type_ids = set()
    try:
        for inst in FilteredElementCollector(doc).OfClass(ImportInstance) \
                .WhereElementIsNotElementType():
            try:
                used_type_ids.add(_eid_int(inst.GetTypeId()))
            except:
                continue
    except:
        pass

    unused = []
    try:
        for cad_type in FilteredElementCollector(doc).OfClass(CADLinkType):
            try:
                if _eid_int(cad_type.Id) not in used_type_ids:
                    unused.append(cad_type)
            except:
                continue
    except:
        pass
    return unused


# ============================================================================
# XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="CAD Import Manager - DQT"
        Height="680" Width="1190"
        WindowStartupLocation="CenterScreen"
        Background="#FEF8E7">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
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
                    <TextBlock Text="CAD Import Manager" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="Imported / linked CAD files in this model - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
                </StackPanel>
                <Button x:Name="btnHelp" Content="? Help" Padding="10,4" Background="White"
                        HorizontalAlignment="Right" VerticalAlignment="Center"/>
            </Grid>
        </Border>

        <!-- Closed-worksets warning - hidden unless this session actually has some closed -->
        <Border x:Name="warningBanner" Grid.Row="1" Background="#FFF3CD" BorderBrush="#E5B85C" BorderThickness="1"
                CornerRadius="4" Padding="10,6" Margin="0,0,0,10" Visibility="Collapsed">
            <TextBlock x:Name="txtWarning" FontSize="10" Foreground="#5D4E37" TextWrapping="Wrap"/>
        </Border>

        <!-- Summary cards -->
        <Grid Grid.Row="2" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
                <StackPanel><TextBlock Text="TOTAL" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtTotal" Text="0" FontSize="22" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="IMPORTS" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtImports" Text="0" FontSize="22" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="LINKS" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtLinks" Text="0" FontSize="22" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
            </Border>
            <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="SELECTED" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtSelected" Text="0" FontSize="22" FontWeight="Bold" Foreground="#5D4E37"/></StackPanel>
            </Border>
            <Border Grid.Column="4" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
                <StackPanel><TextBlock Text="UNUSED TYPES" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtUnusedTypes" Text="0" FontSize="22" FontWeight="Bold" Foreground="#FF6B6B"/></StackPanel>
            </Border>
        </Grid>

        <!-- Content -->
        <Grid Grid.Row="3">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="170"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- Left Panel -->
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8" Margin="0,0,8,0">
                <StackPanel>
                    <TextBlock Text="SEARCH" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <TextBox x:Name="txtSearch" Padding="6,4" Margin="0,0,0,10" ToolTip="Name, creator, workset, view, ID or Type ID"/>
                    <TextBlock Text="TYPE" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <ComboBox x:Name="cmbFilter" Padding="6,4" Margin="0,0,0,10" SelectedIndex="0">
                        <ComboBoxItem Content="All"/>
                        <ComboBoxItem Content="Import only"/>
                        <ComboBoxItem Content="Link only"/>
                    </ComboBox>
                    <TextBlock Text="Double-click ID or Type ID to copy it. Double-click elsewhere on a row to select + zoom to that file. Type ID is the Element ID ACC's Model Analytics reports - paste it into Search to find its instances." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
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
                    <DataGridTextColumn x:Name="colId" Header="ID" Binding="{Binding element_id}" Width="70" SortMemberPath="element_id"/>
                    <DataGridTextColumn x:Name="colTypeId" Header="Type ID" Binding="{Binding type_id}" Width="70" SortMemberPath="type_id"/>
                    <DataGridTextColumn Header="File Name" Binding="{Binding name}" Width="*" SortMemberPath="name"/>
                    <DataGridTextColumn Header="Type" Binding="{Binding link_type}" Width="70" SortMemberPath="link_type"/>
                    <DataGridTextColumn Header="Created By" Binding="{Binding created_by}" Width="120" SortMemberPath="created_by"/>
                    <DataGridTextColumn Header="Workset" Binding="{Binding workset}" Width="120" SortMemberPath="workset"/>
                    <DataGridTextColumn Header="View" Binding="{Binding view_name}" Width="160" SortMemberPath="view_name"/>
                    <DataGridTextColumn Header="Level" Binding="{Binding level}" Width="100" SortMemberPath="level"/>
                </DataGrid.Columns>
            </DataGrid>
        </Grid>

        <!-- Action Buttons -->
        <Border Grid.Row="4" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="8" Margin="0,10,0,0">
            <Grid>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
                    <Button x:Name="btnSelectAll" Content="Select All" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnClear" Content="Clear" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnRefresh" Content="Refresh" Padding="10,5" Margin="2" Background="White"/>
                </StackPanel>
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                    <Button x:Name="btnSelectInModel" Content="Select in Model" Padding="10,5" Margin="2" Background="#F0CC88"/>
                    <Button x:Name="btnZoom" Content="Zoom To" Padding="10,5" Margin="2" Background="#F0CC88"/>
                    <Button x:Name="btnExportCSV" Content="Export CSV" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnPurgeTypes" Content="Purge Unused Types" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnDelete" Content="Delete" Padding="10,5" Margin="2" Background="#FF6B6B" Foreground="White"/>
                    <Button x:Name="btnClose" Content="Close" Padding="10,5" Margin="2" Background="White"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- Footer -->
        <Border Grid.Row="5" Background="#F0CC88" CornerRadius="3" Padding="8,5" Margin="0,8,0,0">
            <TextBlock Text="Dang Quoc Truong - DQT (c) 2026" FontSize="10" FontWeight="SemiBold" HorizontalAlignment="Center" Foreground="#5D4E37"/>
        </Border>
    </Grid>
</Window>
"""


# ============================================================================
# MAIN WINDOW
# ============================================================================
class CADImportManagerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.items = []
        self.filtered = []
        self.closed_worksets = []
        self.unused_types = []

        self.txtSearch.TextChanged += self.on_filter
        self.cmbFilter.SelectionChanged += self.on_filter
        self.dataGrid.SelectionChanged += self.on_selection
        self.dataGrid.MouseDoubleClick += self.on_double_click

        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnRefresh.Click += self.refresh
        self.btnSelectInModel.Click += self.select_in_model
        self.btnZoom.Click += self.zoom_to
        self.btnExportCSV.Click += self.export_csv
        self.btnPurgeTypes.Click += self.purge_unused_types
        self.btnDelete.Click += self.delete_selected
        self.btnClose.Click += self.close_window
        self.btnHelp.Click += self.on_help

        self.load_data()
        self.update_ui()

    def load_data(self):
        self.items = get_cad_imports(self.doc)
        self.filtered = list(self.items)
        self.closed_worksets = _get_closed_worksets(self.doc)
        self.unused_types = _get_unused_cad_types(self.doc)

    def _update_warning_banner(self):
        """Explains the #1 cause of "this tool doesn't find a CAD import
        that ACC's Model Analytics does": elements on a workset this
        session hasn't opened are invisible to every in-session tool, not
        just this one - see _get_closed_worksets."""
        if not self.closed_worksets:
            self.warningBanner.Visibility = Visibility.Collapsed
            return
        names = self.closed_worksets[:6]
        more = "" if len(self.closed_worksets) <= 6 else \
            " and {} more".format(len(self.closed_worksets) - 6)
        self.txtWarning.Text = (
            "{} workset(s) are closed in this session - {}{}. CAD Imports/Links "
            "on a closed workset are not loaded at all, so they cannot show up "
            "below, even though ACC's Model Analytics (which reads the whole "
            "file server-side) will still find them. Reopen the model with all "
            "worksets open to see the complete list here too.".format(
                len(self.closed_worksets), ", ".join(names), more))
        self.warningBanner.Visibility = Visibility.Visible

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtImports.Text = str(len([i for i in self.items if i.link_type.startswith("Import")]))
        self.txtLinks.Text = str(len([i for i in self.items if i.link_type.startswith("Link")]))
        self.txtSelected.Text = "0"
        self.txtUnusedTypes.Text = str(len(self.unused_types))
        self._update_warning_banner()
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
            if fi == 1 and not item.link_type.startswith("Import"):
                continue
            if fi == 2 and not item.link_type.startswith("Link"):
                continue
            if search and search not in "{} {} {} {} {} {}".format(
                    item.name, item.created_by, item.workset,
                    item.view_name, item.element_id, item.type_id).lower():
                continue
            self.filtered.append(item)
        self.update_grid()

    def on_selection(self, s, e):
        self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)

    def _selected_ids(self):
        ids = List[ElementId]()
        for item in self.dataGrid.SelectedItems:
            ids.Add(ElementId(item.element_id))
        return ids

    def _cell_under(self, source):
        """Walk up the visual tree from a click's OriginalSource to find the
        DataGridCell it landed in, so double-click can behave differently
        for the ID column than for the rest of the row."""
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

    def _copy_to_clipboard(self, text):
        text = str(text)
        try:
            from System.Windows import Clipboard
            Clipboard.SetText(text)
        except Exception:
            try:
                from System.Windows.Forms import Clipboard as WFClipboard
                WFClipboard.SetText(text)
            except Exception as ex:
                forms.alert("Could not copy ID to clipboard: {}".format(ex),
                            title="DQT - CAD Import Manager")

    def on_double_click(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            return
        item = self.dataGrid.SelectedItem
        cell = self._cell_under(e.OriginalSource)
        if cell is not None:
            if cell.Column is self.colId:
                self._copy_to_clipboard(item.element_id)
                return
            if cell.Column is self.colTypeId:
                self._copy_to_clipboard(item.type_id)
                return
        self._navigate_and_select([item])

    def select_all(self, s, e):
        self.dataGrid.SelectAll()

    def select_none(self, s, e):
        self.dataGrid.UnselectAll()

    def refresh(self, s, e):
        self.load_data()
        self.on_filter(None, None)
        self.txtTotal.Text = str(len(self.items))
        self.txtImports.Text = str(len([i for i in self.items if i.link_type.startswith("Import")]))
        self.txtLinks.Text = str(len([i for i in self.items if i.link_type.startswith("Link")]))
        self.txtUnusedTypes.Text = str(len(self.unused_types))
        self._update_warning_banner()

    def select_in_model(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one CAD file first.", title="DQT - CAD Import Manager")
            return
        try:
            self.uidoc.Selection.SetElementIds(self._selected_ids())
        except Exception as ex:
            forms.alert(str(ex), title="DQT - CAD Import Manager")

    def zoom_to(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one CAD file first.", title="DQT - CAD Import Manager")
            return
        self._navigate_and_select([item for item in self.dataGrid.SelectedItems])

    def _navigate_and_select(self, items):
        """Select the given rows and, where possible, switch straight to a
        view that actually contains them, instead of asking Revit to search
        for one.

        UIDocument.ShowElements pops Revit's OWN native "No good view could
        be found" Task Dialog for an element it cannot resolve a view for -
        that dialog is not a catchable managed exception, so wrapping
        ShowElements in try/except does nothing to stop it. The two things
        that actually trigger it here are handled directly instead:
          - a CAD Link whose external file is unloaded/missing has no
            geometry anywhere to zoom to - that is flagged up front via
            link_type (see _link_status_suffix) and ShowElements is never
            called for it.
          - a single element placed into one specific view is shown by
            switching the active view to it directly, which always
            succeeds and needs no search at all.
        Anything else still goes through ShowElements as before - that path
        was not reported broken, and this only narrows the failure mode
        this was written for."""
        ids = List[ElementId]()
        for item in items:
            ids.Add(ElementId(item.element_id))

        try:
            self.uidoc.Selection.SetElementIds(ids)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - CAD Import Manager")
            return

        broken = [i for i in items if i.link_type.startswith("Link (")]
        ok_items = [i for i in items if i not in broken]

        if len(ok_items) == 1:
            item = ok_items[0]
            el = self.doc.GetElement(ElementId(item.element_id))
            owner_id = None
            try:
                owner_id = el.OwnerViewId if el else None
            except:
                owner_id = None
            if owner_id is not None and _eid_int(owner_id) > 0:
                owner_view = self.doc.GetElement(owner_id)
                if owner_view is not None:
                    try:
                        self.uidoc.ActiveView = owner_view
                        self.uidoc.Selection.SetElementIds(ids)
                        self.uidoc.RefreshActiveView()
                    except:
                        pass
                    if broken:
                        self._warn_unreachable(broken)
                    return

        if ok_items:
            ok_ids = List[ElementId]()
            for item in ok_items:
                ok_ids.Add(ElementId(item.element_id))
            try:
                self.uidoc.ShowElements(ok_ids)
            except:
                pass

        if broken:
            self._warn_unreachable(broken)

    def _warn_unreachable(self, broken):
        lines = ["{} - {}".format(i.name, i.link_type) for i in broken[:8]]
        more = "" if len(broken) <= 8 else "\n... and {} more".format(len(broken) - 8)
        forms.alert(
            "Selected, but Revit has no geometry to zoom to for {} CAD "
            "link(s) that are not currently loaded:\n\n{}{}\n\n"
            "Reload them from Manage Links first if you need to see "
            "them.".format(len(broken), "\n".join(lines), more),
            title="DQT - CAD Import Manager")

    def export_csv(self, s, e):
        current_items = [item for item in self.dataGrid.Items]
        if not current_items:
            forms.alert("No data to export.", title="DQT - CAD Import Manager")
            return

        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "CSV Files|*.csv"
        dlg.FileName = "CADImports_{}.csv".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

        if dlg.ShowDialog() == DialogResult.OK:
            try:
                with codecs.open(dlg.FileName, 'w', 'utf-8-sig') as f:
                    f.write("ID,Type ID,File Name,Type,Created By,Workset,View,Level\n")
                    for item in current_items:
                        f.write('{},{},"{}",{},{},{},"{}",{}\n'.format(
                            item.element_id, item.type_id,
                            item.name.replace('"', '""'),
                            item.link_type, item.created_by, item.workset,
                            item.view_name.replace('"', '""'), item.level))
                forms.alert("Exported {} row(s).".format(len(current_items)),
                            title="DQT - CAD Import Manager")
            except Exception as ex:
                forms.alert(str(ex), title="DQT - CAD Import Manager")

    def purge_unused_types(self, s, e):
        """Delete every CADLinkType with zero remaining instances - the
        orphans _get_unused_cad_types finds, left behind by deleting
        instances one at a time instead of via "Select All Instances"
        on the Type itself. This is the direct fix for "I deleted every
        instance but ACC's Model Analytics still reports this CAD
        import" - Insight reports at the Type level, so the orphaned
        Type has to go too, not just its instances."""
        unused = _get_unused_cad_types(self.doc)
        if not unused:
            forms.alert(
                "No unused CAD types found - every CAD Import/Link type "
                "in this model still has at least one instance.",
                title="DQT - CAD Import Manager")
            return

        names = [_cad_type_type_name(self.doc, t) for t in unused]
        lines = names[:10]
        more = "" if len(names) <= 10 else "\n... and {} more".format(len(names) - 10)
        msg = (
            "Found {} unused CAD type(s) - each still exists as an "
            "orphaned Type with zero instances left in the model. This is "
            "exactly why ACC's Model Analytics can keep reporting a CAD "
            "import as present even after every instance was deleted - it "
            "reports at the Type level, and Revit never auto-deletes a "
            "Type just because its instance count reaches zero.\n\n"
            "Delete them now?\n\n{}{}").format(len(unused), "\n".join(lines), more)

        if not forms.alert(msg, title="DQT - CAD Import Manager: Purge Unused Types",
                           yes=True, no=True):
            return

        deleted = 0
        failed = []
        try:
            with revit.Transaction("DQT - Purge Unused CAD Types"):
                for cad_type in unused:
                    try:
                        self.doc.Delete(cad_type.Id)
                        deleted += 1
                    except Exception as ex:
                        failed.append("{} - {}".format(
                            _cad_type_type_name(self.doc, cad_type), ex))
        except Exception as ex:
            failed.append("transaction failed: {}".format(ex))

        result = "Purged {} of {} unused CAD type(s).".format(deleted, len(unused))
        if failed:
            lines2 = failed[:8]
            more2 = "" if len(failed) <= 8 else "\n... and {} more".format(len(failed) - 8)
            result += "\n\nCould not delete:\n{}{}".format("\n".join(lines2), more2)
        forms.alert(result, title="DQT - CAD Import Manager")

        self.refresh(s, e)

    def delete_selected(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one CAD file first.", title="DQT - CAD Import Manager")
            return

        selected = [item for item in self.dataGrid.SelectedItems]
        count = len(selected)
        imports_n = len([i for i in selected if i.link_type.startswith("Import")])
        links_n = len([i for i in selected if i.link_type.startswith("Link")])

        msg = ("Delete {} CAD file(s) from this model?\n\n"
               "{} Import(s), {} Link(s)\n\n"
               "Any Type left with zero instances afterward is purged "
               "automatically in the same step, so nothing orphaned is "
               "left behind for ACC's Model Analytics to keep reporting.\n\n"
               "This removes them from the model - Undo (Ctrl+Z) restores "
               "them right after if needed.").format(count, imports_n, links_n)
        if not forms.alert(msg, title="DQT - CAD Import Manager: Confirm Delete",
                           yes=True, no=True):
            return

        deleted, failed, purged_types = self._delete_items(selected)

        result = "Deleted {} of {} CAD file(s).".format(deleted, count)
        if purged_types:
            result += "\nAlso purged {} Type(s) left with zero instances.".format(purged_types)
        if failed:
            lines = failed[:8]
            more = "" if len(failed) <= 8 else "\n... and {} more".format(len(failed) - 8)
            result += "\n\nCould not delete:\n{}{}".format("\n".join(lines), more)
        forms.alert(result, title="DQT - CAD Import Manager")

        self.refresh(s, e)

    def _delete_items(self, items):
        """Delete these CAD import elements in one transaction, then purge
        any Type left with zero instances as a direct result. Returns
        (deleted_count, failure_descriptions, purged_type_count).

        Each instance is deleted individually inside the same transaction,
        rather than as one batch, so a single element Revit refuses to
        delete (a pinned one, say) does not stop the rest from going -
        matching how the rest of this suite treats a bad element as a
        per-item failure, not a reason to abandon the whole operation.
        The Type each deleted instance belonged to is tracked before the
        delete, then checked afterward - a Type only gets removed here if
        NONE of its instances survive, so a Type still used by an
        instance the user did not select is left untouched."""
        deleted = 0
        failed = []
        purged_types = 0
        try:
            with revit.Transaction("DQT - Delete CAD Import(s)"):
                type_ids_touched = set()
                for item in items:
                    try:
                        type_ids_touched.add(_eid_int(item.element.GetTypeId()))
                    except:
                        pass
                    try:
                        self.doc.Delete(ElementId(item.element_id))
                        deleted += 1
                    except Exception as ex:
                        failed.append("{} (ID {}) - {}".format(
                            item.name, item.element_id, ex))

                if type_ids_touched:
                    still_used = set()
                    try:
                        for inst in FilteredElementCollector(self.doc).OfClass(ImportInstance) \
                                .WhereElementIsNotElementType():
                            try:
                                still_used.add(_eid_int(inst.GetTypeId()))
                            except:
                                continue
                    except:
                        pass
                    for tid in type_ids_touched:
                        if tid in still_used:
                            continue
                        try:
                            self.doc.Delete(ElementId(tid))
                            purged_types += 1
                        except:
                            pass
        except Exception as ex:
            failed.append("transaction failed: {}".format(ex))
        return deleted, failed, purged_types

    def close_window(self, s, e):
        self.Close()

    def on_help(self, s, e):
        if _open_help_page("cad_import_manager.html"):
            return
        forms.alert(
            "CAD Import Manager\n\n"
            "Lists every CAD file imported or linked into the model, with "
            "its creator, workset, host level and the view it was placed "
            "into - so a stray or oversized CAD file can be found without "
            "hunting through every view.\n\n"
            "STAT CARDS\n"
            "  TOTAL         - CAD ImportInstance elements found\n"
            "  IMPORTS       - imported (not linked) files\n"
            "  LINKS         - linked files\n"
            "  SELECTED      - rows currently selected in the grid\n"
            "  UNUSED TYPES  - CAD Import/Link Types with zero instances left\n\n"
            "COLUMNS\n"
            "  ID      - the placed instance's own Element ID\n"
            "  Type ID - the CAD Type's Element ID, shared by every\n"
            "            instance of that file. This is the ID ACC's\n"
            "            Model Analytics reports, so paste it into\n"
            "            Search to find that file's instances here.\n\n"
            "WORKFLOW\n"
            "  Search matches name, creator, workset, view, ID or Type ID.\n"
            "  Double-click ID or Type ID to copy it; double-click "
            "elsewhere on a row to select + zoom to that file.\n"
            "  Select in Model / Zoom To act on the checked rows.\n"
            "  Export CSV saves the visible list.\n"
            "  Delete removes the selected CAD elements from the model - "
            "any Type left with zero instances afterward is purged "
            "automatically in the same step.\n"
            "  Purge Unused Types finds and deletes every CAD Type with "
            "zero instances left, even ones this tool did not just delete "
            "(e.g. left over from deleting instances one at a time before "
            "this feature existed).\n\n"
            "WHY A CAD IMPORT MIGHT BE MISSING HERE\n"
            "  This tool can only see elements this Revit session has "
            "actually loaded. A CAD import/link on a workset you closed "
            "when opening the model is invisible to it - and to every "
            "other in-session tool - even though ACC's Model Analytics "
            "(Insight) still finds it, since that reads the whole file "
            "server-side regardless of any user's open-workset choice. "
            "The orange banner above the stat cards names which "
            "worksets are closed when that's the case; reopen the model "
            "with all worksets open to see the complete list.\n\n"
            "WHY ACC STILL REPORTS A CAD IMPORT YOU ALREADY DELETED\n"
            "  ACC's Model Analytics reports CAD imports at the TYPE "
            "level (one entry per unique CAD file), not per instance. "
            "Deleting every instance does not delete the Type itself - "
            "Revit never auto-purges a Type just because its instance "
            "count reaches zero - so an orphaned Type keeps showing up "
            "in ACC until it, not just its instances, is deleted. Use "
            "Purge Unused Types here, then Sync/upload a new version and "
            "wait for ACC to reprocess it.\n"
            "  If UNUSED TYPES reads 0 and ACC still lists the file, the "
            "file is genuinely still in the model: match ACC's Element ID "
            "against the Type ID column to see its remaining instances, "
            "delete those, and the Type is purged with them.",
            title="CAD Import Manager - Help")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first.", title="DQT - CAD Import Manager")
        else:
            CADImportManagerWindow().ShowDialog()
    except Exception as ex:
        forms.alert("Error: {}".format(str(ex)), title="DQT - CAD Import Manager Error")
