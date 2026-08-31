# -*- coding: utf-8 -*-
"""
Legend Manager v1.0

Lists every Legend view in the project - how many elements are drawn inside
it and which sheets it's placed on. A Legend is the one view type Revit
lets you place on more than one sheet at once, which normally means
dragging it onto each sheet by hand; this adds a batch "Place on Sheets"
step, plus the usual Search / Rename / Duplicate / Delete.

Compatible with Revit 2024, 2025, 2026, 2027

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "Legend\nManager"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "List Legend views, see their sheet placements, and manage them - by DQT"

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

# pyrevit.forms must be imported before anything from System.Windows -
# it is what actually loads WindowsBase/PresentationCore into the CLR in
# pyRevit's IronPython engine. Importing RoutedEventHandler first (as an
# earlier version of this file did) raised "Cannot import name
# RoutedEventHandler" on Revit 2026, because the assembly it lives in
# (WindowsBase) was not loaded yet at that point.
from pyrevit import revit, forms, script
from pyrevit.forms import WPFWindow

import System
from System.Windows import RoutedEventHandler
from System.Windows.Controls import CheckBox
from System.Collections.ObjectModel import ObservableCollection

import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewType, ViewSheet, Viewport,
    ViewDuplicateOption, ElementId, XYZ, Transaction, TransactionGroup
)

import codecs
import os
import sys

# Shared batch rename dialog (extension lib/). Imported softly: it powers one
# button, so a broken install should not stop the whole manager from opening -
# the button reports it instead. Matches the pattern Dimension Manager and
# Wall Layer Manager already use for the same shared dialog.
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


def _eid_int(eid):
    """Get integer value of an ElementId across Revit 2024-2027."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


# ============================================================================
# DATA GATHERING
# ============================================================================

def get_legend_views(document):
    """All non-template Legend views."""
    views = []
    for v in FilteredElementCollector(document).OfClass(View):
        try:
            if v.IsTemplate:
                continue
            if v.ViewType == ViewType.Legend:
                views.append(v)
        except Exception:
            continue
    return views


def get_viewports_by_view(document):
    """dict: legend view's integer ElementId -> list of Viewport elements
    placing that view on a sheet."""
    result = {}
    for vp in FilteredElementCollector(document).OfClass(Viewport):
        try:
            key = _eid_int(vp.ViewId)
        except Exception:
            continue
        result.setdefault(key, []).append(vp)
    return result


def get_all_sheets(document):
    sheets = []
    for s in FilteredElementCollector(document).OfClass(ViewSheet):
        sheets.append(s)
    sheets.sort(key=lambda s: (_safe_attr(s, "SheetNumber"), _safe_attr(s, "Name")))
    return sheets


def _safe_attr(obj, name, default=""):
    try:
        val = getattr(obj, name)
        return val if val is not None else default
    except Exception:
        return default


def sheet_label(sheet):
    return "{} - {}".format(_safe_attr(sheet, "SheetNumber", "?"),
                             _safe_attr(sheet, "Name", "<sheet>"))


def count_view_elements(document, view):
    try:
        return len(list(FilteredElementCollector(document, view.Id)
                         .WhereElementIsNotElementType().ToElements()))
    except Exception:
        return 0


def view_template_name(document, view):
    try:
        tid = view.ViewTemplateId
        if tid is None or tid == ElementId.InvalidElementId:
            return "-"
        t = document.GetElement(tid)
        return t.Name if t else "-"
    except Exception:
        return "-"


# ============================================================================
# ROW MODEL
# ============================================================================

