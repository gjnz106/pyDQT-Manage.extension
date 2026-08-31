# -*- coding: utf-8 -*-
"""Image Manager v1.0
Author: Dang Quoc Truong (DQT)

Lists every raster Image placed into the model (ImageInstance elements)
with its name, source file path, whether that file can still be found on
disk, creator, workset, host level and the view it was placed into, so a
stray, oversized or broken-link image can be found and selected without
hunting through every view.
"""
__title__ = "Image\nManager"
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
import os

get_elementid_value = get_elementid_value_func()


def _eid_int(eid):
    """Get integer value from ElementId - compatible with Revit 2024-2026"""
    if eid is None:
        return -1
    return get_elementid_value(eid)


# ============================================================================
# DATA MODEL
# ============================================================================
class ImageItem(object):
    def __init__(self):
        self.element_id = 0
        self.name = "<Unnamed>"
        self.status = "-"          # "OK" / "Missing File" / "No Path"
        self.source_path = "-"
        self.created_by = "-"
        self.workset = "-"
        self.level = "-"
        self.view_name = "-"
        self.element = None


def _image_type_name(doc, elem):
    """The image's display name, tried in the order this codebase's CAD
    Import Manager already relies on for the equivalent lookup on an
    ImportInstance's type: Element.Name on the type is the version-stable
    route, LookupParameter and the raw Id are fallbacks."""
    img_type = None
    try:
        img_type = doc.GetElement(elem.GetTypeId())
    except:
        pass
    if img_type:
        try:
            val = DB.Element.Name.GetValue(img_type)
            if val:
                return val
        except:
            pass
        try:
            p = img_type.LookupParameter("Name")
            if p and p.HasValue:
                val = p.AsString()
                if val:
                    return val
        except:
            pass
        try:
            if img_type.Name:
                return img_type.Name
        except:
            pass

    return "<Unnamed> (ID {})".format(_eid_int(elem.Id))


def _image_source_path(doc, elem):
    """The external raster file this image was placed from, or "" when it
    cannot be determined. Tried through every route this Revit version
    might expose it via, oldest API surface last:
      1) ImageType.GetImageTypeSettings().SourcePath - the documented,
         current way to read it.
      2) ImageType.Path - older API some Revit builds still carry.
      3) a LookupParameter literally named "Path"/"Source Path", in case
         a future/older build exposes it that way instead.
    Never raises - an image whose path cannot be determined is reported
    as "" rather than failing the whole row."""
    img_type = None
    try:
        img_type = doc.GetElement(elem.GetTypeId())
    except:
        pass
    if not img_type:
        return ""

    try:
        settings = img_type.GetImageTypeSettings()
        if settings and settings.SourcePath:
            return settings.SourcePath
    except:
        pass

    try:
        if img_type.Path:
            return img_type.Path
    except:
        pass

    try:
        for pname in ("Path", "Source Path", "Image Path"):
            p = img_type.LookupParameter(pname)
            if p and p.HasValue:
                val = p.AsString()
                if val:
                    return val
    except:
        pass

    return ""


