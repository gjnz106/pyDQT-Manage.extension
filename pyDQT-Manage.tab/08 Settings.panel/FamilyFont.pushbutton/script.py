# -*- coding: utf-8 -*-
"""
Family Font Manager

Batch-changes the Text Font (and optionally the Width Factor) used inside 2D
annotation families (Generic Annotations, Tags, Title Blocks, Symbols,
Callout/Elevation/Grid/Level heads, View Titles, etc.) without opening each
family one at a time.

METHOD: for every loadable family whose category is selected, the family is
opened headlessly with Document.EditFamily(), every element TYPE inside it
that exposes a Text Font parameter has that parameter changed, then the
family is reloaded into the project with Document.LoadFamily() and the
temporary family document is discarded (never saved to disk).

WHY "every type with a Text Font parameter" and not "every TextNoteType":
a Label placed in a tag / title block / annotation family does NOT use a
Text Note Type - it uses its own "Tag Label" system-family type, a different
class. Collecting only TextNoteType silently misses every Label, which is
usually the only visible text in a tag or a section head. Filtering on the
presence of BuiltInParameter.TEXT_FONT catches Text Note Types, Tag Label
types, and anything else Revit gives a font to, in every Revit version.

Revit's screen may flicker as each family briefly becomes the active
document while it is edited - that is EditFamily doing its job, not an
error, and it needs no interaction. SAVE the model before running: a large
batch reloads many families in sequence and, like any bulk sketch/family
operation, is best done with a fresh save to fall back on.

BLACK BOX: every step is appended (open/write/close, unbuffered) to
%USERPROFILE%/DQT_FamilyFont.log, so a run that stops partway can be
diagnosed from the last line written.

Dang Quoc Truong - DQT (c) 2026
"""

__title__ = "Family\nFont"
__author__ = "DQT"

from pyrevit import revit, forms
from pyrevit.forms import WPFWindow
from Autodesk.Revit.DB import *
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import RoutedEventHandler
from System.Windows.Controls import CheckBox
import clr
clr.AddReference('System.Drawing')
from System.Drawing.Text import InstalledFontCollection
import datetime
import os
import tempfile

doc = revit.doc


def _eid_int(eid):
    """Get integer value of an ElementId across Revit 2024-2027."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _default_log_path():
    """A log location that stays the SAME across Revit restarts (see the
    Split Shaft Opening tool for the reasoning - %TEMP% is per-session)."""
    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if base:
            try:
                if os.path.isdir(base):
                    return os.path.join(base, "DQT_FamilyFont.log")
            except:
                pass
    return os.path.join(tempfile.gettempdir(), "DQT_FamilyFont.log")


_LOG_PATH = _default_log_path()


def _log(msg):
    """Crash-proof black-box log: open/append/close per line, unbuffered."""
    try:
        f = open(_LOG_PATH, "a")
        try:
            f.write("{} | {}\n".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
        finally:
            f.close()
    except:
        pass


# ============================================================================
# FAMILY RELOAD OPTIONS
# ============================================================================
class _OverwriteLoadOptions(IFamilyLoadOptions):
    """Reload options for LoadFamily: always keep the existing family (so
    every instance and type assignment in the project stays put) and
    overwrite its parameter values with the edited copy's."""
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source,
                             overwriteParameterValues):
        source.Value = FamilySource.Family
        overwriteParameterValues.Value = True
        return True


# ============================================================================
# HELPERS
# ============================================================================
def get_name(element):
    try:
        if hasattr(element, 'Name') and element.Name:
            return element.Name
    except:
        pass
    try:
        name = Element.Name.GetValue(element)
        if name:
            return name
    except:
        pass
    return "<No Name>"


def get_installed_fonts():
    """Fonts installed on this machine, for the target-font picker."""
    try:
        ifc = InstalledFontCollection()
        return sorted(set(f.Name for f in ifc.Families))
    except:
        return []


def _param(element_type, bip):
    try:
        return element_type.get_Parameter(bip)
    except:
        return None


