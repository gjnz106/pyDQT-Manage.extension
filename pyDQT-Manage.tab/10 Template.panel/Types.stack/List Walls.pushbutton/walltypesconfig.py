# -*- coding: utf-8 -*-
"""List Walls - settings (shift-click)."""

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
from pyrevit import script, revit, DB, forms
from rpw.ui.forms import (FlexForm, Label, ComboBox, CheckBox, Button)

my_config = script.get_config()


def get_text_types(doc=None):
    doc = doc or revit.doc
    tt = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements()
    return {tu.get_element_name(t): tu.eid_int(t.Id) for t in tt}


def get_config(option, doc=None):
    doc = doc or revit.doc
    # pyRevit's get_option re-raises when the option is missing and no
    # non-None default is given, so guard it and fall through to defaults.
    try:
        val = my_config.get_option(option)
        if val is not None:
            return val
    except Exception:
        pass
    if option == "v_offset":
        return "Compact"
    if option == "text_bold":
        return 0
    if option == "include_buildup":
        return 0
    if option == "text_style":
        tt = get_text_types(doc)
        if tt:
            return list(tt.values())[0]
        return tu.eid_int(tu.get_default_text_type_id(doc))
    return None


def rwp_ui_show(doc=None):
    doc = doc or revit.doc
    text_types = get_text_types(doc)
    if not text_types:
        forms.alert("No Text Note Types found in this project.", exitscript=True)

    prev_style_eid = get_config("text_style", doc)
    prev_style_name = None
    for name, eid in text_types.items():
        if eid == prev_style_eid:
            prev_style_name = name
            break
    if prev_style_name is None:
        prev_style_name = list(text_types.keys())[0]

    prev_v = get_config("v_offset", doc)
    v_offset_options = ["Compact", "Spaced"]

    components = [
        Label("Vertical Offset"),
        ComboBox(name="v_offset", options=v_offset_options,
                 default=prev_v if prev_v in v_offset_options else "Compact"),
        Label("Text Style"),
        ComboBox(name="text_style", options=text_types.keys(), default=prev_style_name),
        CheckBox("text_bold", "Bold labels", default=bool(get_config("text_bold", doc))),
        CheckBox("include_buildup",
                 "Include wall buildup (layers, thickness, material)",
                 default=bool(get_config("include_buildup", doc))),
        Button("Remember")
    ]
    form = FlexForm("List Walls - Settings", components)
    if form.show():
        my_config.v_offset = form.values["v_offset"]
        my_config.text_style = text_types[form.values["text_style"]]
        my_config.text_bold = int(form.values["text_bold"])
        my_config.include_buildup = int(form.values["include_buildup"])
        script.save_config()


if __name__ == "__main__":
    rwp_ui_show()