def _file_status(path):
    """"OK" when the source file exists on disk right now, "Missing File"
    when a path is known but not reachable, "No Path" when no path could
    be determined at all. A network path or a path on a drive this Revit
    session cannot see reports the same as truly missing - that matches
    what Revit's own broken-image indicator means to the user."""
    if not path:
        return "No Path"
    try:
        if os.path.exists(path):
            return "OK"
    except:
        pass
    return "Missing File"


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
    """Best-effort host level for a placed image.

    ImageInstance carries no dedicated LevelId property, so this tries
    every route Revit exposes one through instead of relying on a single
    parameter name that might not exist on every Revit build:
      1) an instance parameter literally named "Level".
      2) the level of the view it was placed into, when that view is
         plan-based.
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
    """The view this image was placed into. An Image is always placed into
    one specific view (unlike a CAD import, it has no "all views" option),
    but this still falls back to "-" rather than raising if a future Revit
    build ever leaves OwnerViewId invalid."""
    try:
        owner_id = elem.OwnerViewId
        if owner_id is not None and _eid_int(owner_id) > 0:
            view = doc.GetElement(owner_id)
            name = getattr(view, "Name", None) if view else None
            if name:
                return name
    except:
        pass
    return "-"


def get_images(doc):
    items = []
    collector = FilteredElementCollector(doc).OfClass(ImageInstance) \
        .WhereElementIsNotElementType()
    for elem in collector:
        try:
            item = ImageItem()
            item.element = elem
            item.element_id = _eid_int(elem.Id)
            item.name = _image_type_name(doc, elem)
            path = _image_source_path(doc, elem)
            item.source_path = path if path else "-"
            item.status = _file_status(path)
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
        Title="Image Manager - DQT"
        Height="650" Width="1220"
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
                    <TextBlock Text="Image Manager" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="Raster images placed in this model - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
                </StackPanel>
                <Button x:Name="btnHelp" Content="? Help" Padding="10,4" Background="White" HorizontalAlignment="Right"/>
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
                <StackPanel><TextBlock Text="TOTAL" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtTotal" Text="0" FontSize="22" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="FOUND" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtFound" Text="0" FontSize="22" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="MISSING" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtMissing" Text="0" FontSize="22" FontWeight="Bold" Foreground="#FF6B6B"/></StackPanel>
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
                    <TextBox x:Name="txtSearch" Padding="6,4" Margin="0,0,0,10" ToolTip="Name, path, creator, workset or view"/>
                    <TextBlock Text="STATUS" FontSize="9" FontWeight="SemiBold" Margin="0,0,0,4"/>
                    <ComboBox x:Name="cmbFilter" Padding="6,4" Margin="0,0,0,10" SelectedIndex="0">
                        <ComboBoxItem Content="All"/>
                        <ComboBoxItem Content="Found only"/>
                        <ComboBoxItem Content="Missing only"/>
                    </ComboBox>
                    <TextBlock Text="Double-click ID to copy it. Double-click elsewhere on a row to select + zoom to that image." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
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
                    <DataGridTextColumn Header="Name" Binding="{Binding name}" Width="160" SortMemberPath="name"/>
                    <DataGridTextColumn Header="Status" Binding="{Binding status}" Width="90" SortMemberPath="status"/>
                    <DataGridTextColumn Header="Source Path" Binding="{Binding source_path}" Width="*" SortMemberPath="source_path"/>
                    <DataGridTextColumn Header="Created By" Binding="{Binding created_by}" Width="110" SortMemberPath="created_by"/>
                    <DataGridTextColumn Header="Workset" Binding="{Binding workset}" Width="110" SortMemberPath="workset"/>
                    <DataGridTextColumn Header="View" Binding="{Binding view_name}" Width="150" SortMemberPath="view_name"/>
                    <DataGridTextColumn Header="Level" Binding="{Binding level}" Width="90" SortMemberPath="level"/>
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
                    <Button x:Name="btnDelete" Content="Delete" Padding="10,5" Margin="2" Background="#FF6B6B" Foreground="White"/>
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
class ImageManagerWindow(WPFWindow):
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
        self.btnDelete.Click += self.delete_selected
        self.btnClose.Click += self.close_window
        self.btnHelp.Click += self.on_help

        self.load_data()
        self.update_ui()

    def load_data(self):
        self.items = get_images(self.doc)
        self.filtered = list(self.items)

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtFound.Text = str(len([i for i in self.items if i.status == "OK"]))
        self.txtMissing.Text = str(len([i for i in self.items if i.status != "OK"]))
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
            if fi == 1 and item.status != "OK":
                continue
            if fi == 2 and item.status == "OK":
                continue
            if search and search not in "{} {} {} {} {}".format(
                    item.name, item.source_path, item.created_by,
                    item.workset, item.view_name).lower():
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
                            title="DQT - Image Manager")

    def on_double_click(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            return
        item = self.dataGrid.SelectedItem
        cell = self._cell_under(e.OriginalSource)
        if cell is not None and cell.Column is self.colId:
            self._copy_id(item)
            return
        self._navigate_and_select([item])

    def on_help(self, s, e):
        forms.alert(
            "Image Manager\n\n"
            "- Search filters by name, path, creator, workset or view; "
            "Status narrows to Found/Missing.\n"
            "- Status is checked against disk right now: Missing File means "
            "the source raster can't be found at its recorded path (moved, "
            "renamed, or on an unreachable drive); No Path means Revit "
            "couldn't report one at all.\n"
            "- Select in Model / Zoom To act on the ticked rows. A missing "
            "image still has a placeholder in its view, so both still work.\n"
            "- Delete removes the selected image instance(s) - Undo restores "
            "them right after if needed.\n"
            "- To fix a Missing image, use Revit's own Manage tab > Manage "
            "Images to browse to the file's new location.\n\n"
            "Dang Quoc Truong - DQT (c) 2026",
            title="DQT - Image Manager")

    def select_all(self, s, e):
        self.dataGrid.SelectAll()

    def select_none(self, s, e):
        self.dataGrid.UnselectAll()

    def refresh(self, s, e):
        self.load_data()
        self.on_filter(None, None)
        self.txtTotal.Text = str(len(self.items))
        self.txtFound.Text = str(len([i for i in self.items if i.status == "OK"]))
        self.txtMissing.Text = str(len([i for i in self.items if i.status != "OK"]))

    def select_in_model(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one image first.", title="DQT - Image Manager")
            return
        try:
            self.uidoc.Selection.SetElementIds(self._selected_ids())
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Image Manager")

    def zoom_to(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one image first.", title="DQT - Image Manager")
            return
        self._navigate_and_select([item for item in self.dataGrid.SelectedItems])

    def _navigate_and_select(self, items):
        """Select the given rows and switch straight to a view that
        contains them where possible, instead of asking Revit to search
        for one.

        Unlike an unloaded CAD link, an image with a missing source file
        still has a real placeholder in its owning view - the element and
        its placement exist in the model either way - so every image here
        can be zoomed to, and there is no "no good view" case to guard
        against."""
        ids = List[ElementId]()
        for item in items:
            ids.Add(ElementId(item.element_id))

        try:
            self.uidoc.Selection.SetElementIds(ids)
        except Exception as ex:
            forms.alert(str(ex), title="DQT - Image Manager")
            return

        if len(items) == 1:
            item = items[0]
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
                    return

        try:
            self.uidoc.ShowElements(ids)
        except:
            pass

    def export_csv(self, s, e):
        current_items = [item for item in self.dataGrid.Items]
        if not current_items:
            forms.alert("No data to export.", title="DQT - Image Manager")
            return

        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "CSV Files|*.csv"
        dlg.FileName = "ImageManager_{}.csv".format(
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))

        if dlg.ShowDialog() == DialogResult.OK:
            try:
                with codecs.open(dlg.FileName, 'w', 'utf-8-sig') as f:
                    f.write("ID,Name,Status,Source Path,Created By,Workset,View,Level\n")
                    for item in current_items:
                        f.write('{},"{}",{},"{}",{},{},"{}",{}\n'.format(
                            item.element_id, item.name.replace('"', '""'),
                            item.status, item.source_path.replace('"', '""'),
                            item.created_by, item.workset,
                            item.view_name.replace('"', '""'), item.level))
                forms.alert("Exported {} row(s).".format(len(current_items)),
                            title="DQT - Image Manager")
            except Exception as ex:
                forms.alert(str(ex), title="DQT - Image Manager")

    def delete_selected(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select at least one image first.", title="DQT - Image Manager")
            return

        selected = [item for item in self.dataGrid.SelectedItems]
        count = len(selected)
        missing_n = len([i for i in selected if i.status != "OK"])

        msg = "Delete {} image(s) from this model?".format(count)
        if missing_n:
            msg += "\n\n{} of them already have a missing source file.".format(missing_n)
        msg += ("\n\nThis removes them from the model - Undo (Ctrl+Z) restores "
                "them right after if needed.")
        if not forms.alert(msg, title="DQT - Image Manager: Confirm Delete",
                           yes=True, no=True):
            return

        deleted, failed = self._delete_items(selected)

        result = "Deleted {} of {} image(s).".format(deleted, count)
        if failed:
            lines = failed[:8]
            more = "" if len(failed) <= 8 else "\n... and {} more".format(len(failed) - 8)
            result += "\n\nCould not delete:\n{}{}".format("\n".join(lines), more)
        forms.alert(result, title="DQT - Image Manager")

        self.refresh(s, e)

    def _delete_items(self, items):
        """Delete these image elements in one transaction. Returns
        (deleted_count, failure_descriptions).

        Each element is deleted individually inside the same transaction,
        rather than as one batch, so a single element Revit refuses to
        delete (a pinned one, say) does not stop the rest from going -
        matching how the rest of this suite treats a bad element as a
        per-item failure, not a reason to abandon the whole operation."""
        deleted = 0
        failed = []
        try:
            with revit.Transaction("DQT - Delete Image(s)"):
                for item in items:
                    try:
                        self.doc.Delete(ElementId(item.element_id))
                        deleted += 1
                    except Exception as ex:
                        failed.append("{} (ID {}) - {}".format(
                            item.name, item.element_id, ex))
        except Exception as ex:
            failed.append("transaction failed: {}".format(ex))
        return deleted, failed

    def close_window(self, s, e):
        self.Close()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first.", title="DQT - Image Manager")
        else:
            ImageManagerWindow().ShowDialog()
    except Exception as ex:
        forms.alert("Error: {}".format(str(ex)), title="DQT - Image Manager Error")
