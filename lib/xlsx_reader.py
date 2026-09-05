# -*- coding: utf-8 -*-
"""Read a spreadsheet without needing Excel installed.

clr.AddReference("Microsoft.Office.Interop.Excel") fails on plenty of
machines where Excel itself works perfectly: modern Click-to-Run installs
of Microsoft 365 frequently do not register the Excel Primary Interop
Assembly in the GAC the way the old MSI installer used to. That is exactly
what "Could not add reference to assembly Microsoft.Office.Interop.Excel"
means, and no amount of try/except around the COM calls fixes it - the
assembly plain isn't there to load.

.xlsx has been a zip archive of XML parts since Excel 2007, so it can be
read directly with .NET's built-in System.IO.Compression (part of the .NET
Framework Revit itself requires - no Office install of any kind needed)
plus xml.etree.ElementTree. CSV is read directly too. COM Interop is kept
only as a last resort for the legacy binary .xls format, which is not a
zip file at all.

Public API:

    read_workbook(filepath, log=None)
        -> {"sheets": [name, ...],
            "rows":   {name: {row_number: {col_index: value}}}}
        Row and column numbers are 1-based, matching what the Excel COM
        object model reported, so callers written against the old reader
        keep their indexing. Only cells that carry a value are present.

    looks_like_file_lock(exception) -> bool
    XlsxReadError

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

import clr

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Same ceiling the COM reader used, so a runaway UsedRange cannot turn one
# stray cell in column 5000 into thousands of empty header entries.
MAX_COLS = 30


class XlsxReadError(Exception):
    """Raised with a message meant to be shown to the user as-is."""
    pass


def looks_like_file_lock(ex):
    """True when the failure is Windows refusing access to the file itself
    rather than anything about the workbook's contents."""
    text = str(ex).lower()
    return ("another process" in text          # sharing violation
            or "being used by" in text
            or "access to the path" in text    # permissions
            or "denied" in text)


def _col_index(cell_ref):
    """'C5' -> 3 (1-based column index). None if the reference is odd."""
    import re
    m = re.match(r'^([A-Za-z]+)\d+$', cell_ref or "")
    if not m:
        return None
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx


def _cell_value(c_el, shared):
    """Text/number value of one <c> cell element, resolving shared strings."""
    t = c_el.get("t")
    if t == "s":
        v_el = c_el.find(_NS_MAIN + "v")
        if v_el is None or v_el.text is None:
            return None
        try:
            idx = int(v_el.text)
        except ValueError:
            return None
        return shared[idx] if 0 <= idx < len(shared) else None
    if t == "inlineStr":
        is_el = c_el.find(_NS_MAIN + "is")
        if is_el is None:
            return None
        return "".join(e.text or "" for e in is_el.iter(_NS_MAIN + "t"))
    v_el = c_el.find(_NS_MAIN + "v")
    if v_el is None or v_el.text is None:
        return None
    text = v_el.text
    if t == "str":
        return text
    if t == "b":
        return "TRUE" if text == "1" else "FALSE"
    # Plain number - formatted the way Cells[].Value2 would be after the
    # callers' str(), so parsing logic written against COM output behaves
    # identically no matter which reader supplied the value.
    try:
        f = float(text)
        return str(int(f)) if f == int(f) and abs(f) < 1e15 else str(f)
    except ValueError:
        return text


def _read_zip_entry_text(archive, path):
    """Full text of one part inside the .xlsx zip, or None if absent."""
    entry = archive.GetEntry(path)
    if entry is None:
        return None
    from System.IO import StreamReader
    stream = entry.Open()
    reader = StreamReader(stream)
    try:
        return reader.ReadToEnd()
    finally:
        reader.Close()


def _shared_strings(archive):
    import xml.etree.ElementTree as ET
    text = _read_zip_entry_text(archive, "xl/sharedStrings.xml")
    if not text:
        return []
    root = ET.fromstring(text.encode("utf-8"))
    return ["".join(t.text or "" for t in si.iter(_NS_MAIN + "t"))
            for si in root.findall(_NS_MAIN + "si")]