class LegendRow(object):
    """One Legend view. Plain attributes (not @property) so WPF's OneWay
    binding sees a fixed snapshot per Items.Refresh() call, matching the
    pattern the rest of this suite uses for read-only DataGrids."""

    def __init__(self, view, viewports_by_view, document):
        self.view = view
        self.eid = _eid_int(view.Id)
        self.name = view.Name
        self.element_count = count_view_elements(document, view)
        self.template = view_template_name(document, view)
        self.refresh_sheets(viewports_by_view, document)

    def refresh_sheets(self, viewports_by_view, document):
        vps = viewports_by_view.get(_eid_int(self.view.Id), [])
        sheets = []
        for vp in vps:
            try:
                sh = document.GetElement(vp.SheetId)
                if sh:
                    sheets.append(sh)
            except Exception:
                continue
        sheets.sort(key=lambda s: (_safe_attr(s, "SheetNumber"), _safe_attr(s, "Name")))
        self.sheets = sheets
        self.sheet_count = len(sheets)
        self.sheets_display = (", ".join(sheet_label(s) for s in sheets)
                                if sheets else "Not placed")


class LegendRenameItem(object):
    """One Legend view, wrapped for the shared Batch Rename dialog (lib/
    batch_rename_dialog.py) - it looks for .name and .Element on whatever
    item list it's given; LegendRow itself exposes the view as .view."""

    def __init__(self, legend_row):
        self.Element = legend_row.view
        self.name = legend_row.name


class SheetRow(object):
    """One row in the sheet-picker dialog."""

    def __init__(self, sheet, originally_placed):
        self.sheet = sheet
        self.label = sheet_label(sheet)
        self.originally_placed = originally_placed
        self.selected = originally_placed


