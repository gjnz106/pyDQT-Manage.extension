# -*- coding: utf-8 -*-
"""Dimension Manager v1.0
Author: Dang Quoc Truong (DQT)

Lists every Dimension Type with how many instances are placed, so an
unused type (a purge candidate) or a heavily-used one is visible at a
glance. Selecting a type and clicking Detail shows exactly which view
each of its instances lives in - every Dimension is view-specific, so
that lookup is always instant, unlike Model Groups. Rename, Batch Rename
and Delete Type act on the selected types directly from the grid.
"""
__title__ = "Dimension\nManager"
__author__ = "DQT"

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')
clr.AddReference('PresentationFramework')
for _asm in ("System.Data", "System.Data.Common"):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass

import System
from System.Data import DataTable
from System.Windows.Controls import DataGridEditAction

from pyrevit import revit, forms, script, HOST_APP, DB
from pyrevit.forms import WPFWindow
from pyrevit.compat import get_elementid_value_func
from Autodesk.Revit.DB import *
from System.Collections.Generic import List
import codecs
import datetime
import os

# Shared batch rename dialog (extension lib/). Imported softly: it powers one
# button, so a broken install should not stop the whole manager from opening -
# the button reports it instead.
try:
    from batch_rename_dialog import BatchRenameDialog
except ImportError:
    BatchRenameDialog = None

get_elementid_value = get_elementid_value_func()


def _eid_int(eid):
    """Get integer value from ElementId - compatible with Revit 2024-2026"""
    if eid is None:
        return -1
    return get_elementid_value(eid)


def _open_help_page(html_filename):
    """Open this tool's page from the shared _Settings_Help folder in the
    default browser. Returns True on success, False if the caller should
    fall back to the in-app help text (e.g. the folder went missing)."""
    try:
        panel_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(panel_dir, "_Settings_Help", html_filename)
        if not os.path.isfile(path):
            return False
        os.startfile(path)
        return True
    except Exception:
        return False


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
        self.element = None         # the DimensionType itself, for inline edits

    @property
    def Element(self):
        """Capitalised alias of .element.

        The shared BatchRenameDialog reads names and ids off wrapper objects
        through item.Element, so exposing it here lets the dimension summaries
        be handed to that dialog unchanged."""
        return self.element


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

# Grid column binding path -> (BuiltInParameter, display name) it writes to.
EDITABLE_FIELDS = {
    "text_size": (_BIP_TEXT_SIZE, "Text Size"),
    "text_font": (_BIP_TEXT_FONT, "Text Font"),
    "width_factor": (_BIP_WIDTH_FACTOR, "Width Factor"),
}


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


def apply_dimension_type_edit(doc, item, field, value):
    """Write one edited grid cell back to its DimensionType.

    Returns (ok, error_message). Text Size and Width Factor are written with
    SetValueString so Revit parses them in the project's display units -
    typing "2.5" in a millimetre project must mean 2.5 mm, not 2.5 feet."""
    spec = EDITABLE_FIELDS.get(field)
    if spec is None:
        return False, "unknown field '{}'".format(field)
    bip, display_name = spec

    dt = item.element
    if dt is None:
        return False, "this dimension type no longer exists - refresh and try again"

    param = _param_by_bip_or_name(dt, bip, display_name)
    if param is None:
        return False, "this type has no {} parameter".format(display_name)
    if param.IsReadOnly:
        return False, "{} is read-only on this type".format(display_name)

    t = DB.Transaction(doc, "DQT - Edit Dimension Type")
    t.Start()
    try:
        text = str(value).strip() if value is not None else ""
        if not text:
            raise Exception("{} cannot be empty".format(display_name))

        if field == "text_font":
            param.Set(text)

        elif field == "text_size":
            if not param.SetValueString(text):
                raise Exception(
                    "'{}' is not a valid text size - type a number in the "
                    "project's units (e.g. 2.5)".format(text))

        elif field == "width_factor":
            if not param.SetValueString(text):
                # Width factor is a plain ratio, so a raw number is safe here.
                try:
                    param.Set(float(text))
                except ValueError:
                    raise Exception("'{}' is not a number".format(text))

        t.Commit()
        return True, None

    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return False, str(ex)