def _sheet_list(archive):
    """[(sheet_name, worksheet_part_path), ...] in workbook order."""
    import xml.etree.ElementTree as ET
    wb_text = _read_zip_entry_text(archive, "xl/workbook.xml")
    if not wb_text:
        return []
    wb_root = ET.fromstring(wb_text.encode("utf-8"))

    rel_map = {}
    rels_text = _read_zip_entry_text(archive, "xl/_rels/workbook.xml.rels")
    if rels_text:
        rels_root = ET.fromstring(rels_text.encode("utf-8"))
        for rel in rels_root.findall(_NS_PR + "Relationship"):
            rel_map[rel.get("Id")] = rel.get("Target")

    sheets_el = wb_root.find(_NS_MAIN + "sheets")
    if sheets_el is None:
        return []

    result = []
    for sheet_el in sheets_el.findall(_NS_MAIN + "sheet"):
        name = sheet_el.get("name") or ""
        target = rel_map.get(sheet_el.get(_NS_R + "id"))
        if not target:
            continue
        target = target.replace("\\", "/").lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        result.append((name, target))
    return result


def _read_rows(archive, path, shared):
    """{row_number: {col_index: value}} for a worksheet part.

    A single malformed <row> is skipped rather than failing the whole
    sheet."""
    import xml.etree.ElementTree as ET
    text = _read_zip_entry_text(archive, path)
    if not text:
        raise XlsxReadError("empty or missing worksheet part: " + path)
    root = ET.fromstring(text.encode("utf-8"))
    sheet_data = root.find(_NS_MAIN + "sheetData")
    rows = {}
    if sheet_data is None:
        return rows
    for row_el in sheet_data.findall(_NS_MAIN + "row"):
        try:
            row_num = int(row_el.get("r"))
            cells = {}
            for c_el in row_el.findall(_NS_MAIN + "c"):
                col_idx = _col_index(c_el.get("r"))
                if col_idx is not None:
                    cells[col_idx] = _cell_value(c_el, shared)
            if cells:
                rows[row_num] = cells
        except Exception:
            continue
    return rows


def _open_archive(filepath):
    """Open a .xlsx as a zip archive, tolerating the file being open in
    Excel at the same time.

    ZipFile.OpenRead() asks for FileShare.Read, which Windows refuses with
    a sharing violation while Excel holds the workbook open - the single
    most likely state for a mapping file the user just looked at. Opening
    the FileStream ourselves with FileShare.ReadWrite | FileShare.Delete
    reads it happily either way.

    Returns (archive, stream); the caller must dispose both."""
    clr.AddReference("System.IO.Compression")
    try:
        # Only the static ZipFile helper lives here and we do not use it; a
        # machine missing this assembly must not lose the whole reader.
        clr.AddReference("System.IO.Compression.FileSystem")
    except:
        pass
    from System.IO import FileStream, FileMode, FileAccess, FileShare
    from System.IO.Compression import ZipArchive, ZipArchiveMode

    stream = FileStream(filepath, FileMode.Open, FileAccess.Read,
                        FileShare.ReadWrite | FileShare.Delete)
    try:
        return ZipArchive(stream, ZipArchiveMode.Read), stream
    except:
        try:
            stream.Close()
        except:
            pass
        raise


def _read_xlsx(filepath, log):
    """Every sheet of a .xlsx/.xlsm, read as zip + XML."""
    archive, stream = _open_archive(filepath)
    try:
        shared = _shared_strings(archive)
        sheet_list = _sheet_list(archive)
        if not sheet_list:
            raise XlsxReadError("workbook.xml lists no sheets")

        result = {"sheets": [], "rows": {}}
        skipped = []
        for name, path in sheet_list:
            try:
                result["rows"][name] = _read_rows(archive, path, shared)
                result["sheets"].append(name)
            except Exception as ex:
                skipped.append("{} ({})".format(name, str(ex)))

        if skipped and log:
            log("Skipped {} sheet(s) that could not be read: {}".format(
                len(skipped), ", ".join(skipped)))
        if not result["sheets"]:
            raise XlsxReadError("no readable sheets found in the file")
        return result
    finally:
        try:
            archive.Dispose()
        except:
            pass
        try:
            stream.Close()
        except:
            pass


