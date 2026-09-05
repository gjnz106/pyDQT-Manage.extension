# -*- coding: utf-8 -*-
"""Workset Checker v1.0
Author: Dang Quoc Truong (DQT)
Auto-generates one 3D view per workset, isolating that workset (all
other worksets hidden) so each workset can be reviewed independently.
"""
__title__ = "Workset\nChecker"
__author__ = "DQT"

import os
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from pyrevit import revit, forms, script, HOST_APP, DB
from pyrevit.forms import WPFWindow
from pyrevit.compat import get_elementid_value_func
from Autodesk.Revit.DB import *

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
# CONFIGURATION
# ============================================================================
class Config:
    default_prefix = "QC-WS - "
    invalid_view_chars = ['{', '}', '[', ']', '|', ';', '<', '>', '?', '`', '~', '\\', '/', ':']


def sanitize_view_name(name):
    result = name
    for ch in Config.invalid_view_chars:
        result = result.replace(ch, '_')
    result = result.strip()
    return result if result else "Workset"


# ============================================================================
# DATA MODEL
# ============================================================================
class WorksetItem(object):
    def __init__(self, workset):
        self.workset = workset
        self.workset_id = workset.Id.IntegerValue
        self.name = workset.Name
        self.element_count = 0
        self.existing_view = "No"


def get_user_worksets(doc):
    collector = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
    return sorted(list(collector), key=lambda w: w.Name.lower())


def find_view3d_by_name(doc, name):
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if not v.IsTemplate and v.Name == name:
                return v
        except:
            continue
    return None


def unique_view_name(doc, base_name):
    existing = set()
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            existing.add(v.Name)
        except:
            continue
    name = base_name
    i = 2
    while name in existing:
        name = "{0} ({1})".format(base_name, i)
        i += 1
    return name


def get_default_3d_view_family_type_id(doc):
    try:
        type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewType3D)
        if type_id and _eid_int(type_id) > 0:
            return type_id
    except:
        pass
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if vft.ViewFamily == ViewFamily.ThreeDimensional:
                return vft.Id
        except:
            continue
    return None


def get_workset_items(doc, prefix):
    items = []
    for ws in get_user_worksets(doc):
        item = WorksetItem(ws)
        try:
            f = ElementWorksetFilter(ws.Id, False)
            item.element_count = FilteredElementCollector(doc).WherePasses(f).WhereElementIsNotElementType().GetElementCount()
        except:
            item.element_count = 0
        base_name = sanitize_view_name(prefix + ws.Name)
        item.existing_view = "Yes" if find_view3d_by_name(doc, base_name) else "No"
        items.append(item)
    return items


def apply_workset_isolation(view, target_ws_id, all_worksets):
    for ws in all_worksets:
        try:
            vis = WorksetVisibility.Visible if ws.Id == target_ws_id else WorksetVisibility.Hidden
            view.SetWorksetVisibility(ws.Id, vis)
        except:
            pass


def generate_view_for_workset(doc, workset, all_worksets, prefix, reuse_existing, apply_display):
    base_name = sanitize_view_name(prefix + workset.Name)
    existing_view3d = find_view3d_by_name(doc, base_name) if reuse_existing else None

    if existing_view3d:
        view = existing_view3d
        created = False
    else:
        final_name = unique_view_name(doc, base_name)
        vft_id = get_default_3d_view_family_type_id(doc)
        if not vft_id:
            raise Exception("No default 3D view type found in this project.")
        view = View3D.CreateIsometric(doc, vft_id)
        view.Name = final_name
        created = True

    apply_workset_isolation(view, workset.Id, all_worksets)

    if apply_display:
        try:
            view.DetailLevel = ViewDetailLevel.Fine
        except:
            pass
        try:
            view.DisplayStyle = DisplayStyle.ShadingWithEdges
        except:
            pass

    return view, created


