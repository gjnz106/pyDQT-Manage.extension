# -*- coding: utf-8 -*-
"""
Family Font Manager

Batch-changes the Text Font used inside 2D annotation families (Generic
Annotations, Tags, Title Blocks, Symbols, Callout/Elevation/Grid/Level
heads, View Titles, etc.) without opening each family one at a time.

METHOD: for every loadable family whose category is selected, the family is
opened headlessly with Document.EditFamily(), every TextNoteType inside it
has its Text Font parameter changed - TextNoteType is what both plain Text
elements AND Label elements use for their appearance inside a family, so
this covers a tag's visible text and a title block's labels too - then the
family is reloaded into the project with Document.LoadFamily() and the
temporary family document is discarded (never saved to disk).

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
    """Open a family read-only and report its TextNoteTypes' current fonts.
    No transaction: reading a parameter does not modify the family document,
    so nothing here can leave a half-edited family behind."""
    fam_doc = doc.EditFamily(fam)
    try:
        fonts = []
        count = 0
        for tnt in FilteredElementCollector(fam_doc).OfClass(TextNoteType):
            count += 1
            try:
                p = tnt.get_Parameter(BuiltInParameter.TEXT_FONT)
                if p and p.HasValue:
                    fonts.append(p.AsString())
            except:
                pass
        return count, fonts
    finally:
        try:
            fam_doc.Close(False)
        except:
            pass


def apply_family_font(fam, target_font, current_filter):
    """Change TEXT_FONT on every TextNoteType in `fam` that matches
    current_filter (None = every type, regardless of its current font).
    Reloads the family back into `doc` in its own transaction so a failure
    on one family cannot roll back families already applied. Returns the
    number of TextNoteTypes actually changed."""
    fam_doc = doc.EditFamily(fam)
    try:
        changed = 0
        t = Transaction(fam_doc, "DQT - Change text font")
        t.Start()
        try:
            for tnt in FilteredElementCollector(fam_doc).OfClass(TextNoteType):
                p = tnt.get_Parameter(BuiltInParameter.TEXT_FONT)
                if p is None or p.IsReadOnly:
                    continue
                current = p.AsString() if p.HasValue else None
                if current_filter and current != current_filter:
                    continue
                if current == target_font:
                    continue
                p.Set(target_font)
                changed += 1
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise

        if changed:
            t2 = Transaction(doc, "DQT - Reload family {}".format(get_name(fam)))
            t2.Start()
            try:
                fam_doc.LoadFamily(doc, _OverwriteLoadOptions())
                t2.Commit()
            except Exception:
                if t2.HasStarted() and not t2.HasEnded():
                    t2.RollBack()
                raise
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
        self.mark = "[x]" if is_annotation else "[ ]"


class FamilyRow(object):
    def __init__(self, name, category):
        self.name = name
        self.category = category
        self.type_count = 0
        self.fonts_found = "-"
        self.status = "not scanned"


_ALL_FONTS = "<All fonts>"


# ============================================================================
# XAML
# ============================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="Family Font Manager - DQT" Height="700" Width="1050"
        WindowStartupLocation="CenterScreen" Background="#FFFFFF" ResizeMode="CanResize">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Border Grid.Row="0" Background="#F0CC88" BorderBrush="#D4B87A" BorderThickness="0,0,0,2"
                CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
            <StackPanel>
                <TextBlock Text="Family Font Manager" FontSize="17" FontWeight="Bold" Foreground="#5D4E37"/>
                <TextBlock Text="Batch-change the Text Font used inside annotation, title block and tag families - no need to open each one by hand"
                           FontSize="11" Foreground="#5D4E37" TextWrapping="Wrap"/>
            </StackPanel>
        </Border>

        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="290"/>
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
                    </Grid.RowDefinitions>

                    <TextBlock Grid.Row="0" Text="FAMILY CATEGORIES" FontSize="10" FontWeight="SemiBold"
                               Foreground="#5D4E37" Margin="0,0,0,6"/>

                    <DataGrid Grid.Row="1" Name="dataGridCategories" AutoGenerateColumns="False" IsReadOnly="True"
                              HeadersVisibility="Column" GridLinesVisibility="Horizontal" HorizontalGridLinesBrush="#E0E0E0"
                              Background="White" BorderBrush="#D4B87A" BorderThickness="1" RowHeight="24"
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
                            <DataGridTextColumn Header="" Binding="{Binding mark}" Width="28" FontFamily="Consolas"/>
                            <DataGridTextColumn Header="Category" Binding="{Binding name}" Width="*"/>
                            <DataGridTextColumn Header="#" Binding="{Binding count}" Width="35"/>
                        </DataGrid.Columns>
                    </DataGrid>

                    <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,0,0,10">
                        <Button Name="btnCatAnnotation" Content="Annotation only" Padding="6,3" Margin="0,0,4,0" Background="#F0CC88" FontSize="10"/>
                        <Button Name="btnCatAll" Content="All" Padding="6,3" Margin="0,0,4,0" Background="White" FontSize="10" Width="35"/>
                        <Button Name="btnCatNone" Content="None" Padding="6,3" Background="White" FontSize="10" Width="45"/>
                    </StackPanel>

                    <TextBlock Grid.Row="3" Text="TARGET FONT" FontSize="10" FontWeight="SemiBold" Foreground="#5D4E37" Margin="0,0,0,4"/>
                    <ComboBox Grid.Row="4" Name="cmbTargetFont" IsEditable="True" Padding="4" Margin="0,0,0,10"/>

                    <TextBlock Grid.Row="5" Text="ONLY REPLACE CURRENT FONT (optional, after Scan)" FontSize="10"
                               FontWeight="SemiBold" Foreground="#5D4E37" Margin="0,0,0,4" TextWrapping="Wrap"/>
                    <ComboBox Grid.Row="6" Name="cmbCurrentFilter" Padding="4" Margin="0,0,0,10"/>

                    <Button Grid.Row="7" Name="btnScan" Content="Scan Selected Categories" Padding="8,6" Background="White"
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
                          Background="White" BorderBrush="#D4B87A" BorderThickness="1"
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
                        <DataGridTextColumn Header="Category" Binding="{Binding category}" Width="150"/>
                        <DataGridTextColumn Header="Text Types" Binding="{Binding type_count}" Width="75"/>
                        <DataGridTextColumn Header="Fonts Found" Binding="{Binding fonts_found}" Width="200"/>
                        <DataGridTextColumn Header="Status" Binding="{Binding status}" Width="140"/>
                    </DataGrid.Columns>
                </DataGrid>

                <TextBlock Grid.Row="1" Name="txtSummary" Text="Select categories on the left, then click Scan to preview."
                           Foreground="#666" Margin="0,6,0,0"/>
            </Grid>
        </Grid>

        <Border Grid.Row="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1" CornerRadius="4"
                Padding="8" Margin="0,10,0,0">
            <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                <Button Name="btnApply" Content="Apply Font Change" Padding="12,6" Margin="0,0,6,0" Background="#F0CC88" FontWeight="SemiBold"/>
                <Button Name="btnClose" Content="Close" Padding="12,6" Background="White"/>
            </StackPanel>
        </Border>

        <TextBlock Grid.Row="3" Text="Dang Quoc Truong - DQT (c) 2026" Foreground="#5D4E37" FontSize="11"
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

        self.dataGridCategories.MouseDoubleClick += self.on_category_toggle
        self.btnCatAnnotation.Click += self.on_cat_annotation_only
        self.btnCatAll.Click += self.on_cat_all
        self.btnCatNone.Click += self.on_cat_none
        self.btnScan.Click += self.on_scan
        self.btnApply.Click += self.on_apply
        self.btnClose.Click += self.on_close

        # Set by on_apply, read by main() AFTER ShowDialog() returns - the
        # batch itself must not run while this modal window is still up.
        self.apply_requested = None

        n_annotation = sum(1 for r in self.family_rows_all if r["is_annotation"])
        self.txtSummary.Text = (
            "{} loadable family(ies) found, {} in 2D annotation categories. "
            "Select categories on the left, then click Scan to preview.".format(
                len(self.family_rows_all), n_annotation))

    # -- category checklist -------------------------------------------------
    def on_category_toggle(self, sender, args):
        row = self.dataGridCategories.CurrentItem
        if row is not None:
            row.selected = not row.selected
            row.mark = "[x]" if row.selected else "[ ]"
            self.dataGridCategories.Items.Refresh()

    def on_cat_annotation_only(self, sender, args):
        for row in self.category_rows:
            row.selected = row.name in self._annotation_category_names()
            row.mark = "[x]" if row.selected else "[ ]"
        self.dataGridCategories.Items.Refresh()

    def on_cat_all(self, sender, args):
        for row in self.category_rows:
            row.selected = True
            row.mark = "[x]"
        self.dataGridCategories.Items.Refresh()

    def on_cat_none(self, sender, args):
        for row in self.category_rows:
            row.selected = False
            row.mark = "[ ]"
        self.dataGridCategories.Items.Refresh()

    def _annotation_category_names(self):
        return set(r["category"] for r in self.family_rows_all if r["is_annotation"])

    def _selected_categories(self):
        return set(row.name for row in self.category_rows if row.selected)

    def _selected_targets(self):
        cats = self._selected_categories()
        return [r for r in self.family_rows_all if r["category"] in cats]

    # -- scan (preview, read-only) ------------------------------------------
    def on_scan(self, sender, args):
        targets = self._selected_targets()
        if not targets:
            forms.alert("No categories selected - tick at least one category first.",
                        title="DQT - Family Font Manager")
            return

        self.family_rows.Clear()
        fonts_seen = set()
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
                count, fonts = scan_family_fonts(fam)
                row.type_count = count
                distinct = sorted(set(f for f in fonts if f))
                row.fonts_found = ", ".join(distinct) if distinct else "-"
                row.status = "scanned"
                total_types += count
                fonts_seen.update(distinct)
            except Exception as ex:
                row.status = "error: {}".format(ex)
                errors += 1
                _log("scan {} (id {}): FAILED {}".format(t["name"], t["id"], ex))
            self.family_rows.Add(row)
        print("DQT - Family Font: scan complete - {} type(s), {} distinct font(s), "
              "{} error(s)".format(total_types, len(fonts_seen), errors))

        _log("SCAN done - {} type(s), {} distinct font(s), {} error(s)".format(
            total_types, len(fonts_seen), errors))

        self.cmbCurrentFilter.Items.Clear()
        self.cmbCurrentFilter.Items.Add(_ALL_FONTS)
        for f in sorted(fonts_seen):
            self.cmbCurrentFilter.Items.Add(f)
        self.cmbCurrentFilter.SelectedIndex = 0

        self.txtSummary.Text = (
            "Scanned {} family(ies): {} text type(s), {} distinct font(s) found"
            "{}.".format(len(targets), total_types, len(fonts_seen),
                        ", {} error(s)".format(errors) if errors else ""))

    # -- apply ----------------------------------------------------------------
    def on_apply(self, sender, args):
        target_font = (self.cmbTargetFont.Text or "").strip()
        if not target_font:
            forms.alert("Type or pick a target font first.", title="DQT - Family Font Manager")
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

        filter_note = (' (only text types currently using "{}")'.format(current_filter)
                       if current_filter else "")
        msg = (
            "Change Text Font to \"{}\" across {} family(ies) in {} selected "
            "category(ies){}.\n\n"
            "Each family is briefly opened and reloaded in the background - "
            "Revit's screen may flicker between families, this needs no "
            "interaction.\n\n"
            "SAVE the model before continuing.\n\nProceed?"
        ).format(target_font, len(targets), len(self._selected_categories()), filter_note)

        if not forms.alert(msg, title="DQT - Family Font Manager", ok=True, cancel=True):
            return

        # Record the request and close - the batch runs in main(), after
        # ShowDialog() returns, never while this modal window is still open.
        self.apply_requested = (targets, target_font, current_filter)
        self.Close()

    def on_close(self, sender, args):
        self.Close()


def _run_batch(targets, target_font, current_filter):
    _log("=" * 50)
    _log("RUN start - {} family(ies), target font '{}', filter {}".format(
        len(targets), target_font, current_filter or "<all>"))

    processed = 0
    changed_families = 0
    total_types_changed = 0
    skipped = 0
    failed = 0
    fail_details = []

    print("\n" + "=" * 60)
    print("DQT - FAMILY FONT: changing {} family(ies) to \"{}\"{}".format(
        len(targets), target_font,
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
            changed = apply_family_font(fam, target_font, current_filter)
            if changed:
                changed_families += 1
                total_types_changed += changed
            print("  OK: {} text type(s) changed".format(changed))
            _log("family {} (id {}): {} text type(s) changed".format(
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
        "Text types changed  : {}\n"
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
        "Batch-change the Text Font used inside 2D annotation families "
        "(Generic Annotations, Tags, Title Blocks, Symbols, view/section/"
        "grid/level heads, etc.) without opening each family by hand.\n\n"
        "Method: each selected family is opened in the background "
        "(Document.EditFamily), every Text Note Type inside it gets the new "
        "font, then it is reloaded into the project. This also changes "
        "Label text, since Labels use the family's Text Note Types too.\n\n"
        "SAVE your model first.\n\n"
        "Click OK to open the tool.",
        title="Family Font Manager", ok=True, cancel=True)
    if not proceed:
        return

    window = FamilyFontWindow()
    window.ShowDialog()

    if window.apply_requested:
        targets, target_font, current_filter = window.apply_requested
        _run_batch(targets, target_font, current_filter)


if __name__ == "__main__":
    main()