def font_param(element_type):
    """The Text Font parameter of a type, or None if it has no usable one."""
    p = _param(element_type, BuiltInParameter.TEXT_FONT)
    if p is None:
        return None
    try:
        if p.StorageType != StorageType.String:
            return None
    except:
        pass
    return p


def _resolve_width_bip():
    """BuiltInParameter for Width Factor. Resolved defensively so that a
    renamed/missing enum member degrades to the by-name lookup in
    width_param() instead of throwing on every type."""
    try:
        return BuiltInParameter.TEXT_WIDTH_SCALE
    except AttributeError:
        return None


_WIDTH_BIP = _resolve_width_bip()


def _as_double_param(p):
    if p is None:
        return None
    try:
        if p.StorageType != StorageType.Double:
            return None
    except:
        return None
    return p


def width_param(element_type):
    """The Width Factor parameter of a type, or None if it has no usable
    one. Not every font-bearing type exposes Width Factor."""
    if _WIDTH_BIP is not None:
        p = _as_double_param(_param(element_type, _WIDTH_BIP))
        if p is not None:
            return p
    try:
        return _as_double_param(element_type.LookupParameter("Width Factor"))
    except:
        return None


def font_bearing_types(fam_doc):
    """Every element TYPE in the family document that carries a Text Font
    parameter. This is deliberately parameter-driven rather than class-
    driven: Labels use "Tag Label" types, plain text uses TextNoteType, and
    the two do not share a class - see the module docstring."""
    found = []
    for et in FilteredElementCollector(fam_doc).WhereElementIsElementType():
        if font_param(et) is not None:
            found.append(et)
    return found


def type_kind(element_type):
    """Short human label for what sort of type this is, so the scan grid can
    show "3 Text, 2 Label" instead of an opaque count."""
    try:
        if isinstance(element_type, TextNoteType):
            return "Text"
    except:
        pass
    try:
        if isinstance(element_type, DimensionType):
            return "Dim"
    except:
        pass
    try:
        if isinstance(element_type, TextElementType):
            return "Label"
    except:
        pass
    try:
        return element_type.GetType().Name
    except:
        return "Type"


def _fmt_width(value):
    return "{0:.2f}".format(value)


def collect_loadable_families():
    """Every loadable, non-in-place Family in the project, with its category
    and whether that category is a 2D annotation category."""
    rows = []
    for fam in FilteredElementCollector(doc).OfClass(Family):
        try:
            if fam.IsInPlace:
                continue
            cat = fam.FamilyCategory
            cat_name = cat.Name if cat else "Uncategorized"
            is_annotation = bool(cat) and cat.CategoryType == CategoryType.Annotation
            rows.append({
                "eid": fam.Id,
                "id": _eid_int(fam.Id),
                "name": get_name(fam),
                "category": cat_name,
                "is_annotation": is_annotation,
                "editable": fam.IsEditable,
            })
        except:
            pass
    return rows


def group_categories(family_rows):
    groups = {}
    for r in family_rows:
        key = r["category"]
        g = groups.get(key)
        if g is None:
            g = {"name": key, "count": 0, "is_annotation": r["is_annotation"]}
            groups[key] = g
        g["count"] += 1
    return sorted(groups.values(), key=lambda g: g["name"])


def scan_family_fonts(fam):
    """Open a family read-only and report the fonts / width factors of every
    font-bearing type inside it. No transaction: reading a parameter does not
    modify the family document, so nothing here can leave a half-edited
    family behind."""
    fam_doc = doc.EditFamily(fam)
    try:
        fonts = []
        widths = []
        kinds = {}
        count = 0
        for et in font_bearing_types(fam_doc):
            count += 1
            k = type_kind(et)
            kinds[k] = kinds.get(k, 0) + 1
            fp = font_param(et)
            if fp is not None and fp.HasValue:
                value = fp.AsString()
                if value:
                    fonts.append(value)
            wp = width_param(et)
            if wp is not None and wp.HasValue:
                widths.append(wp.AsDouble())
        return count, fonts, widths, kinds
    finally:
        try:
            fam_doc.Close(False)
        except:
            pass


