# -*- coding: utf-8 -*-
"""List Text Styles

Place one text note per Text Note Type, each rendered in its own style,
so every text style in the project can be reviewed visually.
"""
__title__ = "List Text\nStyles"
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

import template_utils as tu
from pyrevit import revit, DB, forms

doc = revit.doc
view = revit.active_view

styles = tu.get_text_types(doc)  # OrderedDict name -> TextNoteType
if not styles:
    forms.alert("No Text Note Types found in this project.", exitscript=True)

pick_point = tu.pick_point_or_exit("Pick point for the text styles list")

offset = 0.0
with revit.Transaction(tu.DQT_TXN + "List Text Styles"):
    for name, ts in styles.items():
        text_position = DB.XYZ(pick_point.X, pick_point.Y - offset, 0)
        text_height = ts.get_Parameter(DB.BuiltInParameter.TEXT_SIZE).AsDouble()
        offset += (text_height * 2.75 * float(view.Scale))
        DB.TextNote.Create(doc, view.Id, text_position, name, ts.Id)