def _set_dimension_field(dt, field, value):
    """Write one field on one DimensionType, WITHOUT opening its own
    transaction - the batch editor wraps every selected type in a single
    transaction instead of one per cell, the way apply_dimension_type_edit
    (used by the inline double-click-to-edit cell) does. Same validation as
    that function; kept separate rather than shared so the working inline
    edit path is not touched by the batch feature.

    Returns (status, message): status is "ok", "skip" (this type has no
    such parameter - not every dimension style carries every field, so
    that is not a failure), or "error" (a real problem: bad value,
    read-only parameter, or an exception setting it)."""
    spec = EDITABLE_FIELDS.get(field)
    if spec is None:
        return "error", "unknown field '{}'".format(field)
    bip, display_name = spec

    param = _param_by_bip_or_name(dt, bip, display_name)
    if param is None:
        return "skip", "this type has no {} parameter".format(display_name)
    if param.IsReadOnly:
        return "error", "{} is read-only on this type".format(display_name)

    text = str(value).strip() if value is not None else ""
    if not text:
        return "error", "{} cannot be empty".format(display_name)

    try:
        if field == "text_font":
            param.Set(text)
        elif field == "width_factor":
            if not param.SetValueString(text):
                try:
                    param.Set(float(text))
                except ValueError:
                    return "error", "'{}' is not a number".format(text)
        return "ok", None
    except Exception as ex:
        return "error", str(ex)


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
            item.element = dt
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


def _rename_type(doc, dt, new_name, alert=True):
    """Rename a DimensionType, the version-safe way this suite already
    relies on for other element types (Element.Name.SetValue first, plain
    .Name as the fallback for whichever a given Revit build refuses).

    Batch callers pass alert=False: one popup per failing type would be
    unusable, so the reason goes to the output window and the caller reports
    the totals once at the end."""
    try:
        DB.Element.Name.SetValue(dt, new_name)
        return True
    except Exception:
        pass
    try:
        dt.Name = new_name
        return True
    except Exception as ex:
        if alert:
            forms.alert("Could not rename: {}".format(ex), title="DQT - Dimension Manager")
        else:
            print("  Could not rename: {}".format(ex))
        return False