def apply_family_font(fam, target_font, current_filter, width_factor):
    """Set Text Font (when target_font is given) and/or Width Factor (when
    width_factor is given) on every font-bearing type in `fam` that matches
    current_filter (None = every type, regardless of its current font).
    Reloads the family back into `doc` via LoadFamily, which commits its own
    transaction - so a failure on one family cannot roll back families
    already applied. Returns the number of types actually changed."""
    fam_doc = doc.EditFamily(fam)
    try:
        changed = 0
        t = Transaction(fam_doc, "DQT - Change text font")
        t.Start()
        try:
            for et in font_bearing_types(fam_doc):
                fp = font_param(et)
                current = fp.AsString() if (fp is not None and fp.HasValue) else None
                if current_filter and current != current_filter:
                    continue

                touched = False
                if target_font and fp is not None and not fp.IsReadOnly:
                    if current != target_font:
                        fp.Set(target_font)
                        touched = True

                if width_factor is not None:
                    wp = width_param(et)
                    if wp is not None and not wp.IsReadOnly:
                        now = wp.AsDouble() if wp.HasValue else None
                        if now is None or abs(now - width_factor) > 1e-9:
                            wp.Set(width_factor)
                            touched = True

                if touched:
                    changed += 1
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise

        if changed:
            # LoadFamily manages its own transaction on `doc` internally -
            # `doc` must have NO open transaction when this is called, or
            # Revit raises "document must not be modifiable before calling
            # LoadFamily". Do not wrap this call in a Transaction(doc, ...).
            fam_doc.LoadFamily(doc, _OverwriteLoadOptions())
        return changed
    finally:
        try:
            fam_doc.Close(False)
        except:
            pass


# ============================================================================
# DATA MODELS (plain objects - WPF binds to these via reflection)
# ============================================================================
class CategoryRow(object):
    def __init__(self, name, count, is_annotation):
        self.name = name
        self.count = count
        self.selected = is_annotation


class FamilyRow(object):
    def __init__(self, name, category):
        self.name = name
        self.category = category
        self.types_desc = "-"
        self.fonts_found = "-"
        self.widths_found = "-"
        self.status = "not scanned"


_ALL_FONTS = "<All fonts>"


