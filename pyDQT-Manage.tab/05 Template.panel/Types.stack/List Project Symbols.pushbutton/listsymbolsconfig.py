# -*- coding: utf-8 -*-
"""List Project Symbols - symbol category selection config.

Saved to and read from the SAME settings section, so the user's chosen
categories actually persist and are used on the next run.
"""

from pyrevit import revit, script, DB, forms

my_config = script.get_config()

# default list of annotation symbol categories
categories = [
    DB.BuiltInCategory.OST_DoorTags,
    DB.BuiltInCategory.OST_WindowTags,
    DB.BuiltInCategory.OST_RoomTags,
    DB.BuiltInCategory.OST_AreaTags,
    DB.BuiltInCategory.OST_WallTags,
    DB.BuiltInCategory.OST_CurtainWallPanelTags,
    DB.BuiltInCategory.OST_SectionHeads,
    DB.BuiltInCategory.OST_CalloutHeads,
    DB.BuiltInCategory.OST_CeilingTags,
    DB.BuiltInCategory.OST_FurnitureTags,
    DB.BuiltInCategory.OST_PlumbingFixtureTags,
    DB.BuiltInCategory.OST_ReferenceViewerSymbol,
    DB.BuiltInCategory.OST_GridHeads,
    DB.BuiltInCategory.OST_LevelHeads,
    DB.BuiltInCategory.OST_SpotElevSymbols,
    DB.BuiltInCategory.OST_ElevationMarks,
    DB.BuiltInCategory.OST_StairsTags,
    DB.BuiltInCategory.OST_StairsLandingTags,
    DB.BuiltInCategory.OST_StairsRunTags,
    DB.BuiltInCategory.OST_StairsSupportTags,
    DB.BuiltInCategory.OST_BeamSystemTags,
    DB.BuiltInCategory.OST_StructuralFramingTags,
    DB.BuiltInCategory.OST_ViewportLabel,
]


class CategoryItem(forms.TemplateListItem):
    pass


def _saved_names():
    return my_config.get_option("chosen_categories", [])


def config_categories():
    """Shift-click UI: pick the categories to include."""
    prev = _saved_names()
    revit_cats = []
    for bic in categories:
        try:
            c = revit.query.get_category(bic)
            if c:
                revit_cats.append(c)
        except Exception:
            pass

    chosen = forms.SelectFromList.show(
        sorted(
            [CategoryItem(c, checked=(c.Name in prev), name_attr="Name")
             for c in revit_cats],
            key=lambda x: x.name),
        title="Select Symbol Categories",
        button_name="Apply",
        multiselect=True)

    if chosen:
        my_config.chosen_categories = [c.Name for c in chosen]
        script.save_config()
    return chosen


def get_categories():
    """Return the saved categories as BuiltInCategory values (or [])."""
    bics = []
    for name in _saved_names():
        try:
            bics.append(revit.query.get_builtincategory(name))
        except Exception:
            pass
    return bics


if __name__ == "__main__":
    config_categories()
