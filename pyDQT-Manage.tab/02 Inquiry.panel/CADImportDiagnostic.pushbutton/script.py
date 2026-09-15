# -*- coding: utf-8 -*-
"""CAD Import Diagnostic (temporary) v1.0
Author: Dang Quoc Truong (DQT)

READ-ONLY - makes no change to the model at all.

Root-causes why a CAD import can be missing from CAD Import Manager /
Model Health Check even when it is a real, top-level element on an open
workset, not in a Group, not in a secondary Design Option: it directly
compares what a plain FilteredElementCollector(doc).OfClass(ImportInstance)
finds against what the same query PLUS .WhereElementIsNotElementType()
finds (the exact filter both tools use), and looks up specific Element
IDs directly, to see exactly where a given CAD import drops out.

This tool is meant to be removed once the investigation it exists for is
done - it has no help page and does not follow the full pyDQT UI theme,
since it is a one-off diagnostic, not a permanent feature.
"""
__title__ = "CAD Import\nDiagnostic"
__author__ = "DQT"

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

import traceback
import System
from Autodesk.Revit.DB import *
from pyrevit import revit, script, forms
from pyrevit.compat import get_elementid_value_func

# Edit these if you're chasing different Element IDs than the ones ACC's
# Model Analytics originally reported.
TARGET_IDS = [12577938, 12986291]

get_elementid_value = get_elementid_value_func()


def eid_int(x):
    if x is None:
        return -1
    return get_elementid_value(x)


def make_element_id(doc, value):
    """ElementId construction that works whether this Revit build wants
    an Int32 or Int64 constructor overload."""
    try:
        return ElementId(value)
    except:
        pass
    try:
        return ElementId(System.Int64(value))
    except:
        pass
    return ElementId(System.Int32(value))


def type_name_of(doc, elem):
    """Best-effort CAD file / type name, same fallback order CAD Import
    Manager's own _cad_type_name uses."""
    try:
        p = elem.LookupParameter("Name")
        if p and p.HasValue:
            val = p.AsString()
            if val:
                return val
    except:
        pass
    try:
        cad_type = doc.GetElement(elem.GetTypeId())
        if cad_type:
            val = Element.Name.GetValue(cad_type)
            if val:
                return val
    except:
        pass
    return "<Unnamed> (ID {})".format(eid_int(elem.Id))


def run_diagnostic(doc, output):
    output.print_md("## CAD Import Diagnostic - {}".format(doc.Title))
    output.print_md("**This makes no change to the model - read-only.**")

    # 1) Raw class-only collector vs. the +WhereElementIsNotElementType
    #    filter CAD Import Manager / Model Health Check actually use.
    raw = list(FilteredElementCollector(doc).OfClass(ImportInstance))
    typed = list(FilteredElementCollector(doc).OfClass(ImportInstance)
                 .WhereElementIsNotElementType())

    output.print_md("---")
    output.print_md("### 1. Collector comparison")
    output.print_md("- `OfClass(ImportInstance)` alone: **{}** element(s)".format(len(raw)))
    output.print_md("- `OfClass(ImportInstance).WhereElementIsNotElementType()` "
                     "(what CAD Import Manager uses): **{}** element(s)".format(len(typed)))

    raw_ids = set(eid_int(e.Id) for e in raw)
    typed_ids = set(eid_int(e.Id) for e in typed)
    dropped_by_type_filter = raw_ids - typed_ids

    if dropped_by_type_filter:
        output.print_md(
            "**{} element(s) are found by the raw collector but DROPPED by "
            "`.WhereElementIsNotElementType()`** - this is the bug, if so:"
            .format(len(dropped_by_type_filter)))
        for eid in sorted(dropped_by_type_filter):
            elem = doc.GetElement(make_element_id(doc, eid))
            name = type_name_of(doc, elem) if elem else "?"
            output.print_md("  - ID **{}** - {}".format(eid, name))
    else:
        output.print_md("No difference - `.WhereElementIsNotElementType()` "
                         "is not the problem here.")

    # 2) Every distinct CAD file name visible in each set, so a name that
    #    only appears in the raw set (never in typed) stands out immediately.
    raw_names = sorted(set(type_name_of(doc, e) for e in raw))
    typed_names = sorted(set(type_name_of(doc, e) for e in typed))

    output.print_md("---")
    output.print_md("### 2. Distinct CAD file names per set")
    output.print_md("**Raw set** ({} names): {}".format(
        len(raw_names), ", ".join(raw_names) or "(none)"))
    output.print_md("**Typed set** ({} names): {}".format(
        len(typed_names), ", ".join(typed_names) or "(none)"))

    names_only_in_raw = sorted(set(raw_names) - set(typed_names))
    if names_only_in_raw:
        output.print_md("**Names that disappear once "
                         "`.WhereElementIsNotElementType()` is applied:** {}"
                         .format(", ".join(names_only_in_raw)))

    # 3) Direct ID lookup for the elements ACC Model Analytics reported.
    output.print_md("---")
    output.print_md("### 3. Direct lookup of the ACC-reported IDs")
    for target in TARGET_IDS:
        elem = doc.GetElement(make_element_id(doc, target))
        if elem is None:
            output.print_md("- ID **{}**: `doc.GetElement()` returned "
                             "**None** (not resolvable in this session at "
                             "all)".format(target))
            continue
        is_type = False
        try:
            is_type = isinstance(elem, ElementType)
        except:
            pass
        output.print_md(
            "- ID **{}**: class=`{}`, category=`{}`, is ElementType={}, "
            "in RAW set={}, in TYPED set={}, name={}".format(
                target, elem.GetType().Name,
                elem.Category.Name if elem.Category else "None",
                is_type, target in raw_ids, target in typed_ids,
                type_name_of(doc, elem)))

    output.print_md("---")
    output.print_md("Copy everything above and share it back for the actual fix.")


if __name__ == "__main__":
    try:
        if not revit.doc:
            forms.alert("Please open a project first.", title="DQT - CAD Import Diagnostic")
        else:
            run_diagnostic(revit.doc, script.get_output())
    except Exception as ex:
        forms.alert("Error:\n{}\n\n{}".format(str(ex), traceback.format_exc()),
                    title="DQT - CAD Import Diagnostic - Error")