# ============================================================================
# XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Family Font Manager - DQT" Height="770" Width="1160" FontSize="13.2"
        WindowStartupLocation="CenterScreen" Background="#FFFFFF" ResizeMode="CanResize">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#F0CC88" BorderBrush="#D4B87A" BorderThickness="0,0,0,2"
                CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0">
                    <TextBlock Text="Family Font Manager" FontSize="18.7" FontWeight="Bold" Foreground="#5D4E37"/>
                    <TextBlock Text="Batch-change the Text Font and Width Factor used inside annotation, title block and tag families - Labels included, no need to open each one by hand"
                               FontSize="12.1" Foreground="#5D4E37" TextWrapping="Wrap"/>
                </StackPanel>
                <Button Grid.Column="1" Name="btnHelp" Content="? Help" Padding="10,4" Background="White"
                        BorderBrush="#D4B87A" VerticalAlignment="Top" Margin="10,0,0,0"/>
            </Grid>
        </Border>

        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="0,0,4,0">
                <StackPanel><TextBlock Text="FAMILIES SCANNED" FontSize="9" Foreground="#888"/><TextBlock Name="txtStatFamilies" Text="0" FontSize="20" FontWeight="Bold" Foreground="#5D4E37"/></StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,4,0">
                <StackPanel><TextBlock Text="TYPES" FontSize="9" Foreground="#888"/><TextBlock Name="txtStatTypes" Text="0" FontSize="20" FontWeight="Bold" Foreground="#5DADE2"/></StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,4,0">
                <StackPanel><TextBlock Text="DISTINCT FONTS" FontSize="9" Foreground="#888"/><TextBlock Name="txtStatFonts" Text="0" FontSize="20" FontWeight="Bold" Foreground="#E5B85C"/></StackPanel>
            </Border>
            <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4" Padding="10,6" Margin="4,0,0,0">
                <StackPanel><TextBlock Text="ERRORS" FontSize="9" Foreground="#888"/><TextBlock Name="txtStatErrors" Text="0" FontSize="20" FontWeight="Bold" Foreground="#FF6B6B"/></StackPanel>
            </Border>
        </Grid>

        <Grid Grid.Row="2">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="320"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <Border Grid.Column="0" Background="#FFFDF5" BorderBrush="#E0E0E0" BorderThickness="1"
                    CornerRadius="4" Padding="10" Margin="0,0,8,0">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>

                    <TextBlock Grid.Row="0" Text="FAMILY CATEGORIES" FontSize="11" FontWeight="SemiBold"
                               Foreground="#5D4E37" Margin="0,0,0,6"/>

                    <DataGrid Grid.Row="1" Name="dataGridCategories" AutoGenerateColumns="False" IsReadOnly="True"
                              HeadersVisibility="Column" GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#E0E0E0"
                              Background="White" BorderBrush="#D4B87A" BorderThickness="1" RowHeight="26"
                              AlternatingRowBackground="#FAF3E0" SelectionMode="Single" Margin="0,0,0,6">
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
                            <DataGridTextColumn Header="Category" Binding="{Binding name}" Width="*"/>
                            <DataGridTextColumn Header="#" Binding="{Binding count}" Width="38"/>
                        </DataGrid.Columns>
                    </DataGrid>

                    <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,0,0,10">
                        <Button Name="btnCatAnnotation" Content="Annotation only" Padding="6,3" Margin="0,0,4,0" Background="#F0CC88" FontSize="11"/>
                        <Button Name="btnCatAll" Content="All" Padding="6,3" Margin="0,0,4,0" Background="White" FontSize="11" Width="40"/>
                        <Button Name="btnCatNone" Content="None" Padding="6,3" Background="White" FontSize="11" Width="50"/>
                    </StackPanel>

                    <TextBlock Grid.Row="3" Text="TARGET FONT" FontSize="11" FontWeight="SemiBold" Foreground="#5D4E37" Margin="0,0,0,4"/>
                    <ComboBox Grid.Row="4" Name="cmbTargetFont" IsEditable="True" Padding="4" Margin="0,0,0,10"/>

                    <StackPanel Grid.Row="5" Orientation="Horizontal" Margin="0,0,0,10">
                        <CheckBox Name="chkWidthFactor" Content="Also set Width Factor" VerticalAlignment="Center" Foreground="#5D4E37"/>
                        <TextBox Name="txtWidthFactor" Text="1.00" Width="60" Margin="8,0,0,0" Padding="3,2"
                                 BorderBrush="#D4B87A" VerticalContentAlignment="Center"/>
                    </StackPanel>

                    <TextBlock Grid.Row="6" Text="ONLY REPLACE CURRENT FONT (optional, after Scan)" FontSize="11"
                               FontWeight="SemiBold" Foreground="#5D4E37" Margin="0,0,0,4" TextWrapping="Wrap"/>
                    <ComboBox Grid.Row="7" Name="cmbCurrentFilter" Padding="4" Margin="0,0,0,10"/>

                    <Button Grid.Row="8" Name="btnScan" Content="Scan Selected Categories" Padding="8,6" Background="White"
                            BorderBrush="#D4B87A" FontWeight="SemiBold" VerticalAlignment="Bottom"/>
                </Grid>
            </Border>

            <Grid Grid.Column="1">
                <Grid.RowDefinitions>
                    <RowDefinition Height="*"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>

                <DataGrid Grid.Row="0" Name="dataGridFamilies" AutoGenerateColumns="False" IsReadOnly="True"
                          HeadersVisibility="Column" GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#E0E0E0"
                          Background="White" BorderBrush="#D4B87A" BorderThickness="1" RowHeight="26"
                          AlternatingRowBackground="#FAF3E0" SelectionMode="Extended">
                    <DataGrid.ColumnHeaderStyle>
                        <Style TargetType="DataGridColumnHeader">
                            <Setter Property="Background" Value="#F0CC88"/>
                            <Setter Property="Foreground" Value="#5D4E37"/>
                            <Setter Property="FontWeight" Value="SemiBold"/>
                            <Setter Property="Padding" Value="8,4"/>
                        </Style>
                    </DataGrid.ColumnHeaderStyle>
                    <DataGrid.Columns>
                        <DataGridTextColumn Header="Family" Binding="{Binding name}" Width="*"/>
                        <DataGridTextColumn Header="Category" Binding="{Binding category}" Width="140"/>
                        <DataGridTextColumn Header="Types" Binding="{Binding types_desc}" Width="135"/>
                        <DataGridTextColumn Header="Fonts Found" Binding="{Binding fonts_found}" Width="180"/>
                        <DataGridTextColumn Header="Width" Binding="{Binding widths_found}" Width="85"/>
                        <DataGridTextColumn Header="Status" Binding="{Binding status}" Width="130"/>
                    </DataGrid.Columns>
                </DataGrid>

                <TextBlock Grid.Row="1" Name="txtSummary" Text="Select categories on the left, then click Scan to preview."
                           Foreground="#666" Margin="0,6,0,0" TextWrapping="Wrap"/>
            </Grid>
        </Grid>

        <Border Grid.Row="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4"
                Padding="8" Margin="0,10,0,0">
            <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                <Button Name="btnApply" Content="Apply Font Change" Padding="12,6" Margin="0,0,6,0" Background="#F0CC88" FontWeight="SemiBold"/>
                <Button Name="btnClose" Content="Close" Padding="12,6" Background="White"/>
            </StackPanel>
        </Border>

        <TextBlock Grid.Row="4" Text="Dang Quoc Truong - DQT (c) 2026" Foreground="#5D4E37" FontSize="12.1"
                   HorizontalAlignment="Right" Margin="0,6,4,0"/>
    </Grid>