# ============================================================================
# MAIN WINDOW XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Legend Manager - DQT"
        Width="1180" Height="700"
        WindowStartupLocation="CenterScreen" Background="#FFFFFF">
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
    <Border Grid.Row="0" Background="#F0CC88" BorderBrush="#D4B87A" BorderThickness="0,0,0,2"
            CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
      <Grid>
        <StackPanel>
          <TextBlock Text="Legend Manager v1.0" FontSize="17" FontWeight="Bold" Foreground="#5D4E37"/>
          <TextBlock Text="Legend views in this model - by Dang Quoc Truong (DQT)" FontSize="10"
                     Foreground="#5D4E37" Margin="0,2,0,0"/>
        </StackPanel>
        <Button x:Name="btnHelp" Content="? Help" Padding="10,4" Background="White"
                BorderBrush="#D4B87A" HorizontalAlignment="Right"/>
      </Grid>
    </Border>

    <!-- Stat cards -->
    <Grid Grid.Row="1" Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
        <StackPanel><TextBlock Text="TOTAL" FontSize="9" Foreground="#888"/>
          <TextBlock x:Name="txtTotal" Text="0" FontSize="20" FontWeight="Bold" Foreground="#5D4E37"/></StackPanel>
      </Border>
      <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,6" Margin="4,0,4,0">
        <StackPanel><TextBlock Text="PLACED" FontSize="9" Foreground="#4CAF50"/>
          <TextBlock x:Name="txtPlaced" Text="0" FontSize="20" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel>
      </Border>
      <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,6" Margin="4,0,4,0">
        <StackPanel><TextBlock Text="UNPLACED" FontSize="9" Foreground="#FF9800"/>
          <TextBlock x:Name="txtUnplaced" Text="0" FontSize="20" FontWeight="Bold" Foreground="#FF9800"/></StackPanel>
      </Border>
      <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
        <StackPanel><TextBlock Text="SELECTED" FontSize="9" Foreground="#E5B85C"/>
          <TextBlock x:Name="txtSelected" Text="0" FontSize="20" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
      </Border>
    </Grid>

    <!-- Search / filter -->
    <Border Grid.Row="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4"
            Padding="8" Margin="0,0,0,10">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Search" VerticalAlignment="Center" Foreground="#333" Margin="0,0,6,0"/>
        <TextBox x:Name="txtSearch" Width="220" Height="26" VerticalContentAlignment="Center"
                 BorderBrush="#D4B87A"/>
        <TextBlock Text="Show" VerticalAlignment="Center" Foreground="#333" Margin="16,0,6,0"/>
        <ComboBox x:Name="cmbFilter" Width="150" Height="26" VerticalContentAlignment="Center"
                  SelectedIndex="0">
          <ComboBoxItem Content="All legends"/>
          <ComboBoxItem Content="Placed on sheets"/>
          <ComboBoxItem Content="Not placed"/>
        </ComboBox>
        <Button x:Name="btnSelectAll" Content="Select All" Padding="10,4" Margin="18,0,0,0"
                Background="White" BorderBrush="#D4B87A"/>
        <Button x:Name="btnClear" Content="Clear" Padding="10,4" Margin="6,0,0,0"
                Background="White" BorderBrush="#D4B87A"/>
      </StackPanel>
    </Border>

    <!-- DataGrid -->
    <DataGrid Grid.Row="3" x:Name="dataGrid" AutoGenerateColumns="False" IsReadOnly="True"
              SelectionMode="Extended" SelectionUnit="FullRow" CanUserSortColumns="True"
              HeadersVisibility="Column" GridLinesVisibility="All"
              Background="White" RowBackground="White" AlternatingRowBackground="#FAF3E0"
              BorderBrush="#D4B87A" BorderThickness="1"
              HorizontalGridLinesBrush="#E0E0E0" VerticalGridLinesBrush="#E0E0E0">
      <DataGrid.Columns>
        <DataGridTextColumn Header="Legend Name" Binding="{Binding name}" Width="*" SortMemberPath="name"/>
        <DataGridTextColumn Header="Elements" Binding="{Binding element_count}" Width="70" SortMemberPath="element_count"/>
        <DataGridTextColumn Header="Sheets" Binding="{Binding sheet_count}" Width="60" SortMemberPath="sheet_count"/>
        <DataGridTextColumn Header="Placed On" Binding="{Binding sheets_display}" Width="320" SortMemberPath="sheets_display"/>
        <DataGridTextColumn Header="View Template" Binding="{Binding template}" Width="150" SortMemberPath="template"/>
        <DataGridTextColumn Header="ID" Binding="{Binding eid}" Width="80" SortMemberPath="eid"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- Action buttons -->
    <Border Grid.Row="4" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4"
            Padding="8" Margin="0,10,0,0">
      <Grid>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Left">
          <Button x:Name="btnPlaceOnSheets" Content="Place on Sheets..." Padding="12,5" Margin="2"
                  Background="#F0CC88" FontWeight="SemiBold"/>
          <Button x:Name="btnRename" Content="Rename" Padding="10,5" Margin="8,2,2,2" Background="White" BorderBrush="#D4B87A"/>
          <Button x:Name="btnBatchRename" Content="Batch Rename..." Padding="10,5" Margin="2" Background="White" BorderBrush="#D4B87A"/>
          <Button x:Name="btnDuplicate" Content="Duplicate" Padding="10,5" Margin="2" Background="White" BorderBrush="#D4B87A"/>
          <Button x:Name="btnDelete" Content="Delete" Padding="10,5" Margin="2" Background="#FFCDD2"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="btnExportCSV" Content="Export CSV" Padding="10,5" Margin="2" Background="White" BorderBrush="#D4B87A"/>
          <Button x:Name="btnRefresh" Content="Refresh" Padding="10,5" Margin="2" Background="White" BorderBrush="#D4B87A"/>
          <Button x:Name="btnClose" Content="Close" Padding="10,5" Margin="2" Background="White" BorderBrush="#D4B87A"/>
        </StackPanel>
      </Grid>
    </Border>

    <Grid Grid.Row="5" Margin="0,8,0,0">
      <TextBlock Text="Dang Quoc Truong - DQT (c) 2026" FontSize="10" Foreground="#5D4E37"
                 HorizontalAlignment="Center"/>
    </Grid>
  </Grid>
