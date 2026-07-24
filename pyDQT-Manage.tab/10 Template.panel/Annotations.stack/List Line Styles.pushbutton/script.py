# -*- coding: utf-8 -*-
"""List Line Styles

Draw a short detail line for every Line Style (Object Styles > Lines
subcategory) with a label, so all line styles can be reviewed at a glance.
"""
__title__ = "List Line\nStyles"
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

text_style_dict = tu.get_text_types(doc)
if not text_style_dict:
    forms.alert("No Text Note Types found in this project.", exitscript=True)

components = [
    Label("Pick Text Style:"),
    ComboBox(name="textstyle_combobox", options=text_style_dict),
    Label("Vertical Offset [mm]:"),
    TextBox(name="offset", Text="500"),
    Button("Select")
]
form = FlexForm("List Line Styles", components)
if not form.show():
    sys.exit()

chosen_text_style = form.values["textstyle_combobox"]
try:
    vert_offset = float(form.values["offset"])
except ValueError:
    forms.alert("Vertical offset must be a number.", exitscript=True)

# collect line style subcategories, sorted by name
cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
subcats = [sc for sc in cat.SubCategories]
sorted_subcats = OrderedDict(
    sorted({sc: sc.Name for sc in subcats}.items(), key=lambda t: t[1].lower()))

# dims and scale
scale = float(view.Scale) / 100
w = 20 * scale
text_offset = 1 * scale
shift = tu.display_to_internal(vert_offset, doc) * scale

pick_point = tu.pick_point_or_exit("Pick point for the line styles list")

p1 = pick_point
p2 = DB.XYZ(pick_point.X + w, pick_point.Y, 0)
l1 = DB.Line.CreateBound(p1, p2)

with revit.Transaction(tu.DQT_TXN + "List Line Styles"):
    for ls in sorted_subcats.keys():
        t1 = DB.Transform.CreateTranslation(DB.XYZ(0, -shift, 0))
        l1 = l1.CreateTransformed(t1)
        new_line = doc.Create.NewDetailCurve(view, l1)
        gs = ls.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
        new_line.LineStyle = gs

        label_text = sorted_subcats[ls]
        t2 = DB.Transform.CreateTranslation(DB.XYZ(text_offset, 0, 0))
        text_position = l1.CreateTransformed(t2).GetEndPoint(1)
        DB.TextNote.Create(doc, view.Id, text_position, label_text, chosen_text_style.Id)
