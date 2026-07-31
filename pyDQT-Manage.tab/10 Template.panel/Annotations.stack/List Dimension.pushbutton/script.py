# -*- coding: utf-8 -*-
"""List Dimension

Draw one sample dimension for every Linear Dimension Type in the project,
each rendered in its own type, with a label, so all dimension styles can
be reviewed at a glance.

Only Linear-style Dimension Types can be previewed this way: the sample
is built from two short reference tick-lines plus a straight dimension
line, which is exactly what a Linear dimension is. Angular / Radial /
Diameter / Spot Elevation / Spot Coordinate / Spot Slope types each need
fundamentally different reference geometry (a shared vertex between two
lines, a curved reference, a single point on a face) - rather than guess
at that geometry and risk placing something wrong, this tool asks Revit
itself: it tries to re-type the sample dimension it just made to the
target type, and if Revit refuses (a mismatched style), that type is
skipped and named in the summary instead of faked.
"""
__title__ = "List\nDimension"
__author__ = "Dang Quoc Truong (DQT)"

# --- locate the extension's shared lib (robust to stack nesting) ---
import os as _os, sys as _sys
_probe = _os.path.dirname(_os.path.abspath(__file__))
for _ in range(8):
    _cand = _os.path.join(_probe, "lib")
    if _os.path.isfile(_os.path.join(_cand, "template_utils.py")):
        if _cand not in _sys.path:
            _sys.path.insert(0, _cand)
        break
    _parent = _os.path.dirname(_probe)
    if _parent == _probe:
        break
    _probe = _parent

import sys
from collections import OrderedDict

import template_utils as tu
from pyrevit import revit, DB, forms
from rpw.ui.forms import (FlexForm, Label, ComboBox, TextBox, Button)

doc = revit.doc
view = revit.active_view


def get_dimension_types(doc):
    """OrderedDict {name: DimensionType} sorted by name (case-insensitive)."""
    coll = DB.FilteredElementCollector(doc).OfClass(DB.DimensionType)
    pairs = [(tu.get_element_name(dt), dt) for dt in coll]
    return OrderedDict(sorted(pairs, key=lambda kv: kv[0].lower()))


def get_curve_reference(curve_elem):
    """A Reference to a just-created DetailCurve's geometry, tried the same
    multi-approach way this suite's Wall Dimension tool already relies on
    to work around Revit's inconsistent Reference availability."""
    try:
        gc = curve_elem.GeometryCurve
        if gc and gc.Reference:
            return gc.Reference
    except Exception:
        pass
    try:
        ref = DB.Reference(curve_elem)
        if ref:
            return ref
    except Exception:
        pass
    try:
        opts = DB.Options()
        opts.ComputeReferences = True
        opts.IncludeNonVisibleObjects = True
        opts.View = view
        geom = curve_elem.get_Geometry(opts)
        if geom:
            for obj in geom:
                try:
                    if getattr(obj, "Reference", None):
                        return obj.Reference
                except Exception:
                    continue
    except Exception:
        pass
    return None


def place_sample_dimension(dim_type, origin, span):
    """Try to create ONE sample dimension previewing dim_type, spanning
    `span` starting at `origin`. Returns (dimension, None) on success, or
    (None, reason) if dim_type is not a Linear-compatible style - cleaning
    up any helper geometry either way so a skipped type leaves nothing
    behind."""
    p1 = origin
    p2 = DB.XYZ(origin.X + span, origin.Y, origin.Z)
    tick1 = DB.Line.CreateBound(DB.XYZ(p1.X, p1.Y - 1.0, p1.Z),
                                 DB.XYZ(p1.X, p1.Y + 1.0, p1.Z))
    tick2 = DB.Line.CreateBound(DB.XYZ(p2.X, p2.Y - 1.0, p2.Z),
                                 DB.XYZ(p2.X, p2.Y + 1.0, p2.Z))

    dc1 = doc.Create.NewDetailCurve(view, tick1)
    dc2 = doc.Create.NewDetailCurve(view, tick2)
    doc.Regenerate()

    ref1 = get_curve_reference(dc1)
    ref2 = get_curve_reference(dc2)
    if not ref1 or not ref2:
        doc.Delete(dc1.Id)
        doc.Delete(dc2.Id)
        return None, "could not obtain reference geometry for the tick lines"

    ref_array = DB.ReferenceArray()
    ref_array.Append(ref1)
    ref_array.Append(ref2)

    dim_line = DB.Line.CreateBound(p1, p2)
    try:
        dim = doc.Create.NewDimension(view, dim_line, ref_array)
    except Exception as ex:
        doc.Delete(dc1.Id)
        doc.Delete(dc2.Id)
        return None, "Revit refused to create the dimension: {}".format(ex)

    if dim is None:
        doc.Delete(dc1.Id)
        doc.Delete(dc2.Id)
        return None, "Revit returned no dimension"

    try:
        dim.ChangeTypeId(dim_type.Id)
    except Exception:
        # Not a Linear-compatible style - remove the placeholder and the
        # tick lines it depends on rather than leave a wrongly-typed
        # sample in the view.
        try:
            doc.Delete(dim.Id)
        except Exception:
            pass
        doc.Delete(dc1.Id)
        doc.Delete(dc2.Id)
        return None, "not a Linear-style dimension type"

    doc.Regenerate()
    return dim, None


# --- appearance form ---
dim_types = get_dimension_types(doc)
if not dim_types:
    forms.alert("No Dimension Types found in this project.", exitscript=True)

text_style_dict = tu.get_text_types(doc)
if not text_style_dict:
    forms.alert("No Text Note Types found in this project.", exitscript=True)

components = [
    Label("Pick Text Style"),
    ComboBox(name="textstyle_combobox", options=text_style_dict),
    Label("Row Spacing [mm]"),
    TextBox(name="spacing", Text="1000"),
    Label("Dimension Span [mm]"),
    TextBox(name="span", Text="2000"),
    Button("Select")
]
form = FlexForm("List Dimension", components)
if not form.show():
    sys.exit()

text_style = form.values["textstyle_combobox"]
try:
    row_gap = tu.display_to_internal(float(form.values["spacing"]), doc)
    span = tu.display_to_internal(float(form.values["span"]), doc)
except ValueError:
    forms.alert("Row spacing / span must be numbers.", exitscript=True)

scale = float(view.Scale) / 100
row_gap = row_gap * scale
span = span * scale
label_offset = DB.XYZ(0, 1.5 * scale, 0)

location = tu.pick_point_or_exit("Pick point for the dimension list")

placed = 0
skipped = []
with revit.Transaction(tu.DQT_TXN + "List Dimension"):
    for name, dt in dim_types.items():
        try:
            dim, reason = place_sample_dimension(dt, location, span)
        except Exception as ex:
            dim, reason = None, str(ex)

        if dim is None:
            skipped.append((name, reason))
        else:
            placed += 1
            tu.place_label(name, location.Add(label_offset), view, text_style.Id)

        location = DB.XYZ(location.X, location.Y - row_gap, location.Z)

msg = "Placed {} of {} dimension type(s).".format(placed, len(dim_types))
if skipped:
    lines = ["  {} - {}".format(n, r) for n, r in skipped[:10]]
    more = "" if len(skipped) <= 10 else "\n  ... and {} more".format(len(skipped) - 10)
    msg += ("\n\nSkipped (non-linear style or unsupported):\n{}{}"
            .format("\n".join(lines), more))
forms.alert(msg, title="List Dimension")