def _info_or_none(value):
    """Grid placeholders ('-', blank) must not end up as literal name
    segments, so they read as 'no information' to the rename dialog."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    return text


def _open_batch_rename(doc, items, parent):
    """Show the shared batch rename dialog, flavoured for dimension types.

    The subclass is built here rather than at module level because
    BatchRenameDialog is an optional import, and subclassing None would take
    the whole Dimension Manager down over a feature that is one button."""

    class DimensionBatchRenameDialog(BatchRenameDialog):
        """Dimension types in the shared find/replace, prefix/suffix,
        segments and custom-position dialog the other managers use.

        The Type/Segments tab is fed the three attributes that actually tell
        one dimension type from another, and renaming goes through
        _rename_type() rather than the base class's plain .Name assignment -
        Element.Name.SetValue is the form that works across the Revit builds
        this suite supports, and it is what the single Rename button uses."""

        def __init__(self, doc, selected_items, parent):
            self.manager = parent
            BatchRenameDialog.__init__(self, doc, selected_items, parent)
            self.Title = "Batch Rename Dimension Types - {} selected".format(
                len(selected_items))

        def get_type_info(self, item):
            return _info_or_none(getattr(item, "style", None))

        def get_size_info(self, item):
            return _info_or_none(getattr(item, "text_size", None))

        def get_segment_info(self, item):
            return _info_or_none(getattr(item, "text_font", None))

        def apply_batch_rename(self):
            from batch_rename_dialog import sanitize_revit_name

            success = 0
            skipped = 0
            errors = 0

            print("\n" + "=" * 60)
            print("DQT - BATCH RENAME DIMENSION TYPES ({} selected)".format(
                len(self.selected_items)))
            print("=" * 60)

            try:
                with revit.Transaction("DQT - Batch Rename Dimension Types"):
                    for item in self.selected_items:
                        old_name = item.name
                        new_name = sanitize_revit_name(
                            self.apply_rename_rules(item, old_name))

                        if not new_name or new_name == old_name:
                            skipped += 1
                            continue

                        # Renames already applied in this transaction are
                        # visible to the check, so two rules collapsing onto
                        # the same name is caught here rather than left for
                        # Revit to reject halfway through.
                        if self.check_name_conflict(new_name, item):
                            print("  '{}' -> '{}' skipped: name already in use".format(
                                old_name, new_name))
                            skipped += 1
                            continue

                        print("  '{}' -> '{}'".format(old_name, new_name))
                        if _rename_type(self.doc, item.element, new_name,
                                        alert=False):
                            success += 1
                        else:
                            errors += 1
            except Exception as ex:
                print("Batch rename failed, nothing was changed: {}".format(ex))
                success, skipped, errors = 0, 0, len(self.selected_items)

            print("-" * 60)
            print("{} renamed, {} skipped, {} failed".format(
                success, skipped, errors))

            self.show_results(success, skipped, errors)

            if self.manager is not None:
                try:
                    self.manager.refresh(None, None)
                except Exception as ex:
                    print("Could not refresh the manager window: {}".format(ex))

            self.result = True
            self.Close()

    DimensionBatchRenameDialog(doc, items, parent).ShowDialog()


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
# XAML - BATCH EDIT DIALOG (Text Font / Width Factor across many types)
# ============================================================================
BATCH_EDIT_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Batch Edit - DQT"
        Width="480" Height="330"
        WindowStartupLocation="CenterScreen"
        Background="#FEF8E7" ResizeMode="NoResize">
    <Grid Margin="15">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#F0CC88" CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
            <TextBlock Text="Batch Edit Text Font / Width Factor" FontSize="16" FontWeight="Bold"/>
        </Border>

        <TextBlock Grid.Row="1" x:Name="txtInfo" Text="" FontSize="12" Foreground="#5D4E37" Margin="0,0,0,15"/>

        <StackPanel Grid.Row="2">
            <StackPanel Orientation="Horizontal" Margin="0,0,0,15">
                <CheckBox x:Name="chkFont" Content="Set Text Font to:" VerticalAlignment="Center" Width="150"/>
                <ComboBox x:Name="cmbFont" Width="230" Height="26" IsEditable="True" IsEnabled="False"/>
            </StackPanel>
            <StackPanel Orientation="Horizontal">
                <CheckBox x:Name="chkWidth" Content="Set Width Factor to:" VerticalAlignment="Center" Width="150"/>
                <TextBox x:Name="txtWidth" Width="230" Height="26" Padding="4,2" IsEnabled="False" VerticalContentAlignment="Center"/>
            </StackPanel>
            <TextBlock Text="A type with no Text Font / Width Factor parameter (not every dimension style has one) is skipped, not failed." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,15,0,0"/>
        </StackPanel>

        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,15,0,0">
            <Button x:Name="btnApply" Content="Apply" Padding="18,6" Margin="0,0,8,0" Background="#F0CC88" FontWeight="SemiBold"/>
            <Button x:Name="btnCancel" Content="Cancel" Padding="18,6" Background="White"/>
        </StackPanel>
    </Grid>
</Window>
"""


