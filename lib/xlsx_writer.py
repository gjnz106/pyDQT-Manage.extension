# -*- coding: utf-8 -*-
"""Write a formatted .xlsx report without needing Excel installed.

The same problem the sibling xlsx_reader.py documents applies to writing:
clr.AddReference("Microsoft.Office.Interop.Excel") fails on machines where
the Click-to-Run install of Microsoft 365 never registered the Excel
Primary Interop Assembly in the GAC. A report generator built on
Workbooks.Add()/SaveAs() simply cannot run there, no matter how well the
COM calls themselves are guarded - the assembly isn't there to load.

.xlsx has been a zip of XML parts (OOXML SpreadsheetML) since Excel 2007,
so a small, purpose-built subset of that format - enough for multi-sheet
reports with bold headers, background fills and merged title cells, which
is all any report in this suite needs - can be written directly with
.NET's built-in System.IO.Compression. No Office install of any kind is
required to produce a file Excel opens normally.

This is not a general-purpose spreadsheet library: no formulas, no shared
strings table (inline strings are simpler and the size difference does not
matter at report scale), no rich per-cell borders. It covers exactly the
formatting pyDQT's own reports use.

Public API:

    writer = XlsxWriter()
    sheet = writer.add_sheet("Summary")
    sheet.set(1, 1, "Title", bold=True, size=16, fill="F0CC88")
    sheet.merge(1, 1, 1, 5, fill="F0CC88", bold=True, size=16)
    sheet.set_col_width(1, 20)
    sheet.autosize_columns()          # optional, fills in any column
                                       # whose width was never set
    writer.save(filepath)

Row/column numbers are 1-based, matching the Excel COM object model this
replaces. Colors are plain "RRGGBB" hex (no leading '#', no alpha).

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

import clr


def _col_letter(idx):
    """1 -> A, 26 -> Z, 27 -> AA ... spreadsheet column numbering has no
    zero digit, so this is a bijective base-26 conversion, not a plain
    base-26 one - dividing by 26 directly would skip straight from Z to BA."""
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xml_escape(text):
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def _fmt_num(value):
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


class _Sheet(object):
    def __init__(self, name, writer):
        self.name = name
        self._writer = writer
        self._rows = {}          # row -> {col: (value, style_index)}
        self._merges = []        # list of "A1:E1" refs
        self._col_widths = {}    # col -> width
        self.max_row = 0
        self.max_col = 0

    def set(self, row, col, value="", bold=False, size=11, fill=None):
        """Write one cell. `fill` is an "RRGGBB" hex string or None."""
        style = self._writer._style_index(bold, size, fill)
        self._rows.setdefault(row, {})[col] = (value, style)
        self.max_row = max(self.max_row, row)
        self.max_col = max(self.max_col, col)

    def merge(self, row1, col1, row2, col2, fill=None, bold=False, size=11):
        """Merge a rectangular range. Every cell in the range gets the same
        style so the fill/font reads correctly across the whole merge -
        Excel itself only stores content on the top-left cell, but a
        blank cell with the wrong (default) style shows through at the
        edges of a merged, filled header."""
        ref = "{}{}:{}{}".format(
            _col_letter(col1), row1, _col_letter(col2), row2)
        self._merges.append(ref)
        for r in range(row1, row2 + 1):
            for c in range(col1, col2 + 1):
                if c not in self._rows.get(r, {}):
                    self.set(r, c, "", bold=bold, size=size, fill=fill)

    def set_col_width(self, col, width):
        self._col_widths[col] = width

    def autosize_columns(self, min_width=8, max_width=60, padding=2):
        """Estimate a readable width per column from its longest value.

        There is no real font metric available without Excel itself to
        do a true AutoFit, but this keeps a report usable out of the box
        instead of every column defaulting to Excel's generic width -
        only columns that were not already sized explicitly are touched."""
        longest = {}
        for cells in self._rows.values():
            for col, (value, _style) in cells.items():
                length = len(str(value)) if value not in (None, "") else 0
                longest[col] = max(longest.get(col, 0), length)
        for col, length in longest.items():
            if col not in self._col_widths:
                self._col_widths[col] = max(min_width, min(max_width, length + padding))

    def _to_xml(self):
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<worksheet xmlns="http://schemas.openxmlformats.org/'
                 'spreadsheetml/2006/main">']
        if self._col_widths:
            parts.append("<cols>")
            for col in sorted(self._col_widths):
                parts.append(
                    '<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'
                    .format(col, _fmt_num(self._col_widths[col])))
            parts.append("</cols>")

        parts.append("<sheetData>")
        for r in sorted(self._rows):
            parts.append('<row r="{}">'.format(r))
            for c in sorted(self._rows[r]):
                value, style = self._rows[r][c]
                ref = "{}{}".format(_col_letter(c), r)
                if value is None or value == "":
                    parts.append('<c r="{}" s="{}"/>'.format(ref, style))
                elif isinstance(value, bool):
                    # bool before int/float - bool is a subclass of int in
                    # Python and would otherwise be written as 0/1.
                    parts.append(
                        '<c r="{}" s="{}" t="inlineStr"><is><t>{}</t></is>'
                        '</c>'.format(ref, style, "TRUE" if value else "FALSE"))
                elif isinstance(value, (int, float)):
                    parts.append('<c r="{}" s="{}"><v>{}</v></c>'.format(
                        ref, style, _fmt_num(value)))
                else:
                    parts.append(
                        '<c r="{}" s="{}" t="inlineStr">'
                        '<is><t xml:space="preserve">{}</t></is></c>'.format(
                            ref, style, _xml_escape(str(value))))
            parts.append("</row>")
        parts.append("</sheetData>")

        if self._merges:
            parts.append('<mergeCells count="{}">'.format(len(self._merges)))
            for ref in self._merges:
                parts.append('<mergeCell ref="{}"/>'.format(ref))
            parts.append("</mergeCells>")

        parts.append("</worksheet>")
        return "".join(parts)


class XlsxWriter(object):
    """One workbook. add_sheet() returns a _Sheet to fill in, then save()
    writes the whole thing out as a single .xlsx."""

    def __init__(self):
        self._sheets = []
        self._style_keys = {}
        # index 0 is the default cell style every writer needs, so it is
        # seeded here rather than created lazily on first use.
        self._style_list = [(False, 11, None)]
        self._style_keys[(False, 11, None)] = 0

    def add_sheet(self, name):
        sheet = _Sheet(name, self)
        self._sheets.append(sheet)
        return sheet

    def _style_index(self, bold, size, fill):
        key = (bool(bold), size, fill)
        idx = self._style_keys.get(key)
        if idx is None:
            idx = len(self._style_list)
            self._style_list.append(key)
            self._style_keys[key] = idx
        return idx

    # ---- OOXML part builders -------------------------------------------

    def _content_types_xml(self):
        overrides = "".join(
            '<Override PartName="/xl/worksheets/sheet{0}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'.format(i)
            for i in range(1, len(self._sheets) + 1))
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">'
            '<Default Extension="rels" ContentType="application/'
            'vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '{}</Types>'.format(overrides))

    def _root_rels_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>')

    def _workbook_xml(self):
        entries = "".join(
            '<sheet name="{}" sheetId="{}" r:id="rId{}"/>'.format(
                _xml_escape(sheet.name), i, i)
            for i, sheet in enumerate(self._sheets, 1))
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" xmlns:r="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>{}</sheets></workbook>'.format(entries))

    def _workbook_rels_xml(self):
        n = len(self._sheets)
        rels = "".join(
            '<Relationship Id="rId{0}" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/'
            'worksheet" Target="worksheets/sheet{0}.xml"/>'.format(i)
            for i in range(1, n + 1))
        rels += (
            '<Relationship Id="rId{0}" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/'
            'styles" Target="styles.xml"/>'.format(n + 1))
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">{}</Relationships>'.format(rels))

    def _styles_xml(self):
        font_index = {}
        fonts = []

        def font_idx(bold, size):
            key = (bold, size)
            if key not in font_index:
                font_index[key] = len(fonts)
                fonts.append('<font>{}<sz val="{}"/><name val="Calibri"/>'
                             '</font>'.format("<b/>" if bold else "", size))
            return font_index[key]

        # Indexes 0 and 1 are the two fills Excel always expects to find
        # (none / gray125) even though nothing here uses gray125 - leaving
        # them out is the kind of omission that makes Excel offer to
        # "repair" an otherwise-valid file.
        fill_index = {None: 0}
        fills = ['<fill><patternFill patternType="none"/></fill>',
                 '<fill><patternFill patternType="gray125"/></fill>']

        def fill_idx(rgb):
            if rgb is None:
                return 0
            if rgb not in fill_index:
                fill_index[rgb] = len(fills)
                fills.append(
                    '<fill><patternFill patternType="solid">'
                    '<fgColor rgb="FF{0}"/><bgColor indexed="64"/>'
                    '</patternFill></fill>'.format(rgb))
            return fill_index[rgb]

        xfs = []
        for bold, size, fill in self._style_list:
            fi = font_idx(bold, size)
            fl = fill_idx(fill)
            apply_font = ' applyFont="1"' if (bold or size != 11) else ""
            apply_fill = ' applyFill="1"' if fill else ""
            xfs.append(
                '<xf numFmtId="0" fontId="{}" fillId="{}" borderId="0" '
                'xfId="0"{}{}/>'.format(fi, fl, apply_font, apply_fill))

        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">'
            '<fonts count="{0}">{1}</fonts>'
            '<fills count="{2}">{3}</fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/>'
            '<diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
            'borderId="0"/></cellStyleXfs>'
            '<cellXfs count="{4}">{5}</cellXfs>'
            # Excel expects a named "Normal" cell style pointing at
            # cellStyleXfs entry 0 even though nothing here uses it by
            # name - without it, some readers (and older Excel builds)
            # treat the file as missing its default style and offer to
            # "repair" it on open.
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
            'builtinId="0"/></cellStyles>'
            '</styleSheet>'.format(
                len(fonts), "".join(fonts), len(fills), "".join(fills),
                len(xfs), "".join(xfs)))

    # ---- writing ---------------------------------------------------------

    def save(self, filepath):
        if not self._sheets:
            raise ValueError("workbook has no sheets to write")

        clr.AddReference("System.IO.Compression")
        try:
            clr.AddReference("System.IO.Compression.FileSystem")
        except:
            pass
        from System.IO import FileStream, FileMode, FileAccess, FileShare
        from System.IO.Compression import ZipArchive, ZipArchiveMode
        from System.Text import Encoding

        # FileShare.Read (not the .NET default of None) so a report that
        # replaces one still open for VIEWING in another app fails with
        # the same clear sharing-violation message either way - it is the
        # caller's job to explain that, not this module's to guess at it
        # by trying to be more permissive than Windows already allows.
        stream = FileStream(filepath, FileMode.Create, FileAccess.Write,
                            FileShare.Read)
        try:
            archive = ZipArchive(stream, ZipArchiveMode.Create)
            try:
                self._write_entry(archive, "[Content_Types].xml",
                                  self._content_types_xml())
                self._write_entry(archive, "_rels/.rels", self._root_rels_xml())
                self._write_entry(archive, "xl/workbook.xml", self._workbook_xml())
                self._write_entry(archive, "xl/_rels/workbook.xml.rels",
                                  self._workbook_rels_xml())
                self._write_entry(archive, "xl/styles.xml", self._styles_xml())
                for i, sheet in enumerate(self._sheets, 1):
                    self._write_entry(archive, "xl/worksheets/sheet{}.xml".format(i),
                                      sheet._to_xml())
            finally:
                archive.Dispose()
        finally:
            stream.Close()

    def _write_entry(self, archive, name, text):
        entry = archive.CreateEntry(name)
        es = entry.Open()
        try:
            from System.Text import Encoding
            data = Encoding.UTF8.GetBytes(text)
            es.Write(data, 0, len(data))
        finally:
            es.Close()
