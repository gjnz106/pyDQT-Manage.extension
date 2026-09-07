# -*- coding: utf-8 -*-
"""
Batch Purge Families v1.0 - DQT
Opens every .rfa in a folder, purges unused elements until the file is clean,
saves it back and reports how many purgeable elements remain.

Compatible: Revit 2024+ (Document.GetUnusedElements) - pyRevit / IronPython

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "Purge\nFamilies"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = ("Batch-purge every .rfa file in a folder until Revit reports no "
           "purgeable elements left, then report what remains.")

import os
import re
import zipfile
import datetime

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")   # FolderBrowserDialog + DoEvents only

import System.IO                            # DirectoryInfo / FileInfo for backups

from Autodesk.Revit.DB import (
    OpenOptions, SaveAsOptions, ModelPathUtils,
    FailureProcessingResult, IFailuresPreprocessor, FailureSeverity,
    Transaction, DetachFromCentralOption
)
import Autodesk.Revit.DB as DB

from System.Collections.Generic import HashSet

from System.Windows.Forms import FolderBrowserDialog
from System.Windows.Forms import DialogResult as FDResult
from System.Windows.Forms import Application as WFApp

import System
from System.Windows import (
    Window, Thickness, FontWeights,
    MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult,
    HorizontalAlignment, VerticalAlignment, Visibility
)
from System.Windows.Controls import (
    DockPanel, StackPanel, Border, ScrollViewer,
    TextBlock, TextBox, Button, CheckBox, RadioButton,
    ListBox, ListBoxItem, ProgressBar,
    Orientation, ScrollBarVisibility, SelectionMode
)

# Shared with Family Manager's rename dialog - one source for how a new name
# is built, so the two tools cannot drift apart.
from dqt_name_ops import (
    is_revit_backup as _is_revit_backup,
    plan_renames, apply_renames,
)
from System.Windows.Media import SolidColorBrush, Color, FontFamily

app = __revit__.Application


# ===========================================================================
#  DQT BRAND COLORS
# ===========================================================================
def _c(r, g, b):
    return Color.FromRgb(r, g, b)


CLR_HEADER      = _c(240, 204, 136)   # #F0CC88  gold header
CLR_HEADER_TEXT = _c( 51,  51,  51)   # #333333
CLR_HEADER_SUB  = _c(102, 102, 102)   # #666666
CLR_ACCENT      = _c( 93,  78,  55)   # #5D4E37
CLR_BG          = _c(254, 248, 231)   # #FEF8E7  cream window background
CLR_CARD        = _c(255, 255, 255)   # #FFFFFF
CLR_BORDER      = _c(212, 184, 122)   # #D4B87A
CLR_FOOTER      = _c(245, 240, 224)   # #F5F0E0
CLR_TEXT        = _c( 51,  51,  51)   # #333333
CLR_MUTED       = _c(153, 153, 153)   # #999999
CLR_ALT         = _c(255, 248, 238)   # #FFF8EE
CLR_LIST_BG     = _c(255, 253, 245)
CLR_APPLY_BG    = _c(200, 230, 201)   # #C8E6C9
CLR_APPLY_BDR   = _c(129, 199, 132)   # #81C784
CLR_APPLY_TEXT  = _c( 46, 125,  50)   # #2E7D32
CLR_WARN_TEXT   = _c(180, 110,  20)   # amber - "purged but not empty"
CLR_ERR_TEXT    = _c(180,  50,  50)

FONT_UI   = FontFamily("Segoe UI")
FONT_MONO = FontFamily("Consolas")

FOOTER_TEXT = "Dang Quoc Truong - DQT (c) 2026"


def _open_help_page(html_filename):
    """Open this tool's page from the shared _Cleanup_Help folder in the
    default browser. Returns True on success, False if the caller should
    fall back to the in-app help text (e.g. the folder went missing)."""
    try:
        panel_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(panel_dir, "_Cleanup_Help", html_filename)
        if not os.path.isfile(path):
            return False
        os.startfile(path)
        return True
    except Exception:
        return False


# ===========================================================================
#  Failure preprocessor - dismiss warnings so the batch never blocks
# ===========================================================================
class SilentFailurePreprocessor(IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                fa.ResolveFailure(f)
        return FailureProcessingResult.Continue


def _apply_failure_handler(transaction):
    opts = transaction.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(SilentFailurePreprocessor())
    transaction.SetFailureHandlingOptions(opts)


# ===========================================================================
#  PURGE ENGINE
#
#  Everything purgeable comes from Document.GetUnusedElements() - the same
#  source the native Purge Unused dialog reads. Deliberately no hand-rolled
#  "is this element used?" heuristics: reference counting in Revit spans
#  compound structures, paint, type parameters, appearance assets and nested
#  families, and a partial scan does not under-purge, it deletes elements that
#  ARE in use.
# ===========================================================================
def get_unused_ids(doc):
    """Ids Revit itself considers purgeable, or None when the API is missing
    (Revit 2023 and earlier). An empty category set means 'all categories'."""
    try:
        return doc.GetUnusedElements(HashSet[DB.ElementId]())
    except Exception:
        return None


def count_ids(ids):
    if ids is None:
        return 0
    try:
        return ids.Count
    except AttributeError:
        return len(list(ids))


def delete_ids(doc, ids, label):
    """Delete a batch, falling back to one-at-a-time if Revit refuses the
    whole set - one protected element must not block the other thousands."""
    transaction = Transaction(doc, "DQT - Purge Families ({})".format(label))
    _apply_failure_handler(transaction)
    try:
        transaction.Start()
        doc.Delete(ids)
        transaction.Commit()
        return count_ids(ids)
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass

    deleted = 0
    for eid in list(ids):
        single = Transaction(doc, "DQT - Purge Families (single)")
        _apply_failure_handler(single)
        try:
            single.Start()
            doc.Delete(eid)
            single.Commit()
            deleted += 1
        except Exception:
            try:
                single.RollBack()
            except Exception:
                pass
    return deleted


def purge_open_document(doc, max_passes):
    """Purge one already-open document until nothing more can be removed.

    Deleting one element can make others purgeable, so this repeats. It stops
    when Revit reports nothing unused, or when a pass removes nothing - at
    that point what is left is protected, and repeating would just spin.

    Returns (deleted, remaining, passes_used)."""
    deleted_total = 0
    passes_used = 0

    for i in range(max_passes):
        ids = get_unused_ids(doc)
        if ids is None:
            return deleted_total, -1, passes_used     # API unavailable
        if count_ids(ids) == 0:
            break

        passes_used = i + 1
        deleted = delete_ids(doc, ids, "pass {}".format(passes_used))
        deleted_total += deleted
        if deleted == 0:
            break

    remaining = count_ids(get_unused_ids(doc))
    return deleted_total, remaining, passes_used


def process_family_file(filepath, max_passes=10, max_cycles=3):
    """Open, purge, save, and reopen a .rfa until a freshly opened copy has
    nothing left to purge.

    The reopen matters: Revit finalises part of its reference bookkeeping when
    a document is written, so elements that were still held after an in-memory
    purge become purgeable only once the file has been saved and read back.
    Purging in a single open session - which is what a one-shot tool does -
    reliably leaves that second tier behind, which is exactly what the native
    Purge Unused dialog then still lists afterwards.

    Returns a result dict used by the list, the summary and the Excel log."""
    result = {
        "file": os.path.basename(filepath),
        "path": filepath,
        "status": "Pending",
        "purged_count": 0,
        "passes": 0,
        "cycles": 0,
        "remaining": -1,
        "error": "",
        "size_before": 0,
        "size_after": 0,
        "time": "",
    }

    try:
        result["size_before"] = os.path.getsize(filepath) // 1024
    except Exception:
        pass

    model_path = None
    try:
        model_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(filepath)
    except Exception as ex:
        result["status"] = "Error"
        result["error"] = "Bad path: {}".format(ex)
        return result

    open_opts = OpenOptions()
    try:
        open_opts.DetachFromCentralOption = DetachFromCentralOption.DoNotDetach
    except Exception:
        pass

    save_opts = SaveAsOptions()
    save_opts.OverwriteExistingFile = True
    try:
        # One backup instead of the default 3 - this tool rewrites every file
        # in the folder, so the default would triple the clutter it creates.
        save_opts.MaximumBackups = 1
    except Exception:
        pass

    total_purged = 0
    max_passes_used = 0
    remaining = -1

    try:
        for cycle in range(max(1, max_cycles)):
            doc = None
            try:
                doc = app.OpenDocumentFile(model_path, open_opts)
                if doc is None:
                    result["status"] = "Error"
                    result["error"] = "Could not open file"
                    return result

                result["cycles"] = cycle + 1
                deleted, remaining, passes = purge_open_document(doc, max_passes)
                total_purged += deleted
                if passes > max_passes_used:
                    max_passes_used = passes

                if remaining == -1:
                    doc.Close(False)
                    result["status"] = "Error"
                    result["error"] = ("GetUnusedElements is unavailable - "
                                       "Revit 2024 or newer is required")
                    return result

                if deleted > 0:
                    doc.SaveAs(filepath, save_opts)
                doc.Close(False)

                # A freshly opened copy had nothing to remove: the file is done.
                if deleted == 0:
                    break
            except Exception:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
                raise

        result["purged_count"] = total_purged
        result["passes"] = max_passes_used
        result["remaining"] = remaining
        try:
            result["size_after"] = os.path.getsize(filepath) // 1024
        except Exception:
            result["size_after"] = result["size_before"]

        # "Success" is reserved for files that actually reached zero; anything
        # Revit still refuses to purge is reported rather than glossed over.
        result["status"] = "Success" if remaining == 0 else "Partial"

    except Exception as ex:
        result["status"] = "Error"
        result["error"] = str(ex)

    return result


# ===========================================================================
#  Backup file deletion - System.IO handles long paths / read-only attributes
#  that os.remove() silently fails on.
# ===========================================================================
def delete_backup_files(folder, recursive):
    """Delete Revit backups (*.0001.rfa / *.0001.rvt) under folder.
    Returns (deleted_count, freed_bytes, failed list of (name, error))."""
    counters = [0, 0]     # IronPython 2.7 has no 'nonlocal'
    failed = []

    def _process_dir(dir_path):
        try:
            dir_info = System.IO.DirectoryInfo(dir_path)
        except Exception:
            return

        if recursive:
            try:
                for sub_dir in dir_info.GetDirectories():
                    _process_dir(sub_dir.FullName)
            except Exception:
                pass

        try:
            for file_info in dir_info.EnumerateFiles():
                if _is_revit_backup(file_info.Name):
                    size = file_info.Length
                    try:
                        file_info.Delete()
                        counters[0] += 1
                        counters[1] += size
                    except Exception as ex:
                        failed.append((file_info.Name, str(ex)))
        except Exception:
            pass

    _process_dir(folder)
    return counters[0], counters[1], failed


# ===========================================================================
#  Excel export - Open XML written by hand.
#  openpyxl is a CPython library and cannot be imported under IronPython 2.7,
#  so the .xlsx (which is just a ZIP of XML) is assembled directly.
# ===========================================================================
def _xml_escape(s):
    s = str(s)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&apos;")
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)


def _xlsx_cell(col, row, value, style_id=0):
    cell_ref = "{}{}".format(col, row)
    s_attr = ' s="{}"'.format(style_id) if style_id else ''

    try:
        num = float(value) if value != "" else None
    except (ValueError, TypeError):
        num = None

    if num is not None and value != "":
        return '<c r="{}"{}><v>{}</v></c>'.format(cell_ref, s_attr, num)
    return '<c r="{}"{} t="inlineStr"><is><t>{}</t></is></c>'.format(
        cell_ref, s_attr, _xml_escape(value))


_COLS = ["A", "B", "C", "D", "E", "F", "G", "H"]

_HEADERS = [
    "File Name",
    "Status",
    "Elements Purged",
    "Remaining Unused",
    "Passes",
    "Size Before (KB)",
    "Size After (KB)",
    "Saved (KB)",
]

_COL_WIDTHS = [38, 10, 17, 18, 8, 17, 16, 12]


def export_excel(results, out_path):
    """Write the results table to out_path. Returns (ok, error_message)."""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml"  ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
        ' Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
        ' Target="styles.xml"/>'
        '</Relationships>'
    )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Purge Log" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="10"/><name val="Segoe UI"/></font>'
        '<font><b/><sz val="10"/><name val="Segoe UI"/><color rgb="FF5D4E37"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF0CC88"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left   style="thin"><color rgb="FFD4B87A"/></left>'
        '<right  style="thin"><color rgb="FFD4B87A"/></right>'
        '<top    style="thin"><color rgb="FFD4B87A"/></top>'
        '<bottom style="thin"><color rgb="FFD4B87A"/></bottom>'
        '<diagonal/>'
        '</border>'
        '</borders>'
        '<cellStyleXfs count="1">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '</cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"><alignment wrapText="0"/></xf>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0">'
        '<alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0">'
        '<alignment horizontal="right"/></xf>'
        '</cellXfs>'
        '</styleSheet>'
    )

    col_defs = "".join(
        '<col min="{c}" max="{c}" width="{w}" customWidth="1"/>'.format(
            c=i + 1, w=_COL_WIDTHS[i])
        for i in range(len(_COLS))
    )

    header_cells = "".join(
        _xlsx_cell(_COLS[i], 1, _HEADERS[i], style_id=1)
        for i in range(len(_HEADERS))
    )
    rows_xml = '<row r="1" ht="18" customHeight="1">{}</row>'.format(header_cells)

    numeric_cols = {2, 3, 4, 5, 6, 7}
    for row_idx, r in enumerate(results):
        saved_kb = r.get("size_before", 0) - r.get("size_after", 0)
        remaining = r.get("remaining", -1)
        values = [
            r.get("file", ""),
            r.get("status", ""),
            r.get("purged_count", 0),
            remaining if remaining >= 0 else "n/a",
            r.get("passes", 0),
            r.get("size_before", 0),
            r.get("size_after", 0),
            saved_kb,
        ]
        excel_row = row_idx + 2
        cells = "".join(
            _xlsx_cell(_COLS[i], excel_row, values[i],
                       style_id=2 if i in numeric_cols else 0)
            for i in range(len(_COLS))
        )
        rows_xml += '<row r="{}">{}</row>'.format(excel_row, cells)

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0" showGridLines="1"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols>{}</cols>'
        '<sheetData>{}</sheetData>'
        '</worksheet>'
    ).format(col_defs, rows_xml)

    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", rels)
            zf.writestr("xl/workbook.xml", workbook)
            zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
            zf.writestr("xl/styles.xml", styles)
            zf.writestr("xl/worksheets/sheet1.xml", sheet)
        return True, ""
    except Exception as ex:
        return False, str(ex)


# ===========================================================================
#  WPF helpers
# ===========================================================================
def _tb(text, size=11, bold=False, color=None, font=None, wrap=False):
    t = TextBlock()
    t.Text = text
    t.FontSize = size
    t.FontFamily = font or FONT_UI
    t.FontWeight = FontWeights.SemiBold if bold else FontWeights.Normal
    t.Foreground = SolidColorBrush(color if color else CLR_TEXT)
    if wrap:
        t.TextWrapping = System.Windows.TextWrapping.Wrap
    return t


def _section_lbl(text):
    t = TextBlock()
    t.Text = text.upper()
    t.FontSize = 9
    t.FontFamily = FONT_UI
    t.FontWeight = FontWeights.SemiBold
    t.Foreground = SolidColorBrush(CLR_ACCENT)
    t.Margin = Thickness(0, 0, 0, 5)
    return t


def _card(child, margin=None):
    b = Border()
    b.Child = child
    b.Background = SolidColorBrush(CLR_CARD)
    b.BorderBrush = SolidColorBrush(CLR_BORDER)
    b.BorderThickness = Thickness(1)
    b.CornerRadius = System.Windows.CornerRadius(4)
    b.Padding = Thickness(12)
    if margin:
        b.Margin = Thickness(*margin) if isinstance(margin, tuple) else margin
    return b


def _btn(text, bg, fg, bdr=None, h=30, w=None, bold=False, size=11):
    b = Button()
    b.Content = text
    b.Height = h
    b.FontSize = size
    b.FontFamily = FONT_UI
    b.FontWeight = FontWeights.SemiBold if bold else FontWeights.Normal
    b.Background = SolidColorBrush(bg)
    b.Foreground = SolidColorBrush(fg)
    b.BorderBrush = SolidColorBrush(bdr if bdr else CLR_BORDER)
    b.BorderThickness = Thickness(1)
    b.Padding = Thickness(10, 0, 10, 0)
    b.Cursor = System.Windows.Input.Cursors.Hand
    if w:
        b.Width = w
    return b


def _chk(label, checked=False):
    c = CheckBox()
    c.Content = label
    c.FontSize = 11
    c.FontFamily = FONT_UI
    c.Foreground = SolidColorBrush(CLR_TEXT)
    c.IsChecked = checked
    c.VerticalAlignment = VerticalAlignment.Center
    return c


def _num_box(value, width=38):
    t = TextBox()
    t.Text = str(value)
    t.FontSize = 11
    t.Width = width
    t.Height = 26
    t.TextAlignment = System.Windows.TextAlignment.Center
    t.BorderBrush = SolidColorBrush(CLR_BORDER)
    t.BorderThickness = Thickness(1)
    t.VerticalContentAlignment = VerticalAlignment.Center
    return t


def _labelled_box(label, width, tooltip=None):
    """A small caption with its text box, as one horizontal unit."""
    panel = StackPanel()
    panel.Orientation = Orientation.Horizontal
    panel.Margin = Thickness(0, 0, 14, 0)

    caption = _tb(label, size=10, color=CLR_MUTED)
    caption.VerticalAlignment = VerticalAlignment.Center
    caption.Margin = Thickness(0, 0, 5, 0)
    panel.Children.Add(caption)

    box = TextBox()
    box.Width = width
    box.Height = 26
    box.FontSize = 11
    box.FontFamily = FONT_UI
    box.BorderBrush = SolidColorBrush(CLR_BORDER)
    box.BorderThickness = Thickness(1)
    box.Padding = Thickness(4, 0, 4, 0)
    box.VerticalContentAlignment = VerticalAlignment.Center
    if tooltip:
        box.ToolTip = tooltip
    panel.Children.Add(box)
    return panel, box


def _radio(label, group, checked=False):
    r = RadioButton()
    r.Content = label
    r.GroupName = group
    r.IsChecked = checked
    r.FontSize = 11
    r.FontFamily = FONT_UI
    r.Foreground = SolidColorBrush(CLR_TEXT)
    r.VerticalAlignment = VerticalAlignment.Center
    r.Margin = Thickness(0, 0, 12, 0)
    r.Cursor = System.Windows.Input.Cursors.Hand
    return r


def _read_int(text_box, default, low, high):
    try:
        return max(low, min(high, int(text_box.Text.strip())))
    except Exception:
        return default


# ===========================================================================
#  Main window
# ===========================================================================
class PurgeFamiliesWindow(Window):

    def __init__(self):
        self.Title = "Batch Purge Families v1.0 - DQT"
        self.Width = 900
        self.Height = 820
        self.MinWidth = 760
        self.MinHeight = 600
        self.WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen
        self.ResizeMode = System.Windows.ResizeMode.CanResize
        self.Background = SolidColorBrush(CLR_BG)
        self.family_files = []
        self.results = []
        self.Content = self._build_root()

    def _build_root(self):
        root = DockPanel()
        root.LastChildFill = True

        header = self._make_header()
        DockPanel.SetDock(header, System.Windows.Controls.Dock.Top)
        root.Children.Add(header)

        footer = self._make_footer()
        DockPanel.SetDock(footer, System.Windows.Controls.Dock.Bottom)
        root.Children.Add(footer)

        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        sv.Content = self._make_body()
        root.Children.Add(sv)
        return root

    # -- header -------------------------------------------------------------
    def _make_header(self):
        hdr = Border()
        hdr.Background = SolidColorBrush(CLR_HEADER)
        hdr.Padding = Thickness(16, 0, 16, 0)

        dp = DockPanel()
        dp.LastChildFill = False

        right_sp = StackPanel()
        right_sp.Orientation = Orientation.Horizontal
        right_sp.VerticalAlignment = VerticalAlignment.Center

        btn_help = Button()
        btn_help.Content = "?"
        btn_help.Width = 24
        btn_help.Height = 24
        btn_help.FontSize = 12
        btn_help.FontWeight = FontWeights.Bold
        btn_help.FontFamily = FONT_UI
        btn_help.Background = SolidColorBrush(_c(212, 168, 80))
        btn_help.Foreground = SolidColorBrush(CLR_HEADER_TEXT)
        btn_help.BorderBrush = SolidColorBrush(CLR_ACCENT)
        btn_help.BorderThickness = Thickness(1)
        btn_help.Cursor = System.Windows.Input.Cursors.Hand
        btn_help.Click += self.on_help
        btn_help.Margin = Thickness(0, 0, 12, 0)
        right_sp.Children.Add(btn_help)

        badge = StackPanel()
        badge.Orientation = Orientation.Vertical
        badge.VerticalAlignment = VerticalAlignment.Center
        badge.HorizontalAlignment = HorizontalAlignment.Right

        b1 = TextBlock()
        b1.Text = "DQT"
        b1.FontSize = 15
        b1.FontWeight = FontWeights.Bold
        b1.FontFamily = FONT_UI
        b1.Foreground = SolidColorBrush(CLR_ACCENT)
        b1.HorizontalAlignment = HorizontalAlignment.Right
        badge.Children.Add(b1)

        b2 = TextBlock()
        b2.Text = "Revit 2024+"
        b2.FontSize = 9
        b2.FontFamily = FONT_UI
        b2.Foreground = SolidColorBrush(CLR_HEADER_SUB)
        b2.HorizontalAlignment = HorizontalAlignment.Right
        badge.Children.Add(b2)

        right_sp.Children.Add(badge)
        DockPanel.SetDock(right_sp, System.Windows.Controls.Dock.Right)
        dp.Children.Add(right_sp)

        center = StackPanel()
        center.Orientation = Orientation.Vertical
        center.VerticalAlignment = VerticalAlignment.Center
        center.Margin = Thickness(0, 12, 0, 12)

        t1 = TextBlock()
        t1.Text = "Batch Purge Families"
        t1.FontSize = 17
        t1.FontWeight = FontWeights.Bold
        t1.FontFamily = FONT_UI
        t1.Foreground = SolidColorBrush(CLR_HEADER_TEXT)
        center.Children.Add(t1)

        t2 = TextBlock()
        t2.Text = "Purge every .rfa in a folder until nothing purgeable is left"
        t2.FontSize = 10
        t2.FontFamily = FONT_UI
        t2.Foreground = SolidColorBrush(CLR_HEADER_SUB)
        t2.Margin = Thickness(0, 2, 0, 0)
        center.Children.Add(t2)

        DockPanel.SetDock(center, System.Windows.Controls.Dock.Left)
        dp.Children.Add(center)

        hdr.Child = dp
        return hdr

    # -- footer -------------------------------------------------------------
    def _make_footer(self):
        ftr = Border()
        ftr.Background = SolidColorBrush(CLR_FOOTER)
        ftr.BorderBrush = SolidColorBrush(CLR_BORDER)
        ftr.BorderThickness = Thickness(0, 1, 0, 0)
        ftr.Padding = Thickness(14, 8, 14, 8)

        dp = DockPanel()
        dp.LastChildFill = True

        btn_row = StackPanel()
        btn_row.Orientation = Orientation.Horizontal

        self.btn_export = _btn("Export Excel Log", CLR_CARD, CLR_TEXT)
        self.btn_export.Margin = Thickness(0, 0, 8, 0)
        self.btn_export.IsEnabled = False
        self.btn_export.Click += self.on_export
        btn_row.Children.Add(self.btn_export)

        btn_close = _btn("Close", CLR_CARD, CLR_TEXT)
        btn_close.Click += lambda s, e: self.Close()
        btn_row.Children.Add(btn_close)

        DockPanel.SetDock(btn_row, System.Windows.Controls.Dock.Right)
        dp.Children.Add(btn_row)

        left = StackPanel()
        left.Orientation = Orientation.Vertical
        left.VerticalAlignment = VerticalAlignment.Center

        self.lbl_status = TextBlock()
        self.lbl_status.Text = "Ready."
        self.lbl_status.FontSize = 10
        self.lbl_status.FontFamily = FONT_UI
        self.lbl_status.Foreground = SolidColorBrush(CLR_MUTED)
        self.lbl_status.TextTrimming = System.Windows.TextTrimming.CharacterEllipsis
        left.Children.Add(self.lbl_status)

        copyright_lbl = TextBlock()
        copyright_lbl.Text = FOOTER_TEXT
        copyright_lbl.FontSize = 9
        copyright_lbl.FontFamily = FONT_UI
        copyright_lbl.Foreground = SolidColorBrush(CLR_ACCENT)
        copyright_lbl.Margin = Thickness(0, 2, 0, 0)
        left.Children.Add(copyright_lbl)

        dp.Children.Add(left)
        ftr.Child = dp
        return ftr

    # -- body ---------------------------------------------------------------
    def _make_body(self):
        body = StackPanel()
        body.Orientation = Orientation.Vertical
        body.Margin = Thickness(15)
        body.Children.Add(self._make_card_folder())
        body.Children.Add(self._make_card_scan())
        body.Children.Add(self._make_card_rename())
        body.Children.Add(self._make_card_progress())
        body.Children.Add(self._make_card_actions())
        return body

    def _make_card_rename(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical
        sp.Children.Add(_section_lbl("Rename files (optional)"))

        note = _tb("A loadable family is named by its file, so renaming the .rfa "
                   "renames the family - no need to open anything. Families "
                   "already loaded into a project keep their old name until "
                   "they are reloaded.",
                   size=10, color=CLR_MUTED, wrap=True)
        note.Margin = Thickness(0, 0, 0, 8)
        sp.Children.Add(note)

        row1 = StackPanel()
        row1.Orientation = Orientation.Horizontal
        row1.Margin = Thickness(0, 0, 0, 8)
        panel, self.txt_find = _labelled_box(
            "Find:", 100, "Text to remove or replace in every name")
        row1.Children.Add(panel)
        panel, self.txt_replace = _labelled_box("Replace:", 100)
        row1.Children.Add(panel)
        panel, self.txt_prefix = _labelled_box("Prefix:", 110, "e.g. LB_WH_DOR_")
        row1.Children.Add(panel)
        panel, self.txt_suffix = _labelled_box("Suffix:", 100)
        row1.Children.Add(panel)
        sp.Children.Add(row1)

        row2 = StackPanel()
        row2.Orientation = Orientation.Horizontal
        row2.Margin = Thickness(0, 0, 0, 10)

        caption = _tb("Case:", size=10, color=CLR_MUTED)
        caption.VerticalAlignment = VerticalAlignment.Center
        caption.Margin = Thickness(0, 0, 8, 0)
        row2.Children.Add(caption)

        self.rb_case_none = _radio("None", "case", checked=True)
        self.rb_case_upper = _radio("UPPER", "case")
        self.rb_case_lower = _radio("lower", "case")
        self.rb_case_title = _radio("Title", "case")
        for rb in (self.rb_case_none, self.rb_case_upper, self.rb_case_lower,
                   self.rb_case_title):
            row2.Children.Add(rb)

        caption = _tb("Keep first", size=10, color=CLR_MUTED)
        caption.VerticalAlignment = VerticalAlignment.Center
        caption.Margin = Thickness(6, 0, 5, 0)
        row2.Children.Add(caption)

        self.txt_keep = _num_box(0, width=34)
        self.txt_keep.ToolTip = ("Leading characters forced to UPPERCASE and left "
                                 "out of the conversion, so a project prefix "
                                 "survives it. 5 turns Lb_wh_Ano into LB_WH_Ano.")
        row2.Children.Add(self.txt_keep)

        caption = _tb("chars UPPER", size=10, color=CLR_MUTED)
        caption.VerticalAlignment = VerticalAlignment.Center
        caption.Margin = Thickness(5, 0, 18, 0)
        row2.Children.Add(caption)

        self.chk_remove_spaces = _chk("Remove spaces")
        row2.Children.Add(self.chk_remove_spaces)
        sp.Children.Add(row2)

        row3 = StackPanel()
        row3.Orientation = Orientation.Horizontal

        self.btn_rename = _btn("Rename Files", CLR_HEADER, CLR_ACCENT,
                               h=30, bold=True)
        self.btn_rename.Padding = Thickness(16, 0, 16, 0)
        row3.Children.Add(self.btn_rename)

        self.lbl_rename_status = _tb("Set an option to preview the new names.",
                                     size=10, color=CLR_MUTED)
        self.lbl_rename_status.VerticalAlignment = VerticalAlignment.Center
        self.lbl_rename_status.Margin = Thickness(12, 0, 0, 0)
        row3.Children.Add(self.lbl_rename_status)
        sp.Children.Add(row3)

        for box in (self.txt_find, self.txt_replace, self.txt_prefix,
                    self.txt_suffix, self.txt_keep):
            box.TextChanged += self._on_rename_option_changed
        for rb in (self.rb_case_none, self.rb_case_upper, self.rb_case_lower,
                   self.rb_case_title):
            rb.Checked += self._on_rename_option_changed
        self.chk_remove_spaces.Checked += self._on_rename_option_changed
        self.chk_remove_spaces.Unchecked += self._on_rename_option_changed
        self.btn_rename.Click += self.on_rename

        return _card(sp, margin=(0, 0, 0, 10))

    def _make_card_folder(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical
        sp.Children.Add(_section_lbl("Folder"))

        folder_row = DockPanel()
        folder_row.LastChildFill = True
        folder_row.Margin = Thickness(0, 0, 0, 10)

        self.btn_browse = _btn("Browse...", CLR_CARD, CLR_TEXT, w=84)
        self.btn_browse.Click += self.on_browse
        DockPanel.SetDock(self.btn_browse, System.Windows.Controls.Dock.Right)
        folder_row.Children.Add(self.btn_browse)

        self.txt_folder = TextBox()
        self.txt_folder.IsReadOnly = True
        self.txt_folder.Text = "No folder selected..."
        self.txt_folder.FontSize = 11
        self.txt_folder.FontFamily = FONT_UI
        self.txt_folder.Foreground = SolidColorBrush(CLR_MUTED)
        self.txt_folder.Background = SolidColorBrush(CLR_ALT)
        self.txt_folder.BorderBrush = SolidColorBrush(CLR_BORDER)
        self.txt_folder.BorderThickness = Thickness(1)
        self.txt_folder.Padding = Thickness(6, 0, 6, 0)
        self.txt_folder.Height = 28
        self.txt_folder.Margin = Thickness(0, 0, 6, 0)
        self.txt_folder.VerticalContentAlignment = VerticalAlignment.Center
        folder_row.Children.Add(self.txt_folder)
        sp.Children.Add(folder_row)

        opt = StackPanel()
        opt.Orientation = Orientation.Horizontal

        self.chk_recursive = _chk("Include subfolders", checked=True)
        self.chk_recursive.Margin = Thickness(0, 0, 20, 0)
        opt.Children.Add(self.chk_recursive)

        lbl_passes = _tb("Purge passes:", color=CLR_TEXT)
        lbl_passes.VerticalAlignment = VerticalAlignment.Center
        lbl_passes.Margin = Thickness(0, 0, 6, 0)
        opt.Children.Add(lbl_passes)

        self.txt_passes = _num_box(10)
        self.txt_passes.Margin = Thickness(0, 0, 16, 0)
        self.txt_passes.ToolTip = (
            "How many times to re-purge within one open document.\n"
            "Deleting one element can make others purgeable.")
        opt.Children.Add(self.txt_passes)

        lbl_cycles = _tb("Reopen cycles:", color=CLR_TEXT)
        lbl_cycles.VerticalAlignment = VerticalAlignment.Center
        lbl_cycles.Margin = Thickness(0, 0, 6, 0)
        opt.Children.Add(lbl_cycles)

        self.txt_cycles = _num_box(3)
        self.txt_cycles.Margin = Thickness(0, 0, 20, 0)
        self.txt_cycles.ToolTip = (
            "How many times to save, reopen and purge again.\n"
            "Some elements only become purgeable after the file has been\n"
            "written and read back - this is what clears the last remainder.")
        opt.Children.Add(self.txt_cycles)

        self.chk_delete_backups = _chk("Delete backup files (.0001, .0002...)")
        self.chk_delete_backups.Margin = Thickness(0, 0, 20, 0)
        opt.Children.Add(self.chk_delete_backups)

        self.chk_log = _chk("Export Excel log when done")
        opt.Children.Add(self.chk_log)

        sp.Children.Add(opt)
        return _card(sp, margin=(0, 0, 0, 10))

    def _make_card_scan(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical

        scan_row = DockPanel()
        scan_row.LastChildFill = False
        scan_row.Margin = Thickness(0, 0, 0, 10)

        self.btn_scan = _btn("Scan Folder", CLR_CARD, CLR_TEXT, w=110)
        self.btn_scan.Click += self.on_scan
        DockPanel.SetDock(self.btn_scan, System.Windows.Controls.Dock.Left)
        scan_row.Children.Add(self.btn_scan)

        count_sp = StackPanel()
        count_sp.Orientation = Orientation.Horizontal
        count_sp.VerticalAlignment = VerticalAlignment.Center
        count_sp.Margin = Thickness(12, 0, 0, 0)

        lbl_found = _tb("Files found: ", color=CLR_MUTED)
        lbl_found.VerticalAlignment = VerticalAlignment.Center
        count_sp.Children.Add(lbl_found)

        self.lbl_count = TextBlock()
        self.lbl_count.Text = u"—"
        self.lbl_count.FontSize = 15
        self.lbl_count.FontWeight = FontWeights.Bold
        self.lbl_count.FontFamily = FONT_UI
        self.lbl_count.Foreground = SolidColorBrush(CLR_ACCENT)
        self.lbl_count.VerticalAlignment = VerticalAlignment.Center
        count_sp.Children.Add(self.lbl_count)

        scan_row.Children.Add(count_sp)
        sp.Children.Add(scan_row)

        sp.Children.Add(_section_lbl("Preview / Results"))

        self.list_files = ListBox()
        self.list_files.Height = 200
        self.list_files.FontSize = 11
        self.list_files.FontFamily = FONT_MONO
        self.list_files.Foreground = SolidColorBrush(CLR_TEXT)
        self.list_files.Background = SolidColorBrush(CLR_LIST_BG)
        self.list_files.BorderBrush = SolidColorBrush(CLR_BORDER)
        self.list_files.BorderThickness = Thickness(1)
        self.list_files.SelectionMode = SelectionMode.Extended
        self.list_files.HorizontalContentAlignment = HorizontalAlignment.Left
        sp.Children.Add(self.list_files)

        return _card(sp, margin=(0, 0, 0, 10))

    def _make_card_progress(self):
        sp = StackPanel()
        sp.Orientation = Orientation.Vertical
        sp.Children.Add(_section_lbl("Progress"))

        prog_row = DockPanel()
        prog_row.LastChildFill = True
        prog_row.Margin = Thickness(0, 0, 0, 8)

        self.lbl_prog_text = TextBlock()
        self.lbl_prog_text.Text = "0 / 0"
        self.lbl_prog_text.FontSize = 10
        self.lbl_prog_text.FontFamily = FONT_UI
        self.lbl_prog_text.Foreground = SolidColorBrush(CLR_MUTED)
        self.lbl_prog_text.Width = 50
        self.lbl_prog_text.TextAlignment = System.Windows.TextAlignment.Right
        self.lbl_prog_text.VerticalAlignment = VerticalAlignment.Center
        DockPanel.SetDock(self.lbl_prog_text, System.Windows.Controls.Dock.Right)
        prog_row.Children.Add(self.lbl_prog_text)

        self.progress = ProgressBar()
        self.progress.Height = 12
        self.progress.Minimum = 0
        self.progress.Maximum = 100
        self.progress.Value = 0
        self.progress.Foreground = SolidColorBrush(CLR_HEADER)
        self.progress.Background = SolidColorBrush(CLR_ALT)
        self.progress.BorderThickness = Thickness(0)
        self.progress.Margin = Thickness(0, 0, 10, 0)
        prog_row.Children.Add(self.progress)
        sp.Children.Add(prog_row)

        self.summary_border = Border()
        self.summary_border.Background = SolidColorBrush(CLR_ALT)
        self.summary_border.BorderBrush = SolidColorBrush(CLR_BORDER)
        self.summary_border.BorderThickness = Thickness(1)
        self.summary_border.CornerRadius = System.Windows.CornerRadius(3)
        self.summary_border.Padding = Thickness(10, 7, 10, 7)
        self.summary_border.Visibility = Visibility.Collapsed

        self.lbl_summary = TextBlock()
        self.lbl_summary.FontSize = 11
        self.lbl_summary.FontFamily = FONT_UI
        self.lbl_summary.Foreground = SolidColorBrush(CLR_ACCENT)
        self.lbl_summary.TextWrapping = System.Windows.TextWrapping.Wrap
        self.summary_border.Child = self.lbl_summary
        sp.Children.Add(self.summary_border)

        return _card(sp, margin=(0, 0, 0, 10))

    def _make_card_actions(self):
        dp = DockPanel()
        dp.LastChildFill = False

        self.btn_run = _btn(
            u"▶  Start Purge",
            CLR_APPLY_BG, CLR_APPLY_TEXT,
            bdr=CLR_APPLY_BDR, h=34, bold=True, size=13
        )
        self.btn_run.Padding = Thickness(22, 0, 22, 0)
        self.btn_run.IsEnabled = False
        self.btn_run.Click += self.on_run
        DockPanel.SetDock(self.btn_run, System.Windows.Controls.Dock.Left)
        dp.Children.Add(self.btn_run)

        return _card(dp, margin=(0, 0, 0, 4))

    # =======================================================================
    #  Events
    # =======================================================================
    def on_help(self, sender, e):
        if _open_help_page("purge_families.html"):
            return
        MessageBox.Show(
            "BATCH PURGE FAMILIES - DQT\n"
            "\n"
            "1. Browse       Select the folder containing .rfa families.\n"
            "2. Scan Folder  Find all .rfa files; preview with sizes.\n"
            "3. Start Purge  Each file is opened, purged, saved, and\n"
            "                reopened until nothing purgeable is left.\n"
            "\n"
            "WHY REOPEN CYCLES\n"
            "  Revit finalises part of its reference bookkeeping when a file\n"
            "  is written. Elements still held after an in-memory purge only\n"
            "  become purgeable once the file has been saved and read back.\n"
            "  Purging in a single open session leaves that tier behind -\n"
            "  which is why the native Purge Unused dialog would still list\n"
            "  items afterwards. Cycles repeat save+reopen+purge until a\n"
            "  freshly opened file reports zero.\n"
            "\n"
            "THE REMAINING COLUMN\n"
            "  Every file is verified after its last purge. Status reads\n"
            "  Success only when Revit reports 0 purgeable elements left.\n"
            "  Partial means something is protected and cannot be removed -\n"
            "  the count tells you how much.\n"
            "\n"
            "OPTIONS\n"
            "  Include subfolders   Scan nested folders recursively.\n"
            "  Purge passes         Re-purge within one open document.\n"
            "  Reopen cycles        Save, reopen and purge again.\n"
            "  Delete backup files  Remove *.0001.rfa / *.0001.rvt copies.\n"
            "  Export Excel log     Save the result table in the folder.\n"
            "\n"
            "RENAME FILES\n"
            "  A loadable family is named by its file, so renaming the .rfa\n"
            "  renames the family - nothing has to be opened, which is why\n"
            "  this runs instantly even on hundreds of files.\n"
            "  Find/Replace, Prefix, Suffix, Case and Remove spaces all\n"
            "  combine in one pass. The list previews every old -> new name\n"
            "  before you commit, and Rename Files asks again first.\n"
            "  Skipped files say why: two files resolving to the same name,\n"
            "  a name already taken, or characters Windows will not accept.\n"
            "  Renaming is independent of purging - run either, or both.\n"
            "  Families already loaded into a project keep their old name\n"
            "  until they are reloaded.\n"
            "\n"
            "NOTE  Files are overwritten in place. Back up first if needed.\n"
            "\n"
            + FOOTER_TEXT,
            "Help - Batch Purge Families",
            MessageBoxButton.OK, MessageBoxImage.Information)

    def on_browse(self, sender, e):
        dlg = FolderBrowserDialog()
        dlg.Description = "Select folder containing .rfa files to purge"
        dlg.ShowNewFolderButton = False
        if dlg.ShowDialog() == FDResult.OK:
            self.txt_folder.Text = dlg.SelectedPath
            self.txt_folder.Foreground = SolidColorBrush(CLR_TEXT)
            self.family_files = []
            self.list_files.Items.Clear()
            self.lbl_count.Text = u"—"
            self.btn_run.IsEnabled = False
            self.summary_border.Visibility = Visibility.Collapsed
            self.lbl_status.Text = "Folder selected. Click Scan to find files."

    def on_scan(self, sender, e):
        folder = self.txt_folder.Text
        if not folder or not os.path.isdir(folder):
            MessageBox.Show("Please select a valid folder first.",
                            "Notice", MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        self.family_files = []
        if self.chk_recursive.IsChecked:
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".rfa") and not _is_revit_backup(f):
                        self.family_files.append(os.path.join(root, f))
        else:
            for f in os.listdir(folder):
                fp = os.path.join(folder, f)
                if (os.path.isfile(fp) and f.lower().endswith(".rfa")
                        and not _is_revit_backup(f)):
                    self.family_files.append(fp)

        self.family_files.sort()

        count = len(self.family_files)
        self.lbl_count.Text = str(count)
        self.btn_run.IsEnabled = count > 0
        self.summary_border.Visibility = Visibility.Collapsed

        if count == 0:
            self.list_files.Items.Clear()
            self.lbl_status.Text = "No .rfa files found in this folder."
        else:
            self._refresh_rename_preview()
            self.lbl_status.Text = (
                "Found {} .rfa file(s). Click 'Start Purge' to continue.".format(count))

    # -- file list rendering ------------------------------------------------
    def _relative(self, path):
        try:
            return os.path.relpath(path, self.txt_folder.Text)
        except Exception:
            return os.path.basename(path)

    def _show_file_list(self):
        """The plain scan listing - size and path, no rename applied."""
        self.list_files.Items.Clear()
        for fp in self.family_files:
            try:
                size_kb = os.path.getsize(fp) // 1024
            except Exception:
                size_kb = 0
            item = ListBoxItem()
            item.Content = "  [{:>7} KB]  {}".format(size_kb, self._relative(fp))
            item.Padding = Thickness(2, 1, 2, 1)
            self.list_files.Items.Add(item)

    def _add_plan_row(self, entry, done=False):
        item = ListBoxItem()
        item.Padding = Thickness(2, 1, 2, 1)
        where = os.path.dirname(self._relative(entry["path"]))
        where = (where + os.sep) if where and where != "." else ""

        if entry["status"] in ("rename", "renamed"):
            item.Content = u"  {}  {}{}  ->  {}".format(
                u"✔" if done else u"→", where, entry["old"], entry["new"])
            item.Foreground = SolidColorBrush(CLR_APPLY_TEXT)
        elif entry["status"] == "unchanged":
            item.Content = u"     {}{}  (no change)".format(where, entry["old"])
            item.Foreground = SolidColorBrush(CLR_MUTED)
        else:
            item.Content = u"  ✘  {}{}  skipped: {}".format(
                where, entry["old"], entry["reason"])
            item.Foreground = SolidColorBrush(CLR_WARN_TEXT)

        self.list_files.Items.Add(item)

    # -- rename -------------------------------------------------------------
    def _rename_options(self):
        if self.rb_case_upper.IsChecked:
            mode = "upper"
        elif self.rb_case_lower.IsChecked:
            mode = "lower"
        elif self.rb_case_title.IsChecked:
            mode = "title"
        else:
            mode = "none"

        return {
            "find": self.txt_find.Text or "",
            "replace": self.txt_replace.Text or "",
            "prefix": self.txt_prefix.Text or "",
            "suffix": self.txt_suffix.Text or "",
            "case_mode": mode,
            "keep_upper": _read_int(self.txt_keep, 0, 0, 200),
            "remove_spaces": bool(self.chk_remove_spaces.IsChecked),
        }

    def _has_rename_options(self, options=None):
        o = options or self._rename_options()
        return bool(o["find"] or o["prefix"] or o["suffix"]
                    or o["case_mode"] != "none" or o["keep_upper"]
                    or o["remove_spaces"])

    def _on_rename_option_changed(self, sender, e):
        try:
            self._refresh_rename_preview()
        except Exception:
            pass

    def _refresh_rename_preview(self):
        """Show what the current options would do. Nothing touches disk here."""
        if not self.family_files:
            return

        options = self._rename_options()
        if not self._has_rename_options(options):
            self._show_file_list()
            self.lbl_rename_status.Text = "Set an option to preview the new names."
            return

        plan = plan_renames(self.family_files, **options)
        self.list_files.Items.Clear()
        for entry in plan:
            self._add_plan_row(entry)

        will = sum(1 for entry in plan if entry["status"] == "rename")
        skipped = sum(1 for entry in plan if entry["status"] == "skip")
        self.lbl_rename_status.Text = "{} to rename, {} skipped.".format(will, skipped)

    def on_rename(self, sender, e):
        if not self.family_files:
            MessageBox.Show("Scan a folder first.", "Notice",
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        options = self._rename_options()
        if not self._has_rename_options(options):
            MessageBox.Show("Set at least one rename option first.", "Notice",
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        plan = plan_renames(self.family_files, **options)
        will = [entry for entry in plan if entry["status"] == "rename"]
        if not will:
            MessageBox.Show("These options change nothing that can be renamed.\n\n"
                            "Check the list for the reason each file was skipped.",
                            "Notice", MessageBoxButton.OK, MessageBoxImage.Information)
            return

        sample = "\n".join(u"  {}  ->  {}".format(entry["old"], entry["new"])
                           for entry in will[:8])
        if len(will) > 8:
            sample += u"\n  ... and {} more".format(len(will) - 8)

        confirm = MessageBox.Show(
            u"Rename {} file(s) on disk?\n\n{}\n\n"
            u"This renames the .rfa files themselves and cannot be undone.".format(
                len(will), sample),
            "Confirm Rename", MessageBoxButton.YesNo, MessageBoxImage.Warning)
        if confirm != MessageBoxResult.Yes:
            return

        renamed, failures = apply_renames(plan)

        # The scanned paths have moved; keep the list pointing at real files.
        self.family_files = sorted(entry["path"] for entry in plan)

        self.list_files.Items.Clear()
        for entry in plan:
            self._add_plan_row(entry, done=True)

        skipped = sum(1 for entry in plan if entry["status"] == "skip")
        self.lbl_rename_status.Text = (
            "Renamed {}, skipped {}. The options are still set - clear them "
            "before running again.".format(renamed, skipped))
        self.lbl_status.Text = "Renamed {} file(s).".format(renamed)

        message = ["RENAME COMPLETE", "",
                   "Renamed : {}".format(renamed),
                   "Skipped : {}".format(skipped)]
        if failures:
            message += ["", "Could not be renamed:"]
            message += ["  {} - {}".format(name, reason)
                        for name, reason in failures[:10]]
            if len(failures) > 10:
                message.append("  ... and {} more".format(len(failures) - 10))
        MessageBox.Show("\n".join(message), "Result",
                        MessageBoxButton.OK, MessageBoxImage.Information)

    def on_run(self, sender, e):
        if not self.family_files:
            return

        confirm = MessageBox.Show(
            "About to purge and OVERWRITE {} .rfa file(s).\n\n"
            "Each file is opened, purged, saved and reopened until clean.\n"
            "This cannot be undone - back up the folder first if needed.\n\n"
            "Continue?".format(len(self.family_files)),
            "Confirm", MessageBoxButton.YesNo, MessageBoxImage.Warning)
        if confirm != MessageBoxResult.Yes:
            return

        self.btn_run.IsEnabled = False
        self.btn_scan.IsEnabled = False
        self.btn_export.IsEnabled = False
        self.summary_border.Visibility = Visibility.Collapsed
        self.results = []

        # Rebuild the listing so its rows line up with family_files - a rename
        # preview or a completed rename leaves it in a different order.
        self._show_file_list()

        max_passes = _read_int(self.txt_passes, 10, 1, 50)
        max_cycles = _read_int(self.txt_cycles, 3, 1, 10)

        total = len(self.family_files)
        folder = self.txt_folder.Text
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        self.progress.Maximum = total
        self.progress.Value = 0

        for idx, fp in enumerate(self.family_files):
            fname = os.path.basename(fp)
            self.lbl_status.Text = "Processing ({}/{}): {}".format(idx + 1, total, fname)
            self.lbl_prog_text.Text = "{} / {}".format(idx + 1, total)
            WFApp.DoEvents()

            result = process_family_file(fp, max_passes, max_cycles)
            result["time"] = datetime.datetime.now().strftime("%H:%M:%S")
            self.results.append(result)

            rel = os.path.relpath(fp, folder)
            item = self.list_files.Items[idx]
            if result["status"] == "Error":
                item.Content = u"  ✘  [ERROR: {}]  {}".format(
                    result["error"][:50], rel)
                item.Foreground = SolidColorBrush(CLR_ERR_TEXT)
            else:
                saved = result["size_before"] - result["size_after"]
                mark = u"✔" if result["status"] == "Success" else u"△"
                item.Content = (
                    u"  {}  [{}->{} KB  −{} KB  |  {} purged  |  "
                    u"{} left  |  {}p/{}c]  {}"
                ).format(mark, result["size_before"], result["size_after"], saved,
                         result["purged_count"], result["remaining"],
                         result["passes"], result["cycles"], rel)
                item.Foreground = SolidColorBrush(
                    CLR_APPLY_TEXT if result["status"] == "Success" else CLR_WARN_TEXT)

            self.progress.Value = idx + 1
            WFApp.DoEvents()

        deleted_count = 0
        freed_bytes = 0
        failed_backups = []
        if self.chk_delete_backups.IsChecked:
            self.lbl_status.Text = "Deleting backup files (*.0001.rfa / *.0001.rvt)..."
            WFApp.DoEvents()
            deleted_count, freed_bytes, failed_backups = delete_backup_files(
                folder, bool(self.chk_recursive.IsChecked))

        clean = sum(1 for r in self.results if r["status"] == "Success")
        partial = sum(1 for r in self.results if r["status"] == "Partial")
        errors = sum(1 for r in self.results if r["status"] == "Error")
        total_purged = sum(r["purged_count"] for r in self.results)
        total_left = sum(r["remaining"] for r in self.results if r["remaining"] > 0)

        summary_parts = [
            u"✔  Clean (0 left): {}    △  Partial: {}    "
            u"✘  Errors: {}".format(clean, partial, errors),
            "Elements purged: {}".format(total_purged),
        ]
        if total_left:
            summary_parts.append("Still purgeable: {}".format(total_left))
        if self.chk_delete_backups.IsChecked:
            freed_mb = round(freed_bytes / (1024.0 * 1024.0), 2)
            summary_parts.append(
                "Backups deleted: {} ({} MB){}".format(
                    deleted_count, freed_mb,
                    " ({} failed)".format(len(failed_backups)) if failed_backups else ""))

        self.lbl_summary.Text = "    ".join(summary_parts)
        self.summary_border.Visibility = Visibility.Visible
        self.lbl_status.Text = "Done - {}/{} reached zero.".format(clean, total)
        self.progress.Value = total
        self.btn_run.IsEnabled = True
        self.btn_scan.IsEnabled = True
        self.btn_export.IsEnabled = True

        if self.chk_log.IsChecked:
            self._export_excel(folder, timestamp, silent=True)

        popup = [
            "PURGE COMPLETE",
            "",
            "Clean (0 purgeable left) : {}".format(clean),
            "Partial (something left) : {}".format(partial),
            "Errors                   : {}".format(errors),
            "Elements purged          : {}".format(total_purged),
        ]
        if total_left:
            popup.append("Still purgeable          : {}".format(total_left))
            popup.append("")
            popup.append("Partial files hold elements Revit will not remove -")
            popup.append("usually a type still referenced from inside the family.")
        if self.chk_delete_backups.IsChecked:
            freed_mb = round(freed_bytes / (1024.0 * 1024.0), 2)
            popup += [
                "",
                "Backup files deleted : {}".format(deleted_count),
                "Disk space freed     : {} MB".format(freed_mb),
            ]
            if failed_backups:
                popup.append("Failed to delete     : {}".format(len(failed_backups)))

        MessageBox.Show("\n".join(popup), "Result",
                        MessageBoxButton.OK, MessageBoxImage.Information)

    def on_export(self, sender, e):
        if not self.results:
            return
        self._export_excel(
            self.txt_folder.Text,
            datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            silent=False)

    def _export_excel(self, folder, timestamp, silent=False):
        if not folder or not os.path.isdir(folder):
            MessageBox.Show("Cannot export log: target folder is not valid.",
                            "Error", MessageBoxButton.OK, MessageBoxImage.Error)
            return

        out_path = os.path.join(folder, "DQT_purge_log_{}.xlsx".format(timestamp))
        ok, err = export_excel(self.results, out_path)

        if ok:
            self.lbl_status.Text = "Excel log saved: {}".format(os.path.basename(out_path))
            MessageBox.Show(
                "Excel log saved:\n{}".format(
                    os.path.basename(out_path) if silent else out_path),
                "Export Complete", MessageBoxButton.OK, MessageBoxImage.Information)
        else:
            MessageBox.Show("Could not export Excel log:\n{}".format(err),
                            "Error", MessageBoxButton.OK, MessageBoxImage.Error)


# ===========================================================================
#  Entry point
# ===========================================================================
if __name__ == "__main__":
    PurgeFamiliesWindow().ShowDialog()