class BatchEditDialog(WPFWindow):
    """Set Text Font and/or Width Factor on many DimensionTypes at once,
    in a single transaction - the double-click-to-edit grid cells only
    ever touch one type at a time."""

    def __init__(self, doc, items, parent):
        WPFWindow.__init__(self, BATCH_EDIT_XAML, literal_string=True)
        self.doc = doc
        self.items = items
        self.parent = parent
        self.applied = False

        self.txtInfo.Text = "{} dimension type(s) selected.".format(len(items))

        fonts = sorted(set(i.text_font for i in items
                            if i.text_font and i.text_font != "-"))
        for font in fonts:
            self.cmbFont.Items.Add(font)

        self.chkFont.Checked += self._on_font_checked
        self.chkFont.Unchecked += self._on_font_unchecked
        self.chkWidth.Checked += self._on_width_checked
        self.chkWidth.Unchecked += self._on_width_unchecked
        self.btnApply.Click += self.on_apply
        self.btnCancel.Click += lambda s, e: self.Close()

    def _on_font_checked(self, s, e):
        self.cmbFont.IsEnabled = True

    def _on_font_unchecked(self, s, e):
        self.cmbFont.IsEnabled = False

    def _on_width_checked(self, s, e):
        self.txtWidth.IsEnabled = True

    def _on_width_unchecked(self, s, e):
        self.txtWidth.IsEnabled = False

    def on_apply(self, sender, args):
        updates = {}
        if self.chkFont.IsChecked:
            font_text = (self.cmbFont.Text or "").strip()
            if not font_text:
                forms.alert("Enter a Text Font, or untick 'Set Text Font to'.",
                            title="DQT - Batch Edit")
                return
            updates["text_font"] = font_text

        if self.chkWidth.IsChecked:
            width_text = (self.txtWidth.Text or "").strip()
            if not width_text:
                forms.alert("Enter a Width Factor, or untick 'Set Width Factor to'.",
                            title="DQT - Batch Edit")
                return
            updates["width_factor"] = width_text

        if not updates:
            forms.alert("Tick at least one field to set.", title="DQT - Batch Edit")
            return

        success = 0
        skipped = 0
        failures = []

        with revit.Transaction("DQT - Batch Edit Dimension Types"):
            for item in self.items:
                if item.element is None:
                    skipped += 1
                    continue
                item_ok = False
                item_failed = False
                for field, value in updates.items():
                    status, err = _set_dimension_field(item.element, field, value)
                    if status == "ok":
                        item_ok = True
                    elif status == "error":
                        item_failed = True
                        failures.append("{}: {}".format(item.name, err))
                    # status == "skip": no such parameter on this type -
                    # not a failure, just doesn't apply here.
                if item_failed:
                    continue
                if item_ok:
                    success += 1
                else:
                    skipped += 1

        message = "Updated {} of {} dimension type(s).".format(success, len(self.items))
        if skipped:
            message += "\n{} skipped (no matching parameter on that type).".format(skipped)
        if failures:
            lines = failures[:8]
            more = "" if len(failures) <= 8 else "\n... and {} more".format(len(failures) - 8)
            message += "\n\nFailed:\n" + "\n".join(lines) + more
        forms.alert(message, title="DQT - Batch Edit")

        self.applied = True
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
            <Grid>
                <StackPanel>
                    <TextBlock Text="Dimension Manager" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="Dimension types in this model - by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37" Margin="0,2,0,0"/>
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
                    <TextBlock Text="Double-click Text Size / Text Font / Width Factor to edit directly - Enter commits the change to the model. Select a type and click Detail to see which view each instance is used in." FontSize="9" Foreground="#888" TextWrapping="Wrap" Margin="0,6,0,0"/>
                </StackPanel>
            </Border>

            <!-- DataGrid -->
            <DataGrid Grid.Column="1" x:Name="dataGrid"
                      AutoGenerateColumns="False" IsReadOnly="False"
                      SelectionMode="Extended" SelectionUnit="FullRow"
                      CanUserSortColumns="True"
                      Background="White" BorderBrush="#D4B87A"
                      GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#EEE"
                      RowBackground="White" AlternatingRowBackground="#FFFDF5">
                <DataGrid.Columns>
                    <DataGridTextColumn x:Name="colId" Header="ID" Binding="{Binding type_id}" Width="70" SortMemberPath="type_id" IsReadOnly="True"/>
                    <DataGridTextColumn Header="Name" Binding="{Binding name}" Width="*" SortMemberPath="name" IsReadOnly="True"/>
                    <DataGridTextColumn Header="Style" Binding="{Binding style}" Width="90" SortMemberPath="style" IsReadOnly="True"/>
                    <DataGridTextColumn x:Name="colTextSize" Header="Text Size" Binding="{Binding text_size}" Width="80" SortMemberPath="text_size"/>
                    <DataGridTextColumn x:Name="colTextFont" Header="Text Font" Binding="{Binding text_font}" Width="130" SortMemberPath="text_font"/>
                    <DataGridTextColumn x:Name="colWidthFactor" Header="Width Factor" Binding="{Binding width_factor}" Width="90" SortMemberPath="width_factor"/>
                    <DataGridTextColumn Header="Instances" Binding="{Binding instance_count}" Width="80" SortMemberPath="instance_count" IsReadOnly="True"/>
                    <DataGridTextColumn Header="Created By" Binding="{Binding created_by}" Width="120" SortMemberPath="created_by" IsReadOnly="True"/>
                    <DataGridTextColumn Header="Workset" Binding="{Binding workset}" Width="120" SortMemberPath="workset" IsReadOnly="True"/>
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
                    <Button x:Name="btnBatchRename" Content="Batch Rename" Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnBatchEdit" Content="Batch Edit Font/Width..." Padding="10,5" Margin="2" Background="White"/>
                    <Button x:Name="btnDeleteType" Content="Delete Type" Padding="10,5" Margin="2" Background="#FFCDD2"/>
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
        self._suppress_cell_events = False

        self.txtSearch.TextChanged += self.on_filter
        self.dataGrid.SelectionChanged += self.on_selection
        self.dataGrid.MouseDoubleClick += self.on_double_click
        self.dataGrid.CellEditEnding += self.on_cell_edit_ending

        self.btnSelectAll.Click += self.select_all
        self.btnClear.Click += self.select_none
        self.btnRefresh.Click += self.refresh
        self.btnSelectInModel.Click += self.select_in_model
        self.btnZoom.Click += self.zoom_to
        self.btnDetail.Click += self.show_detail
        self.btnRename.Click += self.rename_selected
        self.btnBatchRename.Click += self.batch_rename_selected
        self.btnBatchEdit.Click += self.batch_edit_selected
        self.btnDeleteType.Click += self.delete_types_selected
        self.btnExportCSV.Click += self.export_csv
        self.btnClose.Click += self.close_window
        self.btnHelp.Click += self.show_help

        self.load_data()
        self.update_ui()

    def show_help(self, sender, args):
        if _open_help_page("dimension_manager.html"):
            return
        from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage
        MessageBox.Show(
            "Dimension Manager\n\n"
            "- Search filters by name, style, font, creator or workset.\n"
            "- Double-click Text Size / Text Font / Width Factor to edit in place; Enter commits it.\n"
            "- Detail shows every instance of the selected type and which view it's in.\n"
            "- Select in Model / Zoom To act on the ticked rows; Rename / Batch Rename / Delete Type edit the type itself.\n"
            "- Batch Edit Font/Width... sets Text Font and/or Width Factor on every "
            "selected type at once, instead of one cell at a time.\n\n"
            "Dang Quoc Truong - DQT (c) 2026",
            "Help", MessageBoxButton.OK, MessageBoxImage.Information)

    def load_data(self):
        self.items = get_dimension_types(self.doc)
        self.filtered = list(self.items)

    def update_ui(self):
        self.txtTotal.Text = str(len(self.items))
        self.txtUnused.Text = str(len([i for i in self.items if i.instance_count == 0]))
        self.txtSelected.Text = "0"
        self.update_grid()

    def _build_datatable(self, items):
        """Build a System.Data.DataTable from the item list - the pattern
        this suite's Text Note Type Manager already relies on for a stable,
        two-way editable DataGrid binding (plain IronPython objects bound
        directly had edit-commit bugs there)."""
        dt = DataTable("DimensionTypes")
        dt.Columns.Add("type_id", System.Int64)
        dt.Columns.Add("name", System.String)
        dt.Columns.Add("style", System.String)
        dt.Columns.Add("text_size", System.String)
        dt.Columns.Add("text_font", System.String)
        dt.Columns.Add("width_factor", System.String)
        dt.Columns.Add("instance_count", System.Int32)
        dt.Columns.Add("created_by", System.String)
        dt.Columns.Add("workset", System.String)

        for item in items:
            row = dt.NewRow()
            row["type_id"] = item.type_id
            row["name"] = item.name
            row["style"] = item.style
            row["text_size"] = item.text_size
            row["text_font"] = item.text_font
            row["width_factor"] = item.width_factor
            row["instance_count"] = item.instance_count
            row["created_by"] = item.created_by
            row["workset"] = item.workset
            dt.Rows.Add(row)
        return dt

    def update_grid(self):
        dt = self._build_datatable(self.filtered)
        self.dataGrid.ItemsSource = dt.DefaultView

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

    def _resolve_selected_items(self):
        """Selected grid rows (DataRowView) resolved back to
        DimensionTypeSummary objects by type_id - never by row/list index,
        since CanUserSortColumns means the grid's row order can differ from
        self.filtered's load order once the user sorts a column."""
        by_id = {}
        for item in self.filtered:
            by_id[item.type_id] = item
        selected = []
        for row_view in self.dataGrid.SelectedItems:
            try:
                tid = row_view["type_id"]
            except Exception:
                continue
            item = by_id.get(tid)
            if item is not None:
                selected.append(item)
        return selected

    def _selected_instance_ids(self):
        ids = List[ElementId]()
        for item in self._resolve_selected_items():
            for eid in item.instance_ids:
                ids.Add(eid)
        return ids

    def on_double_click(self, s, e):
        if self.dataGrid.SelectedItems.Count != 1:
            return
        cell = self._cell_under(e.OriginalSource)
        if cell is None:
            # Can't tell which column was clicked - e.g. the second click of
            # the double-click landed on the edit TextBox WPF already
            # swapped in for an editable cell. Do nothing rather than risk
            # treating an edit attempt as a navigate/zoom request.
            return
        if (cell.Column is self.colTextSize or
                cell.Column is self.colTextFont or
                cell.Column is self.colWidthFactor):
            return  # editable cell - let the DataGrid enter edit mode
        selected = self._resolve_selected_items()
        if len(selected) != 1:
            return
        item = selected[0]
        if cell.Column is self.colId:
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
        selected = self._resolve_selected_items()
        if len(selected) != 1:
            return
        item = selected[0]
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
        selected = self._resolve_selected_items()
        if len(selected) != 1:
            return
        item = selected[0]
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

    def batch_rename_selected(self, s, e):
        if BatchRenameDialog is None:
            forms.alert(
                "The shared batch rename dialog could not be loaded from the "
                "extension's lib folder.\n\n"
                "Single Rename still works.",
                title="DQT - Dimension Manager")
            return

        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select one or more dimension types to batch rename.",
                        title="DQT - Dimension Manager")
            return

        selected = [item for item in self._resolve_selected_items()
                    if item.element is not None]
        if not selected:
            forms.alert("The selected dimension types no longer exist - "
                        "refresh and try again.",
                        title="DQT - Dimension Manager")
            return

        _open_batch_rename(self.doc, selected, self)

    def batch_edit_selected(self, s, e):
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select one or more dimension types to batch edit.",
                        title="DQT - Dimension Manager")
            return

        selected = [item for item in self._resolve_selected_items()
                    if item.element is not None]
        if not selected:
            forms.alert("The selected dimension types no longer exist - "
                        "refresh and try again.",
                        title="DQT - Dimension Manager")
            return

        dialog = BatchEditDialog(self.doc, selected, self)
        dialog.ShowDialog()
        if dialog.applied:
            self.refresh(s, e)

    def delete_types_selected(self, s, e):
        """Delete the selected dimension types. Deleting a type that still
        has placed instances deletes those instances too - that is Revit's
        own cascade behaviour for element types, not something this tool
        does explicitly - so the confirmation spells it out before anything
        happens."""
        if self.dataGrid.SelectedItems.Count == 0:
            forms.alert("Select one or more dimension types to delete.",
                        title="DQT - Dimension Manager")
            return

        selected = [item for item in self._resolve_selected_items()
                    if item.element is not None]
        if not selected:
            forms.alert("The selected dimension types no longer exist - "
                        "refresh and try again.",
                        title="DQT - Dimension Manager")
            return

        total_instances = sum(item.instance_count for item in selected)
        names = ", ".join(item.name for item in selected[:5])
        if len(selected) > 5:
            names += ", ... (+{} more)".format(len(selected) - 5)

        message = "Delete {} dimension type(s)?\n\n{}\n\n".format(len(selected), names)
        if total_instances:
            message += ("This also deletes {} placed dimension instance(s) "
                        "that use these types, across every view. This "
                        "cannot be undone from this dialog.").format(total_instances)
        else:
            message += "None of the selected types have placed instances."

        if not forms.alert(message, title="DQT - Delete Dimension Types",
                           yes=True, no=True, warn_icon=True):
            return

        deleted = 0
        failed = []
        try:
            with revit.Transaction("DQT - Delete Dimension Types"):
                for item in selected:
                    try:
                        # Document.Delete returns the ids it actually removed
                        # (including cascaded instances) rather than raising
                        # when Revit silently refuses - e.g. the last
                        # remaining type in a family. An empty result is
                        # exactly that case, so it is reported as a failure
                        # too even though nothing threw.
                        removed = self.doc.Delete(ElementId(item.type_id))
                        if removed is not None and removed.Count > 0:
                            deleted += 1
                        else:
                            failed.append("{} (nothing was removed - Revit "
                                          "may require at least one type "
                                          "of this kind)".format(item.name))
                    except Exception as ex:
                        failed.append("{}: {}".format(item.name, ex))
        except Exception as ex:
            forms.alert("Delete failed, nothing was changed: {}".format(ex),
                        title="DQT - Dimension Manager")
            return

        message = "{} dimension type(s) deleted.".format(deleted)
        if failed:
            message += "\n\nNot deleted ({}):\n".format(len(failed)) + "\n".join(failed[:10])
            if len(failed) > 10:
                message += "\n..."
        forms.alert(message, title="DQT - Dimension Manager")

        self.refresh(s, e)

    def on_cell_edit_ending(self, sender, args):
        """Push an edited Text Size / Text Font / Width Factor cell back to
        its DimensionType.

        Runs SYNCHRONOUSLY and deliberately so. This window is modal, so the
        handler is still nested inside the external command that opened it
        and the Revit API context is valid - exactly like the Rename
        button's Click handler. Deferring the write to the WPF Dispatcher
        would let it run after ShowDialog() has returned and the command has
        ended: starting a Transaction with no API context, from a callback
        whose scope is already being torn down, takes Revit down with a
        fatal error instead of raising something catchable."""
        if args.EditAction != DataGridEditAction.Commit:
            return
        if self._suppress_cell_events:
            return

        try:
            field = args.Column.Binding.Path.Path
        except Exception:
            return
        if field not in EDITABLE_FIELDS:
            return

        editing = args.EditingElement
        try:
            new_value = editing.Text
        except Exception:
            return

        try:
            type_id = args.Row.Item["type_id"]
        except Exception:
            return

        item = None
        for candidate in self.filtered:
            if candidate.type_id == type_id:
                item = candidate
                break
        if item is None:
            return

        ok, err = apply_dimension_type_edit(self.doc, item, field, new_value)
        if not ok:
            display_name = EDITABLE_FIELDS.get(field, (None, field))[1]
            forms.alert("Could not set {} on '{}':\n\n{}".format(display_name, item.name, err),
                        title="DQT - Dimension Manager")

        # Re-read the type and hand the authoritative value back to the
        # editor before the grid commits it. On success that shows what
        # Revit actually stored (it normalises "1.8" to "1.8000 mm"); on
        # failure it puts the old value back so rejected text never sticks.
        if field == "text_size":
            item.text_size = _dim_text_size(item.element)
        elif field == "text_font":
            item.text_font = _dim_text_font(item.element)
        elif field == "width_factor":
            item.width_factor = _dim_width_factor(item.element)

        self._suppress_cell_events = True
        try:
            editing.Text = getattr(item, field)
        except Exception:
            pass
        finally:
            self._suppress_cell_events = False

    def export_csv(self, s, e):
        current_items = list(self.filtered)
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
