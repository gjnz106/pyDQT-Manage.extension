# -*- coding: utf-8 -*-
"""List Walls

List all Basic Wall types. On a Legend view they are placed as Legend
Components; on a Floor Plan they are drawn as real walls on the view's
level. Each is labelled, optionally with its full layer buildup.

Shift-Click: settings (spacing, text style, bold, include buildup).
"""
__title__ = "List\nWalls"
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
import walltypesconfig
from pyrevit import revit, DB, forms

BIC = DB.BuiltInCategory
doc = revit.doc
view = revit.active_view

LINE_LENGTH = 7.5
TEXT_OFFSET = 8.5
COMPACT_OFFSET = 2.5
SPACED_OFFSET = 5

# -- configuration --
v_offset_choice = walltypesconfig.get_config("v_offset", doc)
v_offset = COMPACT_OFFSET if v_offset_choice == "Compact" else SPACED_OFFSET
text_bold_choice = walltypesconfig.get_config("text_bold")
text_style_id = DB.ElementId(walltypesconfig.get_config("text_style"))
if not doc.GetElement(text_style_id):
    text_style_id = tu.get_default_text_type_id(doc)
include_wall_buildup = walltypesconfig.get_config("include_buildup")

label_offset = DB.XYZ(TEXT_OFFSET, 0, 0)


def get_level_from_view(v):
    lvl_param = v.get_Parameter(DB.BuiltInParameter.PLAN_VIEW_LEVEL)
    if not lvl_param:
        return None
    for lvl in DB.FilteredElementCollector(doc).OfClass(DB.Level):
        if lvl.Name == lvl_param.AsString():
            return lvl
    return None


def place_wall(loc, view_level):
    p1 = loc + DB.XYZ(0, -1, 0)
    p2 = loc.Add(DB.XYZ(LINE_LENGTH, -1, 0))
    curve = DB.Line.CreateBound(p1, p2)
    try:
        return DB.Wall.Create(doc, curve, view_level.Id, True)
    except Exception as e:
        print("Error placing wall: {}".format(e))
        return None


def format_wall_layers(wall_type):
    description = "\n\nTotal Thickness {}:".format(
        tu.length_to_display_string(wall_type.Width, doc))
    structure = wall_type.GetCompoundStructure()
    if structure:
        for layer in structure.GetLayers():
            width = tu.length_to_display_string(layer.Width, doc)
            material = doc.GetElement(layer.MaterialId)
            material_name = material.Name if material else "ByCategory"
            description += "\n\t- {} - {} - {}".format(width, layer.Function, material_name)
    return description


location = tu.pick_point_or_exit("Pick point for the walls list")

coll_wall_types = DB.FilteredElementCollector(doc) \
    .OfCategory(BIC.OST_Walls).OfClass(DB.WallType).WhereElementIsElementType()

dict_walls = {}
layers_count = {}
for wall_type in coll_wall_types:
    if wall_type.Kind.ToString() != "Basic":  # skip Curtain / Stacked
        continue
    type_name = wall_type.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
    if include_wall_buildup:
        type_name += format_wall_layers(wall_type)
        cs = wall_type.GetCompoundStructure()
        layers_count[type_name] = len(cs.GetLayers()) if cs else 1
    dict_walls.setdefault(type_name, wall_type)

if not dict_walls:
    forms.alert("No Basic Wall types found in this project.", exitscript=True)

with revit.Transaction(tu.DQT_TXN + "List Walls"):
    source_legend_component = None
    initial_translation = None
    level = None

    if view.ViewType == DB.ViewType.Legend:
        source_legend_component = DB.FilteredElementCollector(doc, view.Id).OfCategory(
            BIC.OST_LegendComponents).FirstElement()
        forms.alert_ifnot(
            source_legend_component,
            "The legend must contain at least one Legend Component to copy.\n"
            "Place any Legend Component on this legend (it can be deleted later), then re-run.",
            exitscript=True)
        source_bb = source_legend_component.get_BoundingBox(view)
        initial_translation = -(source_bb.Max + source_bb.Min) / 2
    elif view.ViewType == DB.ViewType.FloorPlan:
        level = get_level_from_view(view)
        if not level:
            forms.alert("Could not resolve the level for this Floor Plan view.", exitscript=True)
    else:
        forms.alert("Active view must be a Legend or a Floor Plan.", exitscript=True)

    for name in sorted(dict_walls):
        if include_wall_buildup:
            if layers_count.get(name, 1) == 1:
                vertical_offset = v_offset * 1.5
            else:
                vertical_offset = v_offset * layers_count[name]
        else:
            vertical_offset = v_offset

        offset = DB.XYZ(0, -vertical_offset, 0)
        header = tu.place_label(name, location.Add(label_offset), view, text_style_id)
        if text_bold_choice == 1:
            tu.set_bold(header)

        if view.ViewType == DB.ViewType.Legend:
            copy_id = DB.ElementTransformUtils.CopyElement(
                doc, source_legend_component.Id, initial_translation)[0]
            new_component = doc.GetElement(copy_id)
            wall_type = dict_walls[name]
            new_component.get_Parameter(DB.BuiltInParameter.LEGEND_COMPONENT).Set(wall_type.Id)
            new_component.get_Parameter(DB.BuiltInParameter.LEGEND_COMPONENT_VIEW).Set(-8)
            new_component.get_Parameter(DB.BuiltInParameter.LEGEND_COMPONENT_LENGTH).Set(LINE_LENGTH)
            wall_thickness = wall_type.Width
            DB.ElementTransformUtils.MoveElement(
                doc, new_component.Id, location - DB.XYZ(0, wall_thickness / 2, 0))
            location = location.Add(offset)

        elif view.ViewType == DB.ViewType.FloorPlan:
            new_wall = place_wall(location, level)
            if new_wall:
                try:
                    new_wall.WallType = dict_walls[name]
                except Exception as e:
                    print("Error changing wall type for {}: {}".format(name, e))
            location = location.Add(offset)
