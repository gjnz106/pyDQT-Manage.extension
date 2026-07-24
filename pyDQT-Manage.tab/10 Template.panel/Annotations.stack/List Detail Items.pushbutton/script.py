# -*- coding: utf-8 -*-
"""List Detail Items

Place every Detail Component type (view-based and curve/line-based),
grouped by family with bold family headers and type labels, so all detail
items in the project can be reviewed on one view.
"""
__title__ = "List Detail\nItems"
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

import template_utils as tu
from pyrevit import revit, DB, forms
from rpw.ui.forms import (FlexForm, Label, ComboBox, TextBox, Button)

doc = revit.doc
view = revit.active_view

# --- appearance form ---
text_style_dict = tu.get_text_types(doc)
if not text_style_dict:
    forms.alert("No Text Note Types found in this project.", exitscript=True)

components = [
    Label("Pick Text Style"),
    ComboBox(name="textstyle_combobox", options=text_style_dict),
    Label("Row Spacing [mm]"),
    TextBox(name="spacing", Text="1000"),
    Label("Line Length (curve-based) [mm]"),
    TextBox(name="line_length", Text="2000"),
    Button("Select")
]
form = FlexForm("List Detail Items", components)
if not form.show():
    sys.exit()

text_style = form.values["textstyle_combobox"]
text_style_id = text_style.Id
try:
    spacing = tu.display_to_internal(float(form.values["spacing"]), doc)
    line_length = tu.display_to_internal(float(form.values["line_length"]), doc)
except ValueError:
    forms.alert("Spacing / line length must be numbers.", exitscript=True)

scale = float(view.Scale) / 100
row_gap = spacing * scale
line_length = line_length * scale
label_offset = DB.XYZ(2 * scale, 0, 0)


# --- collect detail component types, split by placement type ---
coll = DB.FilteredElementCollector(doc) \
    .OfCategory(DB.BuiltInCategory.OST_DetailComponents) \
    .OfClass(DB.FamilySymbol) \
    .WhereElementIsElementType()

dict_vb = {}
dict_cb = {}
for sym in coll:
    placement = sym.Family.FamilyPlacementType
    fam = sym.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM).AsString()
    typ = tu.get_element_name(sym)
    if placement == DB.FamilyPlacementType.ViewBased:
        dict_vb.setdefault(fam, {})[typ] = sym
    elif placement == DB.FamilyPlacementType.CurveBasedDetail:
        dict_cb.setdefault(fam, {})[typ] = sym

if not dict_vb and not dict_cb:
    forms.alert("No Detail Component types found in this project.", exitscript=True)


def activate(symbol):
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()


def advance_below(instance, point):
    """Move point below the placed instance + row gap."""
    bb = instance.get_BoundingBox(view)
    bb_h = (bb.Max.Y - bb.Min.Y) if bb else 0
    return DB.XYZ(point.X, point.Y - bb_h - row_gap, 0)


location = tu.pick_point_or_exit("Pick point for the detail items list")

with revit.Transaction(tu.DQT_TXN + "List Detail Items"):
    # view-based (point placement)
    for fam in sorted(dict_vb):
        header = tu.place_label("Family : " + fam, location.Add(label_offset), view, text_style_id)
        tu.set_bold(header)
        location = DB.XYZ(location.X, location.Y - row_gap, 0)

        for typ in sorted(dict_vb[fam]):
            sym = dict_vb[fam][typ]
            activate(sym)
            inst = doc.Create.NewFamilyInstance(location, sym, view)
            doc.Regenerate()
            tu.place_label("Type : " + typ, location.Add(label_offset), view, text_style_id)
            location = advance_below(inst, location)

        location = DB.XYZ(location.X, location.Y - row_gap, 0)

    # curve/line-based (line placement)
    for fam in sorted(dict_cb):
        header = tu.place_label("Family : " + fam, location.Add(label_offset), view, text_style_id)
        tu.set_bold(header)
        location = DB.XYZ(location.X, location.Y - row_gap, 0)

        for typ in sorted(dict_cb[fam]):
            sym = dict_cb[fam][typ]
            activate(sym)
            p1 = location
            p2 = location.Add(DB.XYZ(line_length, 0, 0))
            curve = DB.Line.CreateBound(p1, p2)
            inst = doc.Create.NewFamilyInstance(curve, sym, view)
            doc.Regenerate()
            tu.place_label("Type : " + typ, location.Add(label_offset), view, text_style_id)
            location = advance_below(inst, location)

        location = DB.XYZ(location.X, location.Y - row_gap, 0)
