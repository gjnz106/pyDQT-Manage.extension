# -*- coding: utf-8 -*-
"""
Shared view -> sheet lookup for the DQT Manage tools.

CAD Import Manager and Group Manager both need to say which sheet(s) a view
ends up on. The answer comes from the model's Viewports, so it is built ONCE
per load as a {view id: [sheet label, ...]} map and every row just looks its
view up - never one Viewport scan per row, which on a large model is what
made tools freeze on open.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

from Autodesk.Revit.DB import FilteredElementCollector, Viewport, ViewSheet


def _eid_int(eid):
    """ElementId -> int, across Revit 2024-2026 (.Value vs .IntegerValue)."""
    if eid is None:
        return -1
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def sheet_label(sheet):
    """"A101 - Ground Floor Plan" for a ViewSheet."""
    try:
        number = sheet.SheetNumber or ""
    except:
        number = ""
    try:
        name = sheet.Name or ""
    except:
        name = ""
    if number and name:
        return "{} - {}".format(number, name)
    return number or name or "(unnamed sheet)"


def build_view_sheet_map(doc):
    """{view id (int): [sheet label, ...]} from one pass over the Viewports.

    A view sits on one sheet, except a Legend, which can be on several - so
    the value is a list, sorted and without repeats. A view that is on no
    sheet is simply absent. Never raises: a failure gives a partial or empty
    map, i.e. "not on a sheet" for what could not be read."""
    mapping = {}
    labels = {}          # sheet id (int) -> label, or None if unreadable
    try:
        for vp in FilteredElementCollector(doc).OfClass(Viewport):
            try:
                sheet_key = _eid_int(vp.SheetId)
                if sheet_key not in labels:
                    sheet = doc.GetElement(vp.SheetId)
                    labels[sheet_key] = sheet_label(sheet) if sheet is not None else None
                label = labels[sheet_key]
                if label is None:
                    continue
                found = mapping.setdefault(_eid_int(vp.ViewId), [])
                if label not in found:
                    found.append(label)
            except:
                continue
    except:
        pass
    for found in mapping.values():
        found.sort()
    return mapping


def sheets_of_view(view, view_sheet_map):
    """The sheet label(s) a view is on. A sheet view is its own sheet (a CAD
    file or detail group placed straight onto a sheet). Empty list when the
    view is on no sheet."""
    if view is None:
        return []
    try:
        if isinstance(view, ViewSheet):
            return [sheet_label(view)]
        return list(view_sheet_map.get(_eid_int(view.Id), []))
    except:
        return []


def summarize(names, limit=3):
    """"A; B; C (+2 more)" - a cell-sized version of a long list. The full
    list belongs in the Detail dialog and the CSV export, not the grid."""
    names = [n for n in names if n]
    if len(names) <= limit:
        return "; ".join(names)
    return "{} (+{} more)".format("; ".join(names[:limit]), len(names) - limit)