</Window>
"""


# ============================================================================
# SHEET PICKER (Place on Sheets) XAML
# ============================================================================
SHEET_PICKER_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Place on Sheets - DQT"
        Width="620" Height="620"
        WindowStartupLocation="CenterScreen" Background="#FFFFFF">
  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <Border Grid.Row="0" Background="#F0CC88" BorderBrush="#D4B87A" BorderThickness="0,0,0,2"
            CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
      <StackPanel>
        <TextBlock x:Name="txtTitle" Text="Place on Sheets" FontSize="16" FontWeight="Bold" Foreground="#5D4E37"/>
        <TextBlock x:Name="txtSubtitle" Text="" FontSize="10.5" Foreground="#5D4E37"
                   Margin="0,2,0,0" TextWrapping="Wrap"/>
      </StackPanel>
    </Border>

    <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,0,0,8">
      <TextBlock Text="Search" VerticalAlignment="Center" Foreground="#333" Margin="0,0,6,0"/>
      <TextBox x:Name="txtSearch" Width="240" Height="26" VerticalContentAlignment="Center" BorderBrush="#D4B87A"/>
      <Button x:Name="btnSelectAll" Content="Select All" Padding="10,4" Margin="16,0,0,0" Background="White" BorderBrush="#D4B87A"/>
      <Button x:Name="btnClear" Content="Clear" Padding="10,4" Margin="6,0,0,0" Background="White" BorderBrush="#D4B87A"/>
    </StackPanel>

    <DataGrid Grid.Row="2" x:Name="dataGrid" AutoGenerateColumns="False" IsReadOnly="True"
              HeadersVisibility="Column" GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#E0E0E0"
              Background="White" BorderBrush="#D4B87A" BorderThickness="1" RowHeight="26"
              AlternatingRowBackground="#FAF3E0" SelectionMode="Single">
      <DataGrid.ColumnHeaderStyle>
        <Style TargetType="DataGridColumnHeader">
          <Setter Property="Background" Value="#F0CC88"/>
          <Setter Property="Foreground" Value="#5D4E37"/>
          <Setter Property="FontWeight" Value="SemiBold"/>
          <Setter Property="Padding" Value="6,4"/>
        </Style>
      </DataGrid.ColumnHeaderStyle>
      <DataGrid.Columns>
        <DataGridTemplateColumn Header="" Width="34">
          <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
              <CheckBox IsChecked="{Binding selected, Mode=OneWay}"
                        HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </DataTemplate>
          </DataGridTemplateColumn.CellTemplate>
        </DataGridTemplateColumn>
        <DataGridTextColumn Header="Sheet" Binding="{Binding label}" Width="*"/>
      </DataGrid.Columns>
    </DataGrid>

    <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <Button x:Name="btnApply" Content="Apply" Padding="16,6" Margin="2" Background="#F0CC88" FontWeight="SemiBold"/>
      <Button x:Name="btnCancel" Content="Cancel" Padding="16,6" Margin="2" Background="White" BorderBrush="#D4B87A"/>
    </StackPanel>
  </Grid>
</Window>
"""


