# -*- coding: utf-8 -*-
"""
Template documentation helpers.

Shared by the pyDQT-Manage "Template" panel tools (List Detail Items /
Filled Regions / Line Styles / Project Symbols / Text Styles / Walls).
These tools lay every element of a given kind onto a legend / drafting
view with labels, to build a project standards / template sheet.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

from collections import OrderedDict

from pyrevit import revit, DB, forms, HOST_APP
from pyrevit.compat import get_elementid_value_func
from Autodesk.Revit import Exceptions

_get_eid_value = get_elementid_value_func()

# Transaction name prefix - part of the DQT suite identity
DQT_TXN = "DQT - "


def eid_int(eid):
    """Integer value of an ElementId - compatible Revit 2024-2027."""
    if eid is None:
        return -1
    return _get_eid_value(eid)


def get_element_name(element):
    """Best-effort element name (type name parameter, then .Name)."""
    try:
        p = element.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.HasValue:
            n = p.AsString()
            if n:
                return n
    except Exception:
        pass
    try:
        return element.Name
    except Exception:
        return "Unnamed"


def _length_internal_unit(doc):
    units = doc.GetUnits()
    if HOST_APP.is_newer_than(2021):
        return units.GetFormatOptions(DB.SpecTypeId.Length).GetUnitTypeId()
    return units.GetFormatOptions(DB.UnitType.UT_Length).DisplayUnits


def display_to_internal(value, doc=None):
    """Convert a value expressed in the project's length display units
    (usually mm) to Revit internal units."""
    doc = doc or revit.doc
    return DB.UnitUtils.ConvertToInternalUnits(
        float(value), _length_internal_unit(doc))


def length_to_display_string(internal_value, doc=None):
    """Format an internal length as a display-unit string (e.g. '200 mm')."""
    doc = doc or revit.doc
    units = doc.GetUnits()
    try:
        if HOST_APP.is_newer_than(2021):
            return DB.UnitFormatUtils.Format(
                units, DB.SpecTypeId.Length, internal_value, False)
        return DB.UnitFormatUtils.Format(
            units, DB.UnitType.UT_Length, internal_value, False, False)
    except Exception:
        return str(round(internal_value, 2))


def get_text_types(doc=None):
    """OrderedDict {name: TextNoteType} sorted by name (case-insensitive)."""
    doc = doc or revit.doc
    tt = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType)
    pairs = [(get_element_name(t), t) for t in tt]
    return OrderedDict(sorted(pairs, key=lambda kv: kv[0].lower()))


def get_default_text_type_id(doc=None):
    """Default TextNoteType id - safe fallback for labels."""
    doc = doc or revit.doc
    return doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType)


def pick_point_or_exit(title="Pick insertion point"):
    """Warning-bar point pick with consistent cancel / bad-view handling."""
    with forms.WarningBar(title=title):
        try:
            return revit.uidoc.Selection.PickPoint()
        except Exceptions.OperationCanceledException:
            forms.alert("Cancelled", ok=True, exitscript=True)
        except Exceptions.InvalidOperationException as ex:
            forms.alert(
                "Cannot pick a point on this view.\n\n"
                "Revit said: {}\n\n"
                "Use a Drafting View, Legend, Plan, Section or Elevation "
                "view, then re-run.".format(ex.Message),
                exitscript=True)


def set_bold(text_note, caps=False):
    """Make a placed TextNote bold (optionally all-caps)."""
    try:
        f = text_note.GetFormattedText()
        f.SetBoldStatus(True)
        if caps:
            f.SetAllCapsStatus(True)
        text_note.SetFormattedText(f)
    except Exception:
        pass
    return text_note


def place_label(text, point, view, text_type_id):
    """Create a TextNote label at point on view."""
    return DB.TextNote.Create(revit.doc, view.Id, point, text, text_type_id)
