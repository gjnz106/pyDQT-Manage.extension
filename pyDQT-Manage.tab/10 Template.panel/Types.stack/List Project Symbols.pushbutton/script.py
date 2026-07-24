# -*- coding: utf-8 -*-
"""List Project Symbols

Place project annotation symbols (tags, heads, marks...) on a Legend view,
grouped by Category > Family > Type with labels.

Shift-Click: pick which symbol categories to include.
"""
__title__ = "List Proj\nSymbols"
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

from collections import OrderedDict

import template_utils as tu
import listsymbolsconfig
from pyrevit import revit, DB, forms
from pyrevit.framework import List

doc = revit.doc
view = revit.active_view

if view.ViewType != DB.ViewType.Legend:
    forms.alert("Active view is not a Legend View.\n\n"
                "Project symbols can only be placed on a Legend.", exitscript=True)

categories = listsymbolsconfig.get_categories()
if not categories:
    categories = listsymbolsconfig.categories

cat_list = List[DB.BuiltInCategory](categories)
multicat_filter = DB.ElementMulticategoryFilter(cat_list)
collect = DB.FilteredElementCollector(doc) \
    .WherePasses(multicat_filter).WhereElementIsElementType()

ordered_symbols = OrderedDict()
for sym in collect:
    try:
        cat = sym.get_Parameter(DB.BuiltInParameter.ELEM_CATEGORY_PARAM).AsValueString()
        fam = sym.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM).AsString()
        typ = tu.get_element_name(sym)
    except Exception:
        continue
    if not cat:
        continue
    ordered_symbols.setdefault(cat, OrderedDict()).setdefault(fam, OrderedDict())[typ] = sym

if not ordered_symbols:
    forms.alert("No symbols found for the selected categories.", exitscript=True)

scale = float(view.Scale) / 100
offset = 5 * scale
text_offset = 5 * scale

pt = tu.pick_point_or_exit("Pick point for the symbols list")
position = pt

with revit.Transaction(tu.DQT_TXN + "List Project Symbols"):
    for cat in sorted(ordered_symbols):
        cat_label_position = DB.XYZ(position.X - text_offset, position.Y, 0)
        cat_note = tu.place_label(cat, cat_label_position, view, tu.get_default_text_type_id(doc))
        tu.set_bold(cat_note, caps=True)
        position = DB.XYZ(pt.X, position.Y - offset, 0)

        for fam in sorted(ordered_symbols[cat]):
            f_note = tu.place_label(fam, DB.XYZ(position.X, position.Y, 0), view,
                                    tu.get_default_text_type_id(doc))
            tu.set_bold(f_note)
            position = DB.XYZ(pt.X, position.Y - offset, 0)

            for fam_type in sorted(ordered_symbols[cat][fam]):
                sym = ordered_symbols[cat][fam][fam_type]
                if not sym.IsActive:
                    sym.Activate()
                    doc.Regenerate()
                inst = doc.Create.NewFamilyInstance(position, sym, view)
                doc.Regenerate()
                bb = inst.get_BoundingBox(view)
                bb_h = (bb.Max.Y - bb.Min.Y) if bb else 0
                tu.place_label(fam_type, DB.XYZ(position.X + text_offset, position.Y, 0),
                               view, tu.get_default_text_type_id(doc))
                position = DB.XYZ(pt.X, position.Y - (bb_h * scale) - offset * 0.5, 0)
            position = DB.XYZ(pt.X, position.Y - offset, 0)
        position = DB.XYZ(pt.X, position.Y - offset * 0.5, 0)