# ============================================================================
# XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Workset Checker - DQT"
        Height="700" Width="1000"
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
                    <TextBlock Text="Workset Checker" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="Auto-generate QC views per workset - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
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
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
                <StackPanel><TextBlock Text="TOTAL WORKSETS" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtTotal" Text="0" FontSize="22" FontWeight="Bold"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0">
                <StackPanel><TextBlock Text="SELECTED" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtSelected" Text="0" FontSize="22" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
                <StackPanel><TextBlock Text="EXISTING VIEWS" FontSize="9" Foreground="#666"/><TextBlock x:Name="txtExisting" Text="0" FontSize="22" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
            </Border>
        </Grid>

        <!-- Content -->
        <Grid Grid.Row="2">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="230"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- Left options panel -->
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10" Margin="0,0,8,0">
                <StackPanel>
                    <TextBlock Text="OPTIONS" FontSize="9" FontWeight="SemiBold" Foreground="#666" Margin="0,0,0,8"/>
                    <TextBlock Text="View name prefix" FontSize="10" Margin="0,0,0,3"/>
                    <TextBox x:Name="txtPrefix" Padding="6,4" Margin="0,0,0,12" Text="QC-WS - "/>
                    <CheckBox x:Name="chkDisplay" IsChecked="True" Margin="0,0,0,8">
                        <TextBlock Text="Detail: Fine + Shaded w/ Edges" TextWrapping="Wrap"/>
                    </CheckBox>
                    <CheckBox x:Name="chkReuse" IsChecked="True" Margin="0,0,0,8">
                        <TextBlock Text="Reuse view if name matches" TextWrapping="Wrap"/>
                    </CheckBox>
                    <CheckBox x:Name="chkOpenFirst" IsChecked="True" Margin="0,0,0,8">
                        <TextBlock Text="Open first view when done" TextWrapping="Wrap"/>
                    </CheckBox>
                    <TextBlock Text="Each generated view turns ON exactly one workset and turns OFF every other workset." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,10,0,0"/>
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
                    <DataGridTextColumn Header="Workset" Binding="{Binding name}" Width="*" SortMemberPath="name"/>
                    <DataGridTextColumn Header="Elements" Binding="{Binding element_count}" Width="120" SortMemberPath="element_count"/>
                    <DataGridTextColumn Header="Existing View" Binding="{Binding existing_view}" Width="110" SortMemberPath="existing_view"/>
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
                    <Button x:Name="btnGenerate" Content="Generate Views" Padding="14,5" Margin="2" Background="#F0CC88" FontWeight="SemiBold"/>
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
class WorksetCheckerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.items = []

        self.dataGrid.SelectionChanged += self.on_selection
        self.txtPrefix.TextChanged += self.on_prefix_changed

        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnRefresh.Click += self.refresh
        self.btnGenerate.Click += self.on_generate
        self.btnClose.Click += self.close_window
        self.btnHelp.Click += self.on_help

        self.load_data()
        self.update_ui()

    def get_prefix(self):
        return self.txtPrefix.Text if self.txtPrefix.Text else Config.default_prefix

    def load_data(self):
        self.items = get_workset_items(self.doc, self.get_prefix())

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        existing_count = len([i for i in self.items if i.existing_view == "Yes"])
        self.txtExisting.Text = str(existing_count)

        self.dataGrid.Items.Clear()
        for item in self.items:
            self.dataGrid.Items.Add(item)

        self.dataGrid.SelectAll()
        self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)

    def on_selection(self, s, e):
        self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)

    def on_prefix_changed(self, s, e):
        prefix = self.get_prefix()
        for item in self.items:
            base_name = sanitize_view_name(prefix + item.name)
            item.existing_view = "Yes" if find_view3d_by_name(self.doc, base_name) else "No"
        self.dataGrid.Items.Refresh()
        existing_count = len([i for i in self.items if i.existing_view == "Yes"])
        self.txtExisting.Text = str(existing_count)

    def select_all(self, s, e):
        self.dataGrid.SelectAll()

    def select_none(self, s, e):
        self.dataGrid.UnselectAll()

    def refresh(self, s, e):
        self.load_data()
        self.update_ui()

    def on_generate(self, s, e):
        selected = [item for item in self.dataGrid.SelectedItems]
        if not selected:
            forms.alert("Select at least one workset to generate views for.", title="DQT - Workset Checker")
            return

        prefix = self.get_prefix()
        apply_display = self.chkDisplay.IsChecked
        reuse = self.chkReuse.IsChecked
        open_first = self.chkOpenFirst.IsChecked

        all_worksets = get_user_worksets(self.doc)

        created_count = 0
        updated_count = 0
        errors = []
        first_view = None

        try:
            with revit.Transaction("DQT - Generate Workset QC Views"):
                for item in selected:
                    try:
                        view, created = generate_view_for_workset(
                            self.doc, item.workset, all_worksets, prefix, reuse, apply_display)
                        if first_view is None:
                            first_view = view
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1
                    except Exception as ex:
                        errors.append("{0}: {1}".format(item.name, str(ex)))
        except Exception as ex:
            forms.alert("Error generating views: {0}".format(str(ex)), title="DQT - Workset Checker")
            return

        msg = "Created: {0}\nUpdated: {1}".format(created_count, updated_count)
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                msg += "\n... and {0} more".format(len(errors) - 5)
        forms.alert(msg, title="DQT - Workset Checker: Result")

        if open_first and first_view is not None:
            try:
                self.uidoc.ActiveView = first_view
            except:
                pass

        self.load_data()
        self.update_ui()

    def close_window(self, s, e):
        self.Close()

    def on_help(self, s, e):
        if _open_help_page("workset_checker.html"):
            return
        forms.alert(
            "Workset Checker\n\n"
            "Generates one 3D view per selected workset, isolating it - "
            "every other workset is hidden - so it can be reviewed on its "
            "own.\n\n"
            "STAT CARDS\n"
            "  TOTAL WORKSETS  - user worksets in this model\n"
            "  SELECTED        - rows currently selected in the grid\n"
            "  EXISTING VIEWS  - how many already have a matching QC view\n\n"
            "WORKFLOW\n"
            "  1. Set the view name Prefix and the options on the left\n"
            "  2. Select the worksets to generate views for\n"
            "  3. Generate Views - reruns update the existing view instead "
            "of duplicating it, when Reuse is on\n\n"
            "Only available on workshared models.",
            title="Workset Checker - Help")


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first.", title="Workset Checker")
        elif not revit.doc.IsWorkshared:
            forms.alert(
                "This project does not have worksharing enabled.\n"
                "Worksets are only available in workshared models.",
                title="Workset Checker")
        else:
            WorksetCheckerWindow().ShowDialog()
    except Exception as ex:
        forms.alert("Error: {0}".format(str(ex)), title="Workset Checker Error")
