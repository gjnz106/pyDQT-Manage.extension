# -*- coding: utf-8 -*-
"""List Filled Regions

Draw a rectangle with each Filled Region type and a label next to it, so
all filled region patterns can be reviewed on one view.
"""
__title__ = "List Filled\nRegions"
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
from pyrevit.framework import List
from rpw.ui.forms import (FlexForm, Label, ComboBox, TextBox, Button)

doc = revit.doc
view = revit.active_view

coll_fill_reg = DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType)
unsorted = {fr: tu.get_element_name(fr) for fr in coll_fill_reg}
if not unsorted:
    forms.alert("No Filled Region types found in this project.", exitscript=True)
sorted_fillreg = OrderedDict(sorted(unsorted.items(), key=lambda t: t[1].lower()))

text_style_dict = tu.get_text_types(doc)
if not text_style_dict:
    forms.alert("No Text Note Types found in this project.", exitscript=True)

components = [
    Label("Pick Text Style"),
    ComboBox(name="textstyle_combobox", options=text_style_dict),
    Label("Box Width [mm]"),
    TextBox(name="box_width", Text="800"),
    Label("Box Height [mm]"),
    TextBox(name="box_height", Text="300"),
    Label("Offset [mm]"),
    TextBox(name="box_offset", Text="100"),
    Button("Select")
]
form = FlexForm("List Filled Regions", components)
if not form.show():
    sys.exit()

text_style = form.values["textstyle_combobox"]
try:
    box_width = float(form.values["box_width"])
    box_height = float(form.values["box_height"])
    box_offset = float(form.values["box_offset"])
except ValueError:
    forms.alert("Width / height / offset must be numbers.", exitscript=True)

# dims and scale
scale = float(view.Scale) / 100
w = tu.display_to_internal(box_width, doc) * scale
h = tu.display_to_internal(box_height, doc) * scale
text_offset = 1 * scale
shift = tu.display_to_internal(box_offset + box_height, doc) * scale

pt = tu.pick_point_or_exit("Pick point for the filled regions list")

# starting rectangle
p1 = DB.XYZ(pt.X, pt.Y, 0)
p2 = DB.XYZ(pt.X + w, pt.Y, 0)
p3 = DB.XYZ(pt.X + w, pt.Y + h, 0)
p4 = DB.XYZ(pt.X, pt.Y + h, 0)
rectangle = [
    DB.Line.CreateBound(p1, p2),
    DB.Line.CreateBound(p2, p3),
    DB.Line.CreateBound(p3, p4),
    DB.Line.CreateBound(p4, p1),
]

with revit.Transaction(tu.DQT_TXN + "List Filled Regions"):
    for fr in sorted_fillreg:
        t1 = DB.Transform.CreateTranslation(DB.XYZ(0, -shift, 0))
        rectangle = [line.CreateTransformed(t1) for line in rectangle]
        crv_loop = DB.CurveLoop.Create(List[DB.Curve](rectangle))

        DB.FilledRegion.Create(doc, fr.Id, view.Id, [crv_loop])

        t2 = DB.Transform.CreateTranslation(DB.XYZ(text_offset, 0, 0))
        label_position = rectangle[1].CreateTransformed(t2).GetEndPoint(1)
        label_txt = sorted_fillreg[fr]
        DB.TextNote.Create(doc, view.Id, label_position, label_txt, text_style.Id)