class SheetPickerWindow(WPFWindow):
    """Pick which sheets a set of legend view(s) should be placed on.

    Single-legend mode: checkboxes reflect current placement exactly, and
    unchecking a previously-placed sheet removes that placement too - it's
    a full sync. Multi-legend mode only ever ADDS placements (removal
    across several legends at once is ambiguous), so nothing starts
    checked and unchecking has no effect beyond not adding it.
    """

    def __init__(self, target_views, viewports_by_view, document):
        WPFWindow.__init__(self, SHEET_PICKER_XAML, literal_string=True)
        self.target_views = target_views
        self.document = document
        self.single_mode = len(target_views) == 1
        self.applied = False

        if self.single_mode:
            v = target_views[0]
            self.txtTitle.Text = 'Place "{}" on Sheets'.format(v.Name)
            self.txtSubtitle.Text = (
                "Checked sheets already have this legend - uncheck one to "
                "remove it there, or check a new sheet to add it.")
            placed_ids = set(_eid_int(vp.SheetId)
                              for vp in viewports_by_view.get(_eid_int(v.Id), []))
        else:
            self.txtTitle.Text = "Place {} Legends on Sheets".format(len(target_views))
            self.txtSubtitle.Text = (
                "Check the sheets to add all {} selected legends to. "
                "A legend already on a sheet is skipped there.").format(len(target_views))
            placed_ids = set()

        self.all_rows = [SheetRow(s, _eid_int(s.Id) in placed_ids)
                          for s in get_all_sheets(document)]
        self.rows = ObservableCollection[object]()
        for r in self.all_rows:
            self.rows.Add(r)
        self.dataGrid.ItemsSource = self.rows

        self.dataGrid.AddHandler(CheckBox.ClickEvent, RoutedEventHandler(self.on_checkbox))
        self.dataGrid.MouseDoubleClick += self.on_row_toggle
        self.txtSearch.TextChanged += self.on_search
        self.btnSelectAll.Click += self.on_select_all
        self.btnClear.Click += self.on_clear
        self.btnApply.Click += self.on_apply
        self.btnCancel.Click += lambda s, e: self.Close()

    def on_checkbox(self, sender, args):
        box = None
        for candidate in (args.OriginalSource, args.Source):
            if isinstance(candidate, CheckBox):
                box = candidate
                break
        if box is None:
            return
        row = box.DataContext
        if isinstance(row, SheetRow):
            row.selected = bool(box.IsChecked)

    def on_row_toggle(self, sender, args):
        row = self.dataGrid.CurrentItem
        if isinstance(row, SheetRow):
            row.selected = not row.selected
            self.dataGrid.Items.Refresh()

    def on_search(self, sender, args):
        text = (self.txtSearch.Text or "").lower()
        self.rows.Clear()
        for r in self.all_rows:
            if not text or text in r.label.lower():
                self.rows.Add(r)

    def on_select_all(self, sender, args):
        for r in self.rows:
            r.selected = True
        self.dataGrid.Items.Refresh()

    def on_clear(self, sender, args):
        for r in self.rows:
            r.selected = False
        self.dataGrid.Items.Refresh()

    def on_apply(self, sender, args):
        to_add = [r.sheet for r in self.all_rows if r.selected and not r.originally_placed]
        to_remove = ([r.sheet for r in self.all_rows if r.originally_placed and not r.selected]
                     if self.single_mode else [])

        if not to_add and not to_remove:
            forms.alert("No changes to apply.", title="DQT - Legend Manager")
            return

        lines = []
        if to_add:
            what = ("this legend" if self.single_mode
                    else "{} legend(s)".format(len(self.target_views)))
            lines.append("Add {} to {} sheet(s).".format(what, len(to_add)))
        if to_remove:
            lines.append("Remove this legend from {} sheet(s).".format(len(to_remove)))
        lines.append("\nProceed?")
        if not forms.alert("\n".join(lines), title="DQT - Legend Manager", ok=True, cancel=True):
            return

        skipped = []
        tg = TransactionGroup(self.document, "DQT - Place Legend on Sheets")
        tg.Start()
        try:
            if to_add:
                t = Transaction(self.document, "DQT - Add Legend Viewports")
                t.Start()
                for sheet in to_add:
                    for view in self.target_views:
                        try:
                            if Viewport.CanAddViewToSheet(self.document, sheet.Id, view.Id):
                                Viewport.Create(self.document, sheet.Id, view.Id, XYZ(1, 1, 0))
                            else:
                                skipped.append("{} on {}".format(view.Name, sheet_label(sheet)))
                        except Exception as ex:
                            skipped.append("{} on {}: {}".format(view.Name, sheet_label(sheet), ex))
                t.Commit()

            if to_remove:
                view = self.target_views[0]
                t = Transaction(self.document, "DQT - Remove Legend Viewports")
                t.Start()
                for sheet in to_remove:
                    for vp in FilteredElementCollector(self.document, sheet.Id).OfClass(Viewport):
                        try:
                            if _eid_int(vp.ViewId) == _eid_int(view.Id):
                                self.document.Delete(vp.Id)
                        except Exception:
                            continue
                t.Commit()
            tg.Assimilate()
        except Exception:
            tg.RollBack()
            raise

        if skipped:
            forms.alert("Done, but some placements were skipped:\n\n" + "\n".join(skipped),
                        title="DQT - Legend Manager")
        self.applied = True
        self.Close()


# ============================================================================
# MAIN WINDOW
# ============================================================================

class LegendManagerWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)
        self.document = doc
        self.all_rows = []
        self.rows = ObservableCollection[object]()
        self.dataGrid.ItemsSource = self.rows

        self.txtSearch.TextChanged += self.on_filter
        self.cmbFilter.SelectionChanged += self.on_filter
        self.dataGrid.SelectionChanged += self.on_selection_changed
        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnPlaceOnSheets.Click += self.on_place_on_sheets
        self.btnRename.Click += self.on_rename
        self.btnBatchRename.Click += self.on_batch_rename
        self.btnDuplicate.Click += self.on_duplicate
        self.btnDelete.Click += self.on_delete
        self.btnExportCSV.Click += self.on_export_csv
        self.btnRefresh.Click += self.on_refresh
        self.btnClose.Click += lambda s, e: self.Close()
        self.btnHelp.Click += self.on_help

        self.load_data()

    # -- data ------------------------------------------------------------
    def load_data(self):
        viewports_by_view = get_viewports_by_view(self.document)
        self.all_rows = [LegendRow(v, viewports_by_view, self.document)
                          for v in get_legend_views(self.document)]
        self.all_rows.sort(key=lambda r: r.name.lower())
        self.apply_filter()

    def apply_filter(self):
        text = (self.txtSearch.Text or "").lower()
        mode = self.cmbFilter.SelectedIndex
        self.rows.Clear()
        for r in self.all_rows:
            if text and text not in r.name.lower():
                continue
            if mode == 1 and r.sheet_count == 0:
                continue
            if mode == 2 and r.sheet_count > 0:
                continue
            self.rows.Add(r)
        self.update_stats()

    def update_stats(self):
        total = len(self.all_rows)
        placed = sum(1 for r in self.all_rows if r.sheet_count > 0)
        self.txtTotal.Text = str(total)
        self.txtPlaced.Text = str(placed)
        self.txtUnplaced.Text = str(total - placed)
        self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)

    def selected_rows(self):
        return [r for r in self.dataGrid.SelectedItems]

    # -- events ------------------------------------------------------------
    def on_filter(self, sender, args):
        self.apply_filter()

    def on_selection_changed(self, sender, args):
        self.txtSelected.Text = str(self.dataGrid.SelectedItems.Count)

    def select_all(self, sender, args):
        self.dataGrid.SelectAll()

    def select_none(self, sender, args):
        self.dataGrid.UnselectAll()

    def on_refresh(self, sender, args):
        self.load_data()

    def on_help(self, sender, args):
        forms.alert(
            "Legend Manager\n\n"
            "- Search filters by name; Show narrows to placed/not-placed legends.\n"
            "- A Legend is the only Revit view type that can sit on more than one "
            "sheet at once - Placed On lists every sheet it's currently on.\n"
            "- Place on Sheets... opens a checklist of every sheet: for one selected "
            "legend it's a full sync (check to add, uncheck to remove); for several "
            "legends at once it only adds new placements.\n"
            "- Rename / Duplicate / Delete act on the selected row(s). Duplicating a "
            "legend does not copy its sheet placements - the copy starts unplaced.\n"
            "- Batch Rename... opens the same tabbed Prefix/Suffix, Find/Replace, "
            "Remove, Change Case and Numbering rename tool the other managers in "
            "this suite use, applied to every selected legend at once.\n\n"
            "Dang Quoc Truong - DQT (c) 2026",
            title="DQT - Legend Manager")

    def on_place_on_sheets(self, sender, args):
        selected = self.selected_rows()
        if not selected:
            forms.alert("Select one or more legends first.", title="DQT - Legend Manager")
            return
        viewports_by_view = get_viewports_by_view(self.document)
        picker = SheetPickerWindow([r.view for r in selected], viewports_by_view, self.document)
        picker.ShowDialog()
        if picker.applied:
            self.load_data()

    def on_rename(self, sender, args):
        selected = self.selected_rows()
        if len(selected) != 1:
            forms.alert("Select exactly one legend to rename.", title="DQT - Legend Manager")
            return
        row = selected[0]
        new_name = forms.ask_for_string(default=row.name, prompt="New name:",
                                         title="DQT - Rename Legend")
        if not new_name or new_name == row.name:
            return
        t = Transaction(self.document, "DQT - Rename Legend")
        t.Start()
        try:
            row.view.Name = new_name
            t.Commit()
        except Exception as ex:
            t.RollBack()
            forms.alert("Could not rename:\n\n{}".format(ex), title="DQT - Legend Manager")
            return
        self.load_data()

    def on_batch_rename(self, sender, args):
        if BatchRenameDialog is None:
            forms.alert(
                "The shared batch rename dialog could not be loaded from the "
                "extension's lib folder.\n\nSingle Rename still works.",
                title="DQT - Legend Manager")
            return
        selected = self.selected_rows()
        if not selected:
            forms.alert("Select one or more legends to batch rename.", title="DQT - Legend Manager")
            return
        items = [LegendRenameItem(row) for row in selected]
        dialog = BatchRenameDialog(self.document, items, self)
        dialog.ShowDialog()
        self.load_data()

    def on_duplicate(self, sender, args):
        selected = self.selected_rows()
        if not selected:
            forms.alert("Select one or more legends to duplicate.", title="DQT - Legend Manager")
            return
        t = Transaction(self.document, "DQT - Duplicate Legend")
        t.Start()
        created, failed = 0, []
        for row in selected:
            try:
                row.view.Duplicate(ViewDuplicateOption.Duplicate)
                created += 1
            except Exception as ex:
                failed.append("{}: {}".format(row.name, ex))
        t.Commit()
        msg = "Duplicated {} legend(s).".format(created)
        if failed:
            msg += "\n\nFailed:\n" + "\n".join(failed)
        forms.alert(msg, title="DQT - Legend Manager")
        self.load_data()

    def on_delete(self, sender, args):
        selected = self.selected_rows()
        if not selected:
            forms.alert("Select one or more legends to delete.", title="DQT - Legend Manager")
            return
        placed = [r for r in selected if r.sheet_count > 0]
        msg = "Delete {} legend(s)?".format(len(selected))
        if placed:
            msg += ("\n\n{} of them are placed on sheets - deleting removes those "
                    "placements too.").format(len(placed))
        if not forms.alert(msg, title="DQT - Legend Manager", ok=True, cancel=True):
            return
        t = Transaction(self.document, "DQT - Delete Legend")
        t.Start()
        try:
            for row in selected:
                self.document.Delete(row.view.Id)
            t.Commit()
        except Exception as ex:
            t.RollBack()
            forms.alert("Could not delete:\n\n{}".format(ex), title="DQT - Legend Manager")
            return
        self.load_data()

    def on_export_csv(self, sender, args):
        try:
            from System.Windows.Forms import SaveFileDialog, DialogResult
            dialog = SaveFileDialog()
            dialog.Filter = "CSV Files (*.csv)|*.csv|All Files (*.*)|*.*"
            dialog.DefaultExt = "csv"
            dialog.FileName = "LegendManager_{}.csv".format(
                System.DateTime.Now.ToString("yyyyMMdd_HHmmss"))
            if dialog.ShowDialog() != DialogResult.OK:
                return
            with codecs.open(dialog.FileName, 'w', encoding='utf-8-sig') as f:
                f.write("Name,Elements,Sheets,Placed On,View Template,ID\n")
                for r in self.all_rows:
                    f.write('"{}",{},{},"{}","{}",{}\n'.format(
                        r.name.replace('"', '""'), r.element_count, r.sheet_count,
                        r.sheets_display.replace('"', '""'),
                        r.template.replace('"', '""'), r.eid))
            forms.alert("Exported {} legend(s).".format(len(self.all_rows)),
                        title="DQT - Legend Manager")
        except Exception as ex:
            forms.alert("Could not export:\n{}".format(ex), title="DQT - Legend Manager")


if __name__ == '__main__':
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Please open a project first.", title="Legend Manager")
    else:
        LegendManagerWindow().ShowDialog()
