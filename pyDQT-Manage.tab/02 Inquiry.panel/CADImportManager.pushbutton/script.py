# -*- coding: utf-8 -*-
"""CAD Import Manager v1.0
Author: Dang Quoc Truong (DQT)

Lists every CAD file imported or linked into the model (ImportInstance
elements) with its file name, link type, creator, workset, host level and
the view it was placed into, so a stray or oversized CAD file can be found
and selected without hunting through every view.
"""
__title__ = "CAD Import\nManager"
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
class CADImportItem(object):
    def __init__(self):
        self.element_id = 0
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


def _is_linked(doc, elem):
    """True for a CAD Link, False for a CAD Import.

    IsLinked was reported missing on some Revit 2026 builds by this same
    suite's CadtoWall tool, so fall back to reading the type's external file
    reference, which is present either way."""
    try:
        return bool(elem.IsLinked)
    except:
        pass
    try:
        cad_type = doc.GetElement(elem.GetTypeId())
        if cad_type and cad_type.GetExternalFileReference():
            return True
    except:
        pass
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


# ============================================================================
# XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="CAD Import Manager - DQT"
        Height="650" Width="1190"
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
                <TextBlock Text="CAD Import Manager" FontSize="17" FontWeight="Bold"/>
                <TextBlock Text="Imported / linked CAD files in this model - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
            </StackPanel>
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
                <StackPanel><TextBlock Text="TOTAL" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtTotal" Text="0" FontSize="22" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="IMPORTS" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtImports" Text="0" FontSize="22" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="LINKS" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtLinks" Text="0" FontSize="22" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
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
                    <TextBox x:Name="txtSearch" Padding="6,4" Margin="0,0,0,10" ToolTip="Name, creator, workset or view"/>
                    <TextBlock Text="TYPE" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <ComboBox x:Name="cmbFilter" Padding="6,4" Margin="0,0,0,10" SelectedIndex="0">
                        <ComboBoxItem Content="All"/>
                        <ComboBoxItem Content="Import only"/>
                        <ComboBoxItem Content="Link only"/>
                    </ComboBox>
                    <TextBlock Text="Double-click ID to copy it. Double-click elsewhere on a row to select + zoom to that file." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
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
class CADImportManagerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.items = []
        self.filtered = []

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
        self.btnClose.Click += self.close_window

        self.load_data()
        self.update_ui()

    def load_data(self):
        self.items = get_cad_imports(self.doc)
        self.filtered = list(self.items)

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtImports.Text = str(len([i for i in self.items if i.link_type.startswith("Import")]))
        self.txtLinks.Text = str(len([i for i in self.items if i.link_type.startswith("Link")]))
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
            if fi == 1 and not item.link_type.startswith("Import"):
                continue
            if fi == 2 and not item.link_type.startswith("Link"):
                continue
            if search and search not in "{} {} {} {}".format(
                    item.name, item.created_by, item.workset,
                    item.view_name).lower():
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

    def _copy_id(self, item):
        text = str(item.element_id)
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
        if cell is not None and cell.Column is self.colId:
            self._copy_id(item)
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
                    f.write("ID,File Name,Type,Created By,Workset,View,Level\n")
                    for item in current_items:
                        f.write('{},"{}",{},{},{},"{}",{}\n'.format(
                            item.element_id, item.name.replace('"', '""'),
                            item.link_type, item.created_by, item.workset,
                            item.view_name.replace('"', '""'), item.level))
                forms.alert("Exported {} row(s).".format(len(current_items)),
                            title="DQT - CAD Import Manager")
            except Exception as ex:
                forms.alert(str(ex), title="DQT - CAD Import Manager")

    def close_window(self, s, e):
        self.Close()


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