def _read_csv(filepath):
    """A .csv as a single sheet, so callers treat it like any workbook."""
    import csv
    import codecs
    import os

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            handle = codecs.open(filepath, "r", encoding)
            try:
                lines = handle.read().splitlines()
            finally:
                handle.close()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise XlsxReadError("could not decode the CSV file as text")

    rows = {}
    import sys
    if sys.version_info[0] >= 3:
        reader = csv.reader(lines)
    else:
        # Python 2 / IronPython's csv cannot take unicode at all - it must be
        # handed UTF-8 bytes, and the fields come back as bytes to decode.
        reader = csv.reader([l.encode("utf-8") for l in lines])
    for row_num, fields in enumerate(reader, start=1):
        cells = {}
        for col_num, field in enumerate(fields[:MAX_COLS], start=1):
            value = field.decode("utf-8") if isinstance(field, bytes) else field
            value = value.strip()
            if value:
                cells[col_num] = value
        if cells:
            rows[row_num] = cells

    name = os.path.splitext(os.path.basename(filepath))[0] or "CSV"
    return {"sheets": [name], "rows": {name: rows}}


def _read_via_com(filepath):
    """Legacy path for the binary .xls format, which is not a zip file so
    the native reader cannot open it. Needs Excel plus its Interop PIA."""
    try:
        clr.AddReference("Microsoft.Office.Interop.Excel")
        import Microsoft.Office.Interop.Excel as Excel
    except Exception as ex:
        raise XlsxReadError(
            "This is a legacy .xls file, which can only be read through "
            "Microsoft Excel, and Excel automation is not available on this "
            "machine:\n\n{}\n\n"
            "Open the file in Excel and re-save it as .xlsx - that format is "
            "read directly and needs no Office install.".format(ex))

    import System
    app = Excel.ApplicationClass()
    app.Visible = False
    app.DisplayAlerts = False
    wb = None
    try:
        wb = app.Workbooks.Open(filepath)
        result = {"sheets": [], "rows": {}}
        for si in range(1, wb.Sheets.Count + 1):
            ws = wb.Sheets[si]
            used = ws.UsedRange
            n_rows = used.Rows.Count
            n_cols = min(used.Columns.Count, MAX_COLS)
            rows = {}
            for r in range(1, n_rows + 1):
                cells = {}
                for c in range(1, n_cols + 1):
                    val = ws.Cells[r, c].Value2
                    if val is None:
                        continue
                    if isinstance(val, float) and val == int(val):
                        cells[c] = str(int(val))
                    else:
                        cells[c] = str(val)
                if cells:
                    rows[r] = cells
            result["sheets"].append(ws.Name)
            result["rows"][ws.Name] = rows
        return result
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except:
            pass
        try:
            app.Quit()
        except:
            pass
        try:
            System.Runtime.InteropServices.Marshal.ReleaseComObject(app)
        except:
            pass


def read_workbook(filepath, log=None):
    """Read a workbook into {"sheets": [...], "rows": {...}}.

    .xlsx/.xlsm and .csv are read directly, with no Office component of any
    kind. COM Interop is only used for the legacy binary .xls - never as a
    retry for a file the OS would not let us open, because Excel automation
    cannot get past that either and its own failure then buries the real
    reason. `log` is an optional one-argument callable for warnings that do
    not stop the read."""
    lower = (filepath or "").lower()

    if lower.endswith(".csv"):
        return _read_csv(filepath)

    if lower.endswith((".xlsx", ".xlsm")):
        try:
            return _read_xlsx(filepath, log)
        except Exception as ex:
            if looks_like_file_lock(ex):
                raise XlsxReadError(
                    "Windows would not let the file be opened:\n\n{}\n\n"
                    "If the workbook is open in Excel, close it (or copy the "
                    "file somewhere else) and try again.".format(ex))
            if isinstance(ex, XlsxReadError):
                raise
            if log:
                log("Built-in reader could not open this file directly ({}) - "
                    "falling back to Microsoft Excel.".format(ex))

    return _read_via_com(filepath)