</Window>
"""


# ============================================================================
# MAIN WINDOW
# ============================================================================
class FamilyFontWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, MAIN_XAML, literal_string=True)

        self.family_rows_all = collect_loadable_families()
        self.category_rows = ObservableCollection[object]()
        for g in group_categories(self.family_rows_all):
            self.category_rows.Add(CategoryRow(g["name"], g["count"], g["is_annotation"]))
        self.dataGridCategories.ItemsSource = self.category_rows

        self.family_rows = ObservableCollection[object]()
        self.dataGridFamilies.ItemsSource = self.family_rows

        for f in get_installed_fonts():
            self.cmbTargetFont.Items.Add(f)

        self.cmbCurrentFilter.Items.Add(_ALL_FONTS)
        self.cmbCurrentFilter.SelectedIndex = 0

        # The checkboxes live inside a cell template, so they are not fields
        # on the window - catch their Click as it bubbles up to the grid.
        self.dataGridCategories.AddHandler(
            CheckBox.ClickEvent, RoutedEventHandler(self.on_category_checkbox))
        self.dataGridCategories.MouseDoubleClick += self.on_category_toggle
        self.btnCatAnnotation.Click += self.on_cat_annotation_only
        self.btnCatAll.Click += self.on_cat_all
        self.btnCatNone.Click += self.on_cat_none
        self.btnScan.Click += self.on_scan
        self.btnApply.Click += self.on_apply
        self.btnClose.Click += self.on_close
        self.btnHelp.Click += self.on_help

        # Set by on_apply, read by main() AFTER ShowDialog() returns - the
        # batch itself must not run while this modal window is still up.
        self.apply_requested = None

        n_annotation = sum(1 for r in self.family_rows_all if r["is_annotation"])
        self.txtSummary.Text = (
            "{} loadable family(ies) found, {} in 2D annotation categories. "
            "Tick categories on the left, then click Scan to preview.".format(
                len(self.family_rows_all), n_annotation))

    # -- category checklist -------------------------------------------------
    def on_category_checkbox(self, sender, args):
        """A checkbox in the category grid was clicked. The CheckBox is bound
        OneWay, so the Python object is the single source of truth and is
        updated here - no reliance on WPF writing back to a Python attr."""
        box = None
        for candidate in (args.OriginalSource, args.Source):
            if isinstance(candidate, CheckBox):
                box = candidate
                break
        if box is None:
            return
        row = box.DataContext
        if isinstance(row, CategoryRow):
            row.selected = bool(box.IsChecked)

    def on_category_toggle(self, sender, args):
        row = self.dataGridCategories.CurrentItem
        if row is not None and isinstance(row, CategoryRow):
            row.selected = not row.selected
            self.dataGridCategories.Items.Refresh()

    def on_cat_annotation_only(self, sender, args):
        annotation = self._annotation_category_names()
        for row in self.category_rows:
            row.selected = row.name in annotation
        self.dataGridCategories.Items.Refresh()

    def on_cat_all(self, sender, args):
        for row in self.category_rows:
            row.selected = True
        self.dataGridCategories.Items.Refresh()

    def on_cat_none(self, sender, args):
        for row in self.category_rows:
            row.selected = False
        self.dataGridCategories.Items.Refresh()

    def _annotation_category_names(self):
        return set(r["category"] for r in self.family_rows_all if r["is_annotation"])

    def _selected_categories(self):
        return set(row.name for row in self.category_rows if row.selected)

    def _selected_targets(self):
        cats = self._selected_categories()
        return [r for r in self.family_rows_all if r["category"] in cats]

    def _read_width_factor(self):
        """(ok, value) - value is None when the Width Factor box is off."""
        if not self.chkWidthFactor.IsChecked:
            return True, None
        raw = (self.txtWidthFactor.Text or "").strip()
        try:
            value = float(raw)
        except:
            forms.alert("Width Factor must be a number, for example 0.8.",
                        title="DQT - Family Font Manager")
            return False, None
        if value <= 0 or value > 10:
            forms.alert("Width Factor must be between 0.01 and 10.",
                        title="DQT - Family Font Manager")
            return False, None
        return True, value

    # -- scan (preview, read-only) ------------------------------------------
    def on_scan(self, sender, args):
        targets = self._selected_targets()
        if not targets:
            forms.alert("No categories selected - tick at least one category first.",
                        title="DQT - Family Font Manager")
            return

        self.family_rows.Clear()
        fonts_seen = set()
        kinds_seen = {}
        total_types = 0
        errors = 0
        _log("=" * 50)
        _log("SCAN start - {} family(ies)".format(len(targets)))
        print("DQT - Family Font: scanning {} family(ies)...".format(len(targets)))

        for i, t in enumerate(targets):
            print("  [{}/{}] {}".format(i + 1, len(targets), t["name"]))
            row = FamilyRow(t["name"], t["category"])
            if not t["editable"]:
                row.status = "skipped: not editable"
                self.family_rows.Add(row)
                continue
            fam = doc.GetElement(t["eid"])
            if fam is None:
                row.status = "skipped: no longer valid"
                self.family_rows.Add(row)
                continue
            try:
                count, fonts, widths, kinds = scan_family_fonts(fam)
                breakdown = ", ".join(
                    "{} {}".format(kinds[k], k) for k in sorted(kinds))
                row.types_desc = ("{} ({})".format(count, breakdown)
                                  if breakdown else str(count))
                distinct = sorted(set(f for f in fonts if f))
                row.fonts_found = ", ".join(distinct) if distinct else "-"
                distinct_widths = sorted(set(round(w, 4) for w in widths))
                row.widths_found = (", ".join(_fmt_width(w) for w in distinct_widths)
                                    if distinct_widths else "-")
                row.status = "scanned"
                total_types += count
                fonts_seen.update(distinct)
                for k in kinds:
                    kinds_seen[k] = kinds_seen.get(k, 0) + kinds[k]
            except Exception as ex:
                row.status = "error: {}".format(ex)
                errors += 1
                _log("scan {} (id {}): FAILED {}".format(t["name"], t["id"], ex))
            self.family_rows.Add(row)
        print("DQT - Family Font: scan complete - {} type(s), {} distinct font(s), "
              "{} error(s)".format(total_types, len(fonts_seen), errors))

        _log("SCAN done - {} type(s) ({}), {} distinct font(s), {} error(s)".format(
            total_types,
            ", ".join("{} {}".format(kinds_seen[k], k) for k in sorted(kinds_seen)),
            len(fonts_seen), errors))

        self.cmbCurrentFilter.Items.Clear()
        self.cmbCurrentFilter.Items.Add(_ALL_FONTS)
        for f in sorted(fonts_seen):
            self.cmbCurrentFilter.Items.Add(f)
        self.cmbCurrentFilter.SelectedIndex = 0

        kind_note = ", ".join("{} {}".format(kinds_seen[k], k)
                              for k in sorted(kinds_seen))
        self.txtSummary.Text = (
            "Scanned {} family(ies): {} font-bearing type(s){}, {} distinct "
            "font(s) found{}.".format(
                len(targets), total_types,
                " ({})".format(kind_note) if kind_note else "",
                len(fonts_seen),
                ", {} error(s)".format(errors) if errors else ""))

        self.txtStatFamilies.Text = str(len(targets))
        self.txtStatTypes.Text = str(total_types)
        self.txtStatFonts.Text = str(len(fonts_seen))
        self.txtStatErrors.Text = str(errors)

    # -- apply ----------------------------------------------------------------
    def on_apply(self, sender, args):
        target_font = (self.cmbTargetFont.Text or "").strip()
        ok, width_factor = self._read_width_factor()
        if not ok:
            return
        if not target_font and width_factor is None:
            forms.alert("Pick a target font, or tick \"Also set Width Factor\" "
                        "to change only the width factor.",
                        title="DQT - Family Font Manager")
            return

        targets = self._selected_targets()
        if not targets:
            forms.alert("No categories selected - tick at least one category first.",
                        title="DQT - Family Font Manager")
            return

        current_filter = None
        sel = self.cmbCurrentFilter.SelectedItem
        if sel and sel != _ALL_FONTS:
            current_filter = sel

        changes = []
        if target_font:
            changes.append("Text Font -> \"{}\"".format(target_font))
        if width_factor is not None:
            changes.append("Width Factor -> {}".format(_fmt_width(width_factor)))
        filter_note = (' (only types currently using "{}")'.format(current_filter)
                       if current_filter else "")
        msg = (
            "{} across {} family(ies) in {} selected category(ies){}.\n\n"
            "This covers Text Note Types AND the Label types used by tags, "
            "title blocks and section heads.\n\n"
            "Each family is briefly opened and reloaded in the background - "
            "Revit's screen may flicker between families, this needs no "
            "interaction.\n\n"
            "SAVE the model before continuing.\n\nProceed?"
        ).format(" and ".join(changes), len(targets),
                 len(self._selected_categories()), filter_note)

        if not forms.alert(msg, title="DQT - Family Font Manager", ok=True, cancel=True):
            return

        # Record the request and close - the batch runs in main(), after
        # ShowDialog() returns, never while this modal window is still open.
        self.apply_requested = (targets, target_font, current_filter, width_factor)
        self.Close()

    def on_close(self, sender, args):
        self.Close()

    def on_help(self, sender, args):
        forms.alert(
            "Family Font Manager\n\n"
            "- Tick categories on the left (or use Annotation only / All / None), "
            "then Scan to preview every font-bearing type - Text Note Types and the "
            "Label types used by tags, title blocks and section heads.\n"
            "- Pick a Target Font (and optionally a Width Factor) and, after scanning, "
            "an Only replace current font filter to narrow the change.\n"
            "- Apply Font Change opens, edits and reloads each family in the background - "
            "save the model first.\n\n"
            "Dang Quoc Truong - DQT (c) 2026",
            title="DQT - Family Font Manager")


def _run_batch(targets, target_font, current_filter, width_factor):
    _log("=" * 50)
    _log("RUN start - {} family(ies), font '{}', width {}, filter {}".format(
        len(targets), target_font or "<unchanged>",
        _fmt_width(width_factor) if width_factor is not None else "<unchanged>",
        current_filter or "<all>"))

    processed = 0
    changed_families = 0
    total_types_changed = 0
    skipped = 0
    failed = 0
    fail_details = []

    changes = []
    if target_font:
        changes.append("font \"{}\"".format(target_font))
    if width_factor is not None:
        changes.append("width factor {}".format(_fmt_width(width_factor)))

    print("\n" + "=" * 60)
    print("DQT - FAMILY FONT: setting {} on {} family(ies){}".format(
        " and ".join(changes), len(targets),
        " (filter: current font = \"{}\")".format(current_filter) if current_filter else ""))
    print("Black-box log: {}".format(_LOG_PATH))
    print("=" * 60)

    for i, t in enumerate(targets):
        print("[{}/{}] {}".format(i + 1, len(targets), t["name"]))
        fam = doc.GetElement(t["eid"])
        if fam is None:
            skipped += 1
            print("  SKIPPED: no longer valid")
            _log("family {} (id {}): no longer valid, skipped".format(t["name"], t["id"]))
            continue
        if not fam.IsEditable:
            skipped += 1
            print("  SKIPPED: not editable")
            _log("family {} (id {}): not editable, skipped".format(t["name"], t["id"]))
            continue
        processed += 1
        try:
            changed = apply_family_font(fam, target_font, current_filter, width_factor)
            if changed:
                changed_families += 1
                total_types_changed += changed
            print("  OK: {} type(s) changed".format(changed))
            _log("family {} (id {}): {} type(s) changed".format(
                t["name"], t["id"], changed))
        except Exception as ex:
            failed += 1
            fail_details.append("{}: {}".format(t["name"], ex))
            print("  FAILED: {}".format(ex))
            _log("family {} (id {}): FAILED {}".format(t["name"], t["id"], ex))

    if processed > failed:
        t = Transaction(doc, "DQT - Regenerate after font change")
        t.Start()
        try:
            doc.Regenerate()
            t.Commit()
        except Exception as ex:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            _log("regen: FAILED {}".format(ex))

    _log("RUN end - {} processed, {} changed, {} skipped, {} failed".format(
        processed, changed_families, skipped, failed))

    msg = (
        "Family Font Change Complete!\n\n"
        "Families processed  : {}\n"
        "Families changed    : {}\n"
        "Types changed (text + label) : {}\n"
        "Skipped (not editable/invalid) : {}\n"
        "Failed              : {}\n\n"
        "Log: {}"
    ).format(processed, changed_families, total_types_changed, skipped, failed, _LOG_PATH)

    if fail_details:
        shown = fail_details[:8]
        msg += "\n\nFailures:\n" + "\n".join(shown)
        if len(fail_details) > len(shown):
            msg += "\n... and {} more (see log)".format(len(fail_details) - len(shown))

    forms.alert(msg, title="DQT - Family Font Summary")


def main():
    proceed = forms.alert(
        "Batch-change the Text Font and Width Factor used inside 2D "
        "annotation families (Generic Annotations, Tags, Title Blocks, "
        "Symbols, view/section/grid/level heads, etc.) without opening each "
        "family by hand.\n\n"
        "Method: each selected family is opened in the background "
        "(Document.EditFamily), every type inside it that has a Text Font "
        "parameter is updated, then it is reloaded into the project. This "
        "covers plain Text Note Types AND the \"Tag Label\" types that Labels "
        "in tags, title blocks and section heads actually use.\n\n"
        "SAVE your model first.\n\n"
        "Click OK to open the tool.",
        title="Family Font Manager", ok=True, cancel=True)
    if not proceed:
        return

    window = FamilyFontWindow()
    window.ShowDialog()

    if window.apply_requested:
        targets, target_font, current_filter, width_factor = window.apply_requested
        _run_batch(targets, target_font, current_filter, width_factor)


if __name__ == "__main__":
    main()
