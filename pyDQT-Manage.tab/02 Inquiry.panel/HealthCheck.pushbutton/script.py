# -*- coding: utf-8 -*-
"""
Model Health Check v2.1 - DQT
Analyzes Revit model health with color-coded metrics dashboard.
Features: Gauge dashboard, Select Elements, Weighted score, Purgeable elements.
Pure code-behind WPF for IronPython stability.

v2.0: a 3-level RAG health scale (Green / Amber / Red) instead of the
6-level one, and the metrics presented in order of their impact on model
performance and stability (Critical / High / Moderate / Low impact).

v2.1: a Linked Models tab - every Revit link checked with the same metrics
and thresholds, one row per linked file, with its full dashboard on Open.
A metric that cannot be measured (the file size of a cloud model, which
has no local file) shows N/A and is left out of the score.

Copyright (c) 2025 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "Model\nHealth"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "Analyze model health with color-coded metrics and gauge dashboard."

# ============================================================
# IMPORTS
# ============================================================
import clr
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

import System
import System.Diagnostics
from System import Environment, Math
from System.Collections.Generic import List
from System.Windows import (
    Window, Thickness, HorizontalAlignment, VerticalAlignment,
    WindowStartupLocation, Visibility, TextWrapping, FontWeights,
    GridLength, GridUnitType, MessageBox, MessageBoxButton, MessageBoxImage,
    MessageBoxResult, CornerRadius as WinCornerRadius, Point
)
import System.Windows.Controls as WPFControls
from System.Windows.Controls import (
    StackPanel, Border, TextBlock, Button, ScrollViewer, Canvas,
    ColumnDefinition, RowDefinition, Orientation, ScrollBarVisibility,
    ToolTip
)
# TextBox is deliberately NOT imported bare here: Autodesk.Revit.UI (wildcard-
# imported below, after this) also defines a class named TextBox - its
# ribbon-panel text box control, which has no public constructor - and a
# wildcard import always wins over an earlier explicit one of the same
# name. A bare TextBox() therefore silently resolves to the wrong class
# and fails at runtime with "Cannot create instances of TextBox because
# it has no public constructors". Always construct it as
# WPFControls.TextBox() instead, the same defensive pattern already used
# for WPFGrid = WPFControls.Grid against the identical Grid collision.
from System.Windows.Media import (
    SolidColorBrush, Color, BrushConverter, Pen,
    PathGeometry, PathFigure, ArcSegment, SweepDirection,
    PenLineCap
)
from System.Windows.Shapes import Path, Ellipse
from System.Windows.Input import Cursors

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import script
from dqt_cad_utils import is_cad_link, is_cad_link_type, get_unused_cad_types

WPFGrid = WPFControls.Grid

import os
import datetime
import codecs
import copy
import json
from collections import OrderedDict


def _open_help_page(html_filename):
    """Open this tool's page from the shared _Inquiry_Help folder in the
    default browser. Returns True on success, False if the caller should
    fall back to the in-app help text (e.g. the folder went missing)."""
    try:
        panel_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(panel_dir, "_Inquiry_Help", html_filename)
        if not os.path.isfile(path):
            return False
        os.startfile(path)
        return True
    except Exception:
        return False


# ============================================================
# DQT BRAND COLORS
# ============================================================
DQT_PRIMARY = "#F0CC88"
DQT_PRIMARY_DARK = "#D4B87A"
DQT_BACKGROUND = "#FEF8E7"
DQT_TEXT_DARK = "#5D4E37"
DQT_TEXT = "#333333"
DQT_BORDER = "#D4B87A"

HEALTH_GREEN = "#4CAF50"
HEALTH_AMBER = "#FFB300"
HEALTH_RED = "#D32F2F"

BC = BrushConverter()
def brush(hex_color):
    return BC.ConvertFromString(hex_color)

# ============================================================
# RAG HEALTH SCALE - every metric, and the model as a whole, is one of
# three levels. A 3-level scale reads faster than the old 6-level one:
# it says straight away whether action is needed.
# ============================================================
RAG_GREEN = "Green"
RAG_AMBER = "Amber"
RAG_RED = "Red"
RAG_LEVELS = [RAG_GREEN, RAG_AMBER, RAG_RED]
RAG_COLORS = {RAG_GREEN: HEALTH_GREEN, RAG_AMBER: HEALTH_AMBER, RAG_RED: HEALTH_RED}
RAG_MEANING = {
    RAG_GREEN: "Healthy, meeting expectations",
    RAG_AMBER: "Needs attention, improvement recommended",
    RAG_RED: "Action required, high risk or major impact",
}
# Short form for the overall model result under the gauge.
RAG_SHORT = {RAG_GREEN: "Healthy", RAG_AMBER: "Needs Attention",
             RAG_RED: "Action Required"}
# Text on a coloured cell: white reads on green and red, not on amber.
RAG_TEXT_COLORS = {RAG_GREEN: "#FFFFFF", RAG_AMBER: DQT_TEXT, RAG_RED: "#FFFFFF"}
# A metric's contribution to the weighted score.
RAG_SCORES = {RAG_GREEN: 100, RAG_AMBER: 50, RAG_RED: 0}
# A metric that could not be measured (value None) - shown, never scored.
NOT_MEASURED = "N/A"
NA_COLOR = "#E0E0E0"
NA_MEANING = "not measured"
# Overall result from the weighted score: Green from 90, Amber from 60
# (the old grade A / grades B-C / grades D-F).
OVERALL_GREEN_MIN = 90
OVERALL_AMBER_MIN = 60

# ============================================================
# IMPACT TIERS - the metrics are listed by how much they hurt the model,
# not as if every metric mattered equally. Each tier's default weight in
# the overall score follows from it.
# ============================================================
IMPACT_TIERS = OrderedDict([
    ("Critical", {"weight": 5, "description":
        "Most likely to cause performance issues, instability, file bloat "
        "and user frustration."}),
    ("High", {"weight": 4, "description":
        "Affect manageability, model quality and long-term maintainability."}),
    ("Moderate", {"weight": 3, "description":
        "Affect manageability and model quality, to a lesser degree."}),
    ("Low", {"weight": 2, "description":
        "Model housekeeping rather than performance issues."}),
])

# ============================================================
# METRICS - in priority order (most impact first), which is the order
# the dashboard, the Settings tab and the report list them in.
# thresholds: [Green <=, Amber <=] - anything above the Amber value is Red.
# weight: 1-5, how much the metric counts toward the overall score.
# ============================================================
METRIC_THRESHOLDS = OrderedDict([
    # ---- Critical impact ----
    ("warnings", {
        "label": "Warnings",
        "impact": "Critical",
        "thresholds": [500, 1000],
        "tooltip": "Total warnings. High count = model instability.",
        "unit": "",
        "selectable": False,
        "weight": 5
    }),
    ("cad_imports", {
        "label": "CAD Imports",
        "impact": "Critical",
        "thresholds": [2, 5],
        "tooltip": "Imported CAD (not linked), plus CAD types left with no instances. Bloats file size significantly, and orphaned types keep being reported by ACC Model Analytics.",
        "unit": "",
        "selectable": True,
        "weight": 5
    }),
    ("file_size_mb", {
        "label": "File Size (MB)",
        "impact": "Critical",
        "thresholds": [250, 500],
        "tooltip": "Model file size. Large files slow loading and sync.",
        "unit": "MB",
        "selectable": False,
        "weight": 5
    }),
    ("in_place_families", {
        "label": "In-Place Families",
        "impact": "Critical",
        "thresholds": [15, 30],
        "tooltip": "In-Place families can't be reused, increase file size.",
        "unit": "",
        "selectable": True,
        "weight": 5
    }),
    # ---- High impact ----
    ("duplicate_elements", {
        "label": "Duplicate Elements",
        "impact": "High",
        "thresholds": [10, 30],
        "tooltip": "Elements of same type overlapping at same location. Cause double counting and visual issues.",
        "unit": "",
        "selectable": True,
        "weight": 4
    }),
    ("cad_links", {
        "label": "CAD Links",
        "impact": "High",
        "thresholds": [25, 50],
        "tooltip": "Linked CAD files. Many links degrade navigation.",
        "unit": "",
        "selectable": True,
        "weight": 4
    }),
    ("rvt_links", {
        "label": "RVT Links",
        "impact": "High",
        "thresholds": [20, 35],
        "tooltip": "Linked Revit files. Too many = slow performance.",
        "unit": "",
        "selectable": True,
        "weight": 4
    }),
    # ---- Moderate impact ----
    ("imported_images", {
        "label": "Imported Images",
        "impact": "Moderate",
        "thresholds": [15, 30],
        "tooltip": "Embedded raster images. Each one bloats file size and can go missing if the source file moves.",
        "unit": "",
        "selectable": True,
        "weight": 3
    }),
    ("groups", {
        "label": "Model Groups",
        "impact": "Moderate",
        "thresholds": [50, 100],
        "tooltip": "Model groups placed in the model. Many or large groups slow editing and regeneration.",
        "unit": "",
        "selectable": True,
        "weight": 3
    }),
    ("design_options", {
        "label": "Design Options",
        "impact": "Moderate",
        "thresholds": [5, 8],
        "tooltip": "Design Options add complexity and memory usage.",
        "unit": "",
        "selectable": True,
        "weight": 3
    }),
    # ---- Low impact ----
    ("rooms_unplaced", {
        "label": "Unplaced Rooms",
        "impact": "Low",
        "thresholds": [5, 15],
        "tooltip": "Unplaced rooms cause errors in schedules.",
        "unit": "",
        "selectable": True,
        "weight": 2
    }),
    ("linked_dwg_not_pinned", {
        "label": "Unpinned Links",
        "impact": "Low",
        "thresholds": [3, 8],
        "tooltip": "Unpinned links can be accidentally moved.",
        "unit": "",
        "selectable": True,
        "weight": 2
    }),
])

# The weights v1.x shipped with. A settings file saved by v1.x holds a
# full snapshot (every metric's weight, edited or not), so a saved weight
# equal to its old default is treated as "never edited" and the new
# impact-based default is used instead.
LEGACY_DEFAULT_WEIGHTS = {
    "file_size_mb": 4, "warnings": 5, "cad_imports": 5,
    "in_place_families": 4, "rvt_links": 2, "cad_links": 3,
    "imported_images": 3, "groups": 3, "design_options": 1,
    "rooms_unplaced": 2, "linked_dwg_not_pinned": 2,
    "duplicate_elements": 4,
}

# The hardcoded values above, snapshotted before any saved override is
# applied - "Reset to Defaults" in the Settings tab restores from this,
# never from METRIC_THRESHOLDS itself (which gets mutated in place below).
METRIC_THRESHOLDS_DEFAULTS = copy.deepcopy(METRIC_THRESHOLDS)

# ============================================================
# CUSTOM THRESHOLDS - user-editable via the Settings tab, persisted to
# disk so a change survives closing the tool. Only "thresholds" and
# "weight" are ever overridden: label/tooltip/unit/selectable describe
# the metric itself, not a policy the tool measures it against, so they
# always come from the hardcoded definition above.
# ============================================================
THRESHOLD_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "threshold_config.json")


def _load_threshold_overrides():
    """{key: {"thresholds": [...], "weight": N}} from disk, or {} if the
    file is missing, unreadable, or not valid JSON - a broken settings
    file must never stop the tool from opening; it just falls back to
    the hardcoded defaults for every entry."""
    if not os.path.isfile(THRESHOLD_CONFIG_PATH):
        return {}
    try:
        with open(THRESHOLD_CONFIG_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _numbers_in_order(t, count):
    """`count` non-decreasing numbers (a bool is not a number here)."""
    if not isinstance(t, list) or len(t) != count:
        return False
    for x in t:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return False
    return all(t[i] <= t[i + 1] for i in range(count - 1))


def _valid_thresholds_list(t):
    """[Green <=, Amber <=]: 2 non-decreasing numbers - the shape
    get_status_text actually needs. Anything else (wrong length,
    non-numeric, out of order, or a bool masquerading as a number) is
    rejected so a corrupted or hand-edited settings file can only ever
    fall back to the default for that one metric, never break the
    scoring math."""
    return _numbers_in_order(t, 2)


def _legacy_thresholds_to_rag(t):
    """A v1.x 6-level threshold list (the upper bounds of Good /
    Acceptable / Warning / Concerning / Critical) as [Green <=, Amber <=]:
    Green is the old Good + Acceptable, Amber the old Warning, Red the
    old Concerning and worse - the levels v1.x already flagged for
    action. None when `t` is not a valid v1.x list."""
    if not _numbers_in_order(t, 5):
        return None
    return [t[1], t[2]]


def _parse_threshold_number(text):
    """One Settings-tab textbox's text -> int (or float, if it genuinely
    has a fractional part) - every hardcoded default is a whole number,
    so keeping a typed "100" as 100 rather than 100.0 matches what the
    user wrote and what a re-opened Settings tab would show back."""
    text = (text or "").strip()
    if not text:
        raise ValueError("value cannot be blank")
    try:
        v = float(text)
    except ValueError:
        raise ValueError("'{}' is not a number".format(text))
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("'{}' is not a valid number".format(text))
    return int(v) if v == int(v) else v


def _apply_threshold_overrides():
    """Merge saved overrides onto METRIC_THRESHOLDS in place, so every
    place below that reads METRIC_THRESHOLDS[key]["thresholds"]/["weight"]
    - scoring, coloring, the heatmap, the Excel/HTML export - automatically
    sees the customized values with no other change needed. An entry for
    an unknown key, or one that fails validation, is simply skipped and
    that metric keeps its hardcoded default.

    A file saved by v1.x (6-level scale) is read too: its 5 thresholds
    are converted to Green/Amber, and a weight still equal to its v1.x
    default gives way to the new impact-based default."""
    for key, val in _load_threshold_overrides().items():
        if key not in METRIC_THRESHOLDS or not isinstance(val, dict):
            continue
        t = val.get("thresholds")
        legacy = _legacy_thresholds_to_rag(t)
        if legacy is not None:
            t = legacy
        if _valid_thresholds_list(t):
            METRIC_THRESHOLDS[key]["thresholds"] = list(t)
        w = val.get("weight")
        if isinstance(w, int) and not isinstance(w, bool) and 1 <= w <= 5:
            if legacy is not None and w == LEGACY_DEFAULT_WEIGHTS.get(key):
                continue
            METRIC_THRESHOLDS[key]["weight"] = w


def _save_threshold_overrides():
    """Persist the CURRENT thresholds/weight for every metric - not only
    the ones that differ from the hardcoded default - so the file on disk
    is a complete, self-describing snapshot: readable on its own, and
    reloading it always reproduces exactly what was on screen when Save
    was pressed."""
    data = {}
    for key, cfg in METRIC_THRESHOLDS.items():
        data[key] = {"thresholds": list(cfg["thresholds"]), "weight": cfg.get("weight", 1)}
    with open(THRESHOLD_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _reset_threshold_overrides():
    """Restore every metric's thresholds/weight to the hardcoded default
    and remove the saved settings file, so a fresh run of the tool (no
    file at all) behaves identically to right after Reset."""
    for key, cfg in METRIC_THRESHOLDS_DEFAULTS.items():
        METRIC_THRESHOLDS[key]["thresholds"] = list(cfg["thresholds"])
        METRIC_THRESHOLDS[key]["weight"] = cfg.get("weight", 1)
    if os.path.isfile(THRESHOLD_CONFIG_PATH):
        try:
            os.remove(THRESHOLD_CONFIG_PATH)
        except Exception:
            pass


_apply_threshold_overrides()


# ============================================================
# MODEL HEALTH ANALYZER
# ============================================================
class ModelHealthAnalyzer:
    def __init__(self, doc):
        self.doc = doc
        self.metrics = OrderedDict()
        self.element_ids = {}

    def analyze(self):
        self._file_size()
        self._warnings()
        self._cad_imports()
        self._in_place_families()
        self._rvt_links()
        self._cad_links()
        self._imported_images()
        self._groups()
        self._design_options()
        self._unplaced_rooms()
        self._unpinned_links()
        self._duplicate_elements()
        return self.metrics

    def _store_ids(self, key, elements):
        ids = []
        for elem in elements:
            try:
                ids.append(elem.Id)
            except:
                pass
        self.element_ids[key] = ids

    def _file_size(self):
        """Size of the model's file on disk; None (not measured) when there
        is no local file to read - an unsaved model, or a cloud model, whose
        path is not a path on this computer."""
        try:
            path = self.doc.PathName
            if path and os.path.isfile(path):
                self.metrics["file_size_mb"] = round(os.path.getsize(path) / (1024.0 * 1024.0), 1)
            else:
                self.metrics["file_size_mb"] = None
        except:
            self.metrics["file_size_mb"] = None

    def _warnings(self):
        try:
            w = self.doc.GetWarnings()
            self.metrics["warnings"] = len(w) if w else 0
        except:
            self.metrics["warnings"] = 0

    def _cad_imports(self):
        """Embedded CAD: placed import instances PLUS orphaned CAD types.

        A CAD type left with zero instances still sits in the file and is
        still reported by ACC's Model Analytics (which counts CAD at the
        TYPE level), so leaving it out made this metric read 0 for models
        that demonstrably still carried imported CAD. Classification goes
        through the shared dqt_cad_utils.is_cad_link rather than raw
        ImportInstance.IsLinked, which is missing on some Revit 2026
        builds - and was being swallowed by a bare except, silently
        dropping the element from BOTH this metric and CAD Links."""
        try:
            col = FilteredElementCollector(self.doc).OfClass(ImportInstance).WhereElementIsNotElementType()
            elems = []
            for inst in col:
                try:
                    if not is_cad_link(self.doc, inst):
                        elems.append(inst)
                except:
                    pass
            try:
                # a type left behind by a LINK is not an import
                elems.extend(t for t in get_unused_cad_types(self.doc)
                             if not is_cad_link_type(t))
            except:
                pass
            self.metrics["cad_imports"] = len(elems)
            self._store_ids("cad_imports", elems)
        except:
            self.metrics["cad_imports"] = 0

    def _in_place_families(self):
        try:
            col = FilteredElementCollector(self.doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
            elems = []
            for fi in col:
                try:
                    if fi.Symbol and fi.Symbol.Family and fi.Symbol.Family.IsInPlace:
                        elems.append(fi)
                except:
                    pass
            self.metrics["in_place_families"] = len(elems)
            self._store_ids("in_place_families", elems)
        except:
            self.metrics["in_place_families"] = 0

    def _rvt_links(self):
        try:
            col = FilteredElementCollector(self.doc).OfClass(RevitLinkInstance).WhereElementIsNotElementType()
            elems = list(col)
            self.metrics["rvt_links"] = len(elems)
            self._store_ids("rvt_links", elems)
        except:
            self.metrics["rvt_links"] = 0

    def _cad_links(self):
        try:
            col = FilteredElementCollector(self.doc).OfClass(ImportInstance).WhereElementIsNotElementType()
            elems = []
            for inst in col:
                try:
                    if is_cad_link(self.doc, inst):
                        elems.append(inst)
                except:
                    pass
            self.metrics["cad_links"] = len(elems)
            self._store_ids("cad_links", elems)
        except:
            self.metrics["cad_links"] = 0

    def _imported_images(self):
        try:
            # Same collection this suite's Image Manager tool uses for the
            # same elements - every raster Image placed into the model -
            # plus (see Image Manager's own get_images for the live bug
            # this closes) any image type Revit still tracks as an
            # external file reference (Insert > Manage Links > Images,
            # which unifies both "Import" and "Link" raster images into
            # one list) with no instance placed in any view. A model can
            # have images Manage Links lists that this collector alone
            # would silently miss entirely.
            col = FilteredElementCollector(self.doc).OfClass(ImageInstance).WhereElementIsNotElementType()
            elems = list(col)
            placed_type_ids = set()
            for e in elems:
                try:
                    placed_type_ids.add(e.GetTypeId())
                except:
                    pass
            try:
                refs = self.doc.GetAllExternalFileReferences()
                for type_id, efr in refs.items():
                    try:
                        if efr.ExternalFileReferenceType != ExternalFileReferenceType.Image:
                            continue
                        if type_id in placed_type_ids:
                            continue
                        img_type = self.doc.GetElement(type_id)
                        if img_type is not None:
                            elems.append(img_type)
                            placed_type_ids.add(type_id)
                    except:
                        continue
            except:
                pass
            self.metrics["imported_images"] = len(elems)
            self._store_ids("imported_images", elems)
        except:
            self.metrics["imported_images"] = 0

    def _groups(self):
        # Model groups only - detail groups are view annotation, not part
        # of the model's performance picture.
        try:
            col = FilteredElementCollector(self.doc).OfCategory(BuiltInCategory.OST_IOSModelGroups).WhereElementIsNotElementType()
            elems = list(col)
            self.metrics["groups"] = len(elems)
            self._store_ids("groups", elems)
        except:
            self.metrics["groups"] = 0

    def _design_options(self):
        try:
            col = FilteredElementCollector(self.doc).OfClass(DesignOption).WhereElementIsNotElementType()
            elems = list(col)
            self.metrics["design_options"] = len(elems)
            self._store_ids("design_options", elems)
        except:
            self.metrics["design_options"] = 0

    def _unplaced_rooms(self):
        try:
            col = FilteredElementCollector(self.doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
            elems = []
            for room in col:
                try:
                    if room.Location is None:
                        elems.append(room)
                except:
                    pass
            self.metrics["rooms_unplaced"] = len(elems)
            self._store_ids("rooms_unplaced", elems)
        except:
            self.metrics["rooms_unplaced"] = 0

    def _unpinned_links(self):
        try:
            elems = []
            for link in FilteredElementCollector(self.doc).OfClass(RevitLinkInstance).WhereElementIsNotElementType():
                try:
                    if not link.Pinned:
                        elems.append(link)
                except:
                    pass
            for inst in FilteredElementCollector(self.doc).OfClass(ImportInstance).WhereElementIsNotElementType():
                try:
                    # same link test as CAD Imports / CAD Links, so a cloud
                    # DWG link is not missed here either
                    if is_cad_link(self.doc, inst) and not inst.Pinned:
                        elems.append(inst)
                except:
                    pass
            self.metrics["linked_dwg_not_pinned"] = len(elems)
            self._store_ids("linked_dwg_not_pinned", elems)
        except:
            self.metrics["linked_dwg_not_pinned"] = 0

    def _duplicate_elements(self):
        """Find duplicate elements using Revit Warnings API.
        Reads warnings with message 'identical instances in the same place'
        which is exactly what Revit uses to detect duplicates.
        This is the most accurate method - matches Revit's own detection.
        """
        try:
            warnings = self.doc.GetWarnings()
            dupe_ids_set = set()
            
            if warnings:
                for warning in warnings:
                    try:
                        desc = warning.GetDescriptionText()
                        # Revit's exact warning for duplicate elements
                        if "identical instances" in desc.lower() and "same place" in desc.lower():
                            # Get all element IDs involved in this warning
                            failing = warning.GetFailingElements()
                            additional = warning.GetAdditionalElements()
                            
                            if failing:
                                for eid in failing:
                                    dupe_ids_set.add(eid)
                            if additional:
                                for eid in additional:
                                    dupe_ids_set.add(eid)
                    except:
                        pass
            
            # Convert to element list for selection
            dupe_ids = list(dupe_ids_set)
            self.metrics["duplicate_elements"] = len(dupe_ids)
            self.element_ids["duplicate_elements"] = dupe_ids
        except:
            self.metrics["duplicate_elements"] = 0


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_status_text(key, value):
    """The metric's RAG level: Green up to the Green value, Amber up to
    the Amber value, Red above it ("N/A" for an unknown metric, or one
    that could not be measured)."""
    if key not in METRIC_THRESHOLDS or value is None:
        return NOT_MEASURED
    t = METRIC_THRESHOLDS[key]["thresholds"]
    if value <= t[0]: return RAG_GREEN
    elif value <= t[1]: return RAG_AMBER
    else: return RAG_RED

def get_health_color(key, value):
    return RAG_COLORS.get(get_status_text(key, value), NA_COLOR)

def get_status_meaning(status):
    return RAG_MEANING.get(status, NA_MEANING)

def status_text_color(status):
    """Colour for a status written on white: the RAG colour, a darker
    amber (amber text on white is hard to read), grey when not measured."""
    if status == RAG_AMBER:
        return "#B07800"
    return RAG_COLORS.get(status, "#888888")

def format_value(key, value):
    """"120.5 MB", "40", or "N/A" when not measured."""
    if value is None:
        return NOT_MEASURED
    unit = METRIC_THRESHOLDS.get(key, {}).get("unit", "")
    return "{}{}".format(value, " " + unit if unit else "")

def get_text_color(key, value):
    """Text colour that reads on the metric's RAG colour."""
    return RAG_TEXT_COLORS.get(get_status_text(key, value), DQT_TEXT)

def get_health_score(metrics):
    """Weighted average of the metrics' RAG scores (Green 100, Amber 50,
    Red 0), 0-100."""
    weighted_total = 0
    weight_sum = 0
    for key, value in metrics.items():
        if key in METRIC_THRESHOLDS and value is not None:
            w = METRIC_THRESHOLDS[key].get("weight", 1)
            weighted_total += RAG_SCORES[get_status_text(key, value)] * w
            weight_sum += w
    return round(weighted_total / max(weight_sum, 1), 1)

def get_overall_status(score):
    """(RAG level, short label, colour) of the whole model from its
    weighted score."""
    if score >= OVERALL_GREEN_MIN: level = RAG_GREEN
    elif score >= OVERALL_AMBER_MIN: level = RAG_AMBER
    else: level = RAG_RED
    return level, RAG_SHORT[level], RAG_COLORS[level]

def count_statuses(metrics):
    """{"Green": n, "Amber": n, "Red": n} over the known, measured
    metrics."""
    counts = OrderedDict((level, 0) for level in RAG_LEVELS)
    for key, value in metrics.items():
        if key in METRIC_THRESHOLDS and value is not None:
            counts[get_status_text(key, value)] += 1
    return counts

def status_summary(counts):
    """One line on what the counts mean for the user."""
    red, amber = counts[RAG_RED], counts[RAG_AMBER]
    if red:
        return "{} Red metric(s) - action required. {} Amber.".format(red, amber)
    if amber:
        return "{} Amber metric(s) - improvement recommended.".format(amber)
    return "All metrics Green - the model is healthy."

def counts_text(counts):
    return "Total: {} metrics | Green: {} | Amber: {} | Red: {}".format(
        sum(counts.values()), counts[RAG_GREEN], counts[RAG_AMBER], counts[RAG_RED])

def metrics_by_impact(metrics):
    """[(tier, [(priority number, key), ...]), ...] - the analysed metrics
    in priority order (the order of METRIC_THRESHOLDS), grouped by impact
    tier. The number is the metric's place in the full priority list."""
    groups = OrderedDict((tier, []) for tier in IMPACT_TIERS)
    for number, key in enumerate(METRIC_THRESHOLDS, 1):
        if key in metrics:
            tier = METRIC_THRESHOLDS[key].get("impact", "Low")
            groups.setdefault(tier, []).append((number, key))
    return [(tier, items) for tier, items in groups.items() if items]

def thresholds_text(thresholds):
    return u"Green ≤ {0} | Amber ≤ {1} | Red > {1}".format(
        thresholds[0], thresholds[1])

def bar_scale(thresholds):
    """The value at the right end of the health bar: half again past the
    Amber value, so the Red zone shows as the last third of the bar."""
    return max(float(thresholds[1]) * 1.5, float(thresholds[1]) + 1, 1.0)

def recommended_keys(metrics):
    """Metrics that are Amber or Red, in priority order."""
    return [key for key in METRIC_THRESHOLDS if key in metrics
            and get_status_text(key, metrics[key]) in (RAG_AMBER, RAG_RED)]

RECOMMENDATIONS = {
    "file_size_mb": "Purge unused families, remove imported CAD files, audit model.",
    "warnings": "Review and resolve warnings. Start with most frequent types.",
    "cad_imports": "Delete imported CAD and purge CAD types left with no instances (CAD Import Manager > Purge Unused Types). Use linked CAD instead.",
    "in_place_families": "Convert In-Place to loadable families.",
    "rvt_links": "Review if all RVT links are necessary. Unload unused.",
    "cad_links": "Minimize CAD links. Convert to native Revit elements.",
    "imported_images": "Delete unused imported images. Link large raster files instead of embedding them.",
    "groups": "Ungroup where possible. Use families instead.",
    "design_options": "Finalize and accept primary design options.",
    "rooms_unplaced": "Place or delete unplaced rooms.",
    "linked_dwg_not_pinned": "Pin all linked files to prevent accidental movement.",
    "duplicate_elements": "Review and delete overlapping duplicate elements. They cause double counting in schedules and visual artifacts.",
}


# ============================================================
# LINKED MODELS - every Revit link, checked with the same metrics
# ============================================================
def _id_value(element_id):
    """ElementId -> int across Revit 2024-2027 (.Value vs .IntegerValue)."""
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def _html(text):
    """Text made safe to drop into the HTML report."""
    return (u"{}".format(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _element_name(element):
    if element is None:
        return ""
    try:
        return Element.Name.GetValue(element)
    except:
        pass
    try:
        return element.Name
    except:
        return ""


class LinkedModel(object):
    """One linked Revit file: its name, how many times it is placed, its
    document (None when the link is not loaded) and, once analysed, its
    metrics - or the error that stopped the analysis."""

    def __init__(self, name):
        self.name = name
        self.instances = 0
        self.doc = None
        self.metrics = None
        self.error = None

    @property
    def loaded(self):
        return self.doc is not None


def collect_linked_models(doc):
    """[LinkedModel] - one per linked file (link type), however many times
    it is placed, sorted by name. Cheap: nothing is analysed here."""
    found = OrderedDict()
    try:
        instances = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance)
                         .WhereElementIsNotElementType())
    except:
        instances = []
    for inst in instances:
        try:
            type_id = inst.GetTypeId()
            key = _id_value(type_id)
        except:
            continue
        model = found.get(key)
        if model is None:
            name = _element_name(doc.GetElement(type_id))
            model = LinkedModel(name or "Link {}".format(key))
            found[key] = model
        model.instances += 1
        if model.doc is None:
            try:
                model.doc = inst.GetLinkDocument()
            except:
                model.doc = None
    return sorted(found.values(), key=lambda m: m.name.lower())


def analyze_linked_model(model):
    """Run the 12 metrics on a loaded link. A link that is not loaded is
    left alone; an analysis that fails keeps its error for the table."""
    model.metrics = None
    model.error = None
    if model.doc is None:
        return model
    try:
        model.metrics = ModelHealthAnalyzer(model.doc).analyze()
    except Exception as ex:
        model.error = str(ex) or ex.__class__.__name__
    return model


def attention_text(metrics, limit=3):
    """"Warnings (Red), CAD Links (Amber)" - the Red metrics first, then
    the Amber ones, each in priority order, at most `limit` of them."""
    keys = recommended_keys(metrics)
    reds = [k for k in keys if get_status_text(k, metrics[k]) == RAG_RED]
    ordered = reds + [k for k in keys if k not in reds]
    parts = ["{} ({})".format(METRIC_THRESHOLDS[k]["label"],
                              get_status_text(k, metrics[k]))
             for k in ordered[:limit]]
    if len(ordered) > limit:
        parts.append("+{} more".format(len(ordered) - limit))
    return ", ".join(parts)


def link_row(model):
    """What the Linked Models table and the report show for one link."""
    row = {"name": model.name, "instances": model.instances,
           "status": "Loaded" if model.loaded else "Not loaded",
           "overall": "-", "score": "-", "red": "-", "amber": "-",
           "color": None, "text_color": DQT_TEXT, "note": ""}
    if not model.loaded:
        row["note"] = "Not loaded - reload it in Manage Links to check it"
    elif model.error:
        row["note"] = "Could not be read: " + model.error
    elif model.metrics is None:
        row["note"] = "Not analyzed yet"
    else:
        score = get_health_score(model.metrics)
        level, label, color = get_overall_status(score)
        counts = count_statuses(model.metrics)
        row.update(overall="{} - {}".format(level, label), score=str(score),
                   red=str(counts[RAG_RED]), amber=str(counts[RAG_AMBER]),
                   color=color, text_color=RAG_TEXT_COLORS[level],
                   note=attention_text(model.metrics) or "All metrics Green")
    return row


# ============================================================
# GAUGE WIDGET - Semi-circle gauge using WPF Path
# ============================================================
def create_gauge(score, size=120):
    """Create a semi-circle gauge widget showing score 0-100"""
    canvas = Canvas()
    canvas.Width = size
    canvas.Height = size * 0.7
    
    cx = size / 2.0
    cy = size * 0.6
    radius = size * 0.42
    stroke_width = size * 0.08
    
    # Background arc (gray)
    bg_arc = _create_arc_path(cx, cy, radius, 180, 360, "#E0E0E0", stroke_width)
    canvas.Children.Add(bg_arc)
    
    # Colored arc based on score
    if score <= 0:
        sweep = 0
    else:
        sweep = min(score / 100.0, 1.0) * 180
    
    if sweep > 0:
        _, _, color = get_overall_status(score)
        fg_arc = _create_arc_path(cx, cy, radius, 180, 180 + sweep, color, stroke_width)
        canvas.Children.Add(fg_arc)

    # Score text
    score_tb = TextBlock()
    score_tb.Text = str(score)
    score_tb.FontSize = size * 0.22
    score_tb.FontWeight = FontWeights.Bold
    _, _, sc = get_overall_status(score)
    score_tb.Foreground = brush(sc)
    score_tb.HorizontalAlignment = HorizontalAlignment.Center
    Canvas.SetLeft(score_tb, cx - size * 0.18)
    Canvas.SetTop(score_tb, cy - size * 0.28)
    canvas.Children.Add(score_tb)
    
    return canvas


def _create_arc_path(cx, cy, radius, start_angle, end_angle, color, stroke_width):
    """Create a WPF Path representing an arc"""
    p = Path()
    p.Stroke = brush(color)
    p.StrokeThickness = stroke_width
    p.StrokeStartLineCap = PenLineCap.Round
    p.StrokeEndLineCap = PenLineCap.Round
    p.Fill = None
    
    start_rad = start_angle * Math.PI / 180.0
    end_rad = end_angle * Math.PI / 180.0
    
    start_x = cx + radius * Math.Cos(start_rad)
    start_y = cy + radius * Math.Sin(start_rad)
    end_x = cx + radius * Math.Cos(end_rad)
    end_y = cy + radius * Math.Sin(end_rad)
    
    is_large = (end_angle - start_angle) > 180
    
    fig = PathFigure()
    fig.StartPoint = Point(start_x, start_y)
    fig.IsClosed = False
    
    arc = ArcSegment()
    arc.Point = Point(end_x, end_y)
    arc.Size = System.Windows.Size(radius, radius)
    arc.IsLargeArc = is_large
    arc.SweepDirection = SweepDirection.Clockwise
    
    fig.Segments.Add(arc)
    
    geo = PathGeometry()
    geo.Figures.Add(fig)
    p.Data = geo
    
    return p


# ============================================================
# WPF WINDOW
# ============================================================
class ModelHealthWindow(Window):
    def __init__(self, doc, uidoc, link_name=None):
        """The dashboard of the open model - or, with `link_name`, of one of
        its Revit links (read-only: no Select, no Settings, no links tab)."""
        self.doc = doc
        self.uidoc = uidoc
        self.metrics = OrderedDict()
        self.analyzer = None
        self.link_name = link_name
        self.is_link = link_name is not None
        self.linked_models = [] if self.is_link else collect_linked_models(doc)
        self.links_stack = None

        self.Title = "Model Health Check v2.1 - DQT"
        if self.is_link:
            self.Title += u" - Linked model: {}".format(link_name)
        self.Height = 900
        self.Width = 1400
        self.MinHeight = 700
        self.MinWidth = 1100
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Background = brush(DQT_BACKGROUND)

        self._build_ui()
        self._run_analysis()

    def _build_ui(self):
        root = WPFGrid()
        root.Margin = Thickness(14)

        for h in [
            GridLength(1, GridUnitType.Auto),   # header
            GridLength(1, GridUnitType.Auto),   # score + gauge
            GridLength(1, GridUnitType.Auto),   # legend
            GridLength(1, GridUnitType.Star),   # metrics
            GridLength(1, GridUnitType.Auto),   # recommendations
            GridLength(1, GridUnitType.Auto),   # footer
        ]:
            rd = RowDefinition()
            rd.Height = h
            root.RowDefinitions.Add(rd)

        header = self._make_header()
        WPFGrid.SetRow(header, 0)
        root.Children.Add(header)

        score_card = self._make_score_card()
        WPFGrid.SetRow(score_card, 1)
        root.Children.Add(score_card)

        legend = self._make_legend()
        WPFGrid.SetRow(legend, 2)
        root.Children.Add(legend)

        # Metrics
        metrics_border = Border()
        metrics_border.Background = brush("#FFFFFF")
        metrics_border.BorderBrush = brush(DQT_BORDER)
        metrics_border.BorderThickness = Thickness(1)
        metrics_border.CornerRadius = WinCornerRadius(6)
        metrics_border.Margin = Thickness(0, 0, 0, 10)
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
        self.metrics_stack = StackPanel()
        sv.Content = self.metrics_stack
        metrics_border.Child = sv
        WPFGrid.SetRow(metrics_border, 3)
        root.Children.Add(metrics_border)

        # Recommendations
        rec_border = Border()
        rec_border.Background = brush("#FFFFFF")
        rec_border.BorderBrush = brush(DQT_BORDER)
        rec_border.BorderThickness = Thickness(1)
        rec_border.CornerRadius = WinCornerRadius(6)
        rec_border.Padding = Thickness(12, 8, 12, 8)
        rec_border.Margin = Thickness(0, 0, 0, 8)
        rec_border.MaxHeight = 160
        rec_sv = ScrollViewer()
        rec_sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        self.rec_panel = StackPanel()
        rec_sv.Content = self.rec_panel
        rec_border.Child = rec_sv
        WPFGrid.SetRow(rec_border, 4)
        root.Children.Add(rec_border)

        footer = self._make_footer()
        WPFGrid.SetRow(footer, 5)
        root.Children.Add(footer)

        # ---- Tabs: the dashboard above, plus Settings to edit the
        # thresholds/weights BEFORE running an analysis, per request. ----
        self.tabs = WPFControls.TabControl()
        self.tabs.Background = brush(DQT_BACKGROUND)
        self.tabs.BorderThickness = Thickness(0)

        self.tab_dashboard = WPFControls.TabItem()
        self.tab_dashboard.Header = self._make_tab_header("Dashboard")
        self.tab_dashboard.Content = root
        self.tabs.Items.Add(self.tab_dashboard)

        # A linked model's dashboard is read-only: thresholds are edited
        # from the open model's window, and links are listed there.
        if not self.is_link:
            self.tab_links = WPFControls.TabItem()
            self.tab_links.Header = self._make_tab_header(
                u"Linked Models ({})".format(len(self.linked_models)))
            self.tab_links.Content = self._make_links_tab()
            self.tabs.Items.Add(self.tab_links)

            self.tab_settings = WPFControls.TabItem()
            self.tab_settings.Header = self._make_tab_header(u"⚙ Settings")
            self.tab_settings.Content = self._make_settings_tab()
            self.tabs.Items.Add(self.tab_settings)

        self.Content = self.tabs

    def _make_tab_header(self, text):
        tb = TextBlock()
        tb.Text = text
        tb.FontSize = 13
        tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = brush(DQT_TEXT_DARK)
        tb.Padding = Thickness(8, 3, 8, 3)
        return tb

    # ---- SETTINGS TAB: edit threshold bands + weight per metric ----
    def _make_settings_tab(self):
        outer = WPFGrid()
        outer.Margin = Thickness(14)
        for h in [GridLength(1, GridUnitType.Auto),   # intro
                  GridLength(1, GridUnitType.Star),   # table
                  GridLength(1, GridUnitType.Auto)]:  # save bar
            rd = RowDefinition()
            rd.Height = h
            outer.RowDefinitions.Add(rd)

        intro = Border()
        intro.Background = brush(DQT_PRIMARY)
        intro.CornerRadius = WinCornerRadius(6)
        intro.Padding = Thickness(16, 12, 16, 12)
        intro.Margin = Thickness(0, 0, 0, 10)
        intro_txt = TextBlock()
        intro_txt.Text = (
            u"Set the thresholds and weight used to grade each metric, "
            u"then “Save & Apply” before running Re-Analyze. "
            u"Each metric is Green up to its Green value, Amber up to its "
            u"Amber value, and Red above that. Weight (1-5) is how much "
            u"the metric counts toward the overall weighted score; by "
            u"default it follows the metric's impact (Critical 5, High 4, "
            u"Moderate 3, Low 2). Metrics are listed by impact, most "
            u"impact first.")
        intro_txt.FontSize = 13
        intro_txt.TextWrapping = TextWrapping.Wrap
        intro_txt.Foreground = brush(DQT_TEXT_DARK)
        intro.Child = intro_txt
        WPFGrid.SetRow(intro, 0)
        outer.Children.Add(intro)

        table_border = Border()
        table_border.Background = brush("#FFFFFF")
        table_border.BorderBrush = brush(DQT_BORDER)
        table_border.BorderThickness = Thickness(1)
        table_border.CornerRadius = WinCornerRadius(6)
        table_border.Margin = Thickness(0, 0, 0, 10)
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto

        # Column widths and cell padding/margins sized for FontSize 13 -
        # the same size the Dashboard's heatmap uses for its own row
        # content (metric label / value), so the two tabs read as one
        # consistent tool rather than Settings looking like a squeezed-in
        # afterthought.
        table = WPFGrid()
        table.Margin = Thickness(10)
        col_widths = [230, 110, 120, 120, 120]
        for w in col_widths:
            cd = ColumnDefinition()
            cd.Width = GridLength(w)
            table.ColumnDefinitions.Add(cd)

        headers = [u"Metric", u"Impact", u"Green ≤", u"Amber ≤",
                   u"Weight (1-5)"]
        header_row = RowDefinition()
        header_row.Height = GridLength(1, GridUnitType.Auto)
        table.RowDefinitions.Add(header_row)
        for ci, htext in enumerate(headers):
            htb = TextBlock()
            htb.Text = htext
            htb.FontSize = 13
            htb.FontWeight = FontWeights.Bold
            htb.Foreground = brush(DQT_TEXT_DARK)
            htb.Margin = Thickness(6, 8, 6, 8)
            htb.TextWrapping = TextWrapping.Wrap
            WPFGrid.SetRow(htb, 0)
            WPFGrid.SetColumn(htb, ci)
            table.Children.Add(htb)

        self._threshold_boxes = OrderedDict()
        row_i = 1
        for key, cfg in METRIC_THRESHOLDS.items():
            rd = RowDefinition()
            rd.Height = GridLength(1, GridUnitType.Auto)
            table.RowDefinitions.Add(rd)
            row_bg = brush("#FAF6EC") if row_i % 2 == 0 else brush("#FFFFFF")

            lbl = TextBlock()
            lbl.Text = cfg["label"]
            lbl.FontSize = 13
            lbl.FontWeight = FontWeights.SemiBold
            lbl.Foreground = brush(DQT_TEXT)
            lbl.VerticalAlignment = VerticalAlignment.Center
            lbl.Margin = Thickness(6, 6, 6, 6)
            lbl.Background = row_bg
            tip = cfg.get("tooltip", "")
            if tip:
                lbl.ToolTip = tip
            WPFGrid.SetRow(lbl, row_i)
            WPFGrid.SetColumn(lbl, 0)
            table.Children.Add(lbl)

            impact = cfg.get("impact", "")
            itb = TextBlock()
            itb.Text = impact
            itb.FontSize = 13
            itb.Foreground = brush(DQT_TEXT_DARK)
            itb.VerticalAlignment = VerticalAlignment.Center
            itb.Margin = Thickness(6, 6, 6, 6)
            itb.ToolTip = IMPACT_TIERS.get(impact, {}).get("description", "")
            WPFGrid.SetRow(itb, row_i)
            WPFGrid.SetColumn(itb, 1)
            table.Children.Add(itb)

            boxes = []
            for ci in range(2):
                tb = WPFControls.TextBox()
                tb.Text = str(cfg["thresholds"][ci])
                tb.FontSize = 13
                tb.Padding = Thickness(6, 5, 6, 5)
                tb.Margin = Thickness(4, 4, 4, 4)
                tb.HorizontalContentAlignment = HorizontalAlignment.Center
                tb.BorderBrush = brush(DQT_BORDER)
                tb.Background = brush("#FFFFFF")
                WPFGrid.SetRow(tb, row_i)
                WPFGrid.SetColumn(tb, ci + 2)
                table.Children.Add(tb)
                boxes.append(tb)

            wtb = WPFControls.TextBox()
            wtb.Text = str(cfg.get("weight", 1))
            wtb.FontSize = 13
            wtb.Padding = Thickness(6, 5, 6, 5)
            wtb.Margin = Thickness(4, 4, 4, 4)
            wtb.HorizontalContentAlignment = HorizontalAlignment.Center
            wtb.BorderBrush = brush(DQT_BORDER)
            wtb.Background = brush("#FFFFFF")
            WPFGrid.SetRow(wtb, row_i)
            WPFGrid.SetColumn(wtb, 4)
            table.Children.Add(wtb)

            self._threshold_boxes[key] = {"boxes": boxes, "weight_box": wtb}
            row_i += 1

        sv.Content = table
        table_border.Child = sv
        WPFGrid.SetRow(table_border, 1)
        outer.Children.Add(table_border)

        # Save bar: status text (left) + Reset/Save buttons (right)
        status_bar = WPFGrid()
        c1 = ColumnDefinition()
        c1.Width = GridLength(1, GridUnitType.Star)
        c2 = ColumnDefinition()
        c2.Width = GridLength(1, GridUnitType.Auto)
        status_bar.ColumnDefinitions.Add(c1)
        status_bar.ColumnDefinitions.Add(c2)

        self.txt_settings_status = TextBlock()
        self.txt_settings_status.FontSize = 12
        self.txt_settings_status.Foreground = brush("#888888")
        self.txt_settings_status.VerticalAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(self.txt_settings_status, 0)
        status_bar.Children.Add(self.txt_settings_status)

        btn_group = StackPanel()
        btn_group.Orientation = Orientation.Horizontal

        self.btn_reset_thresholds = Button()
        self.btn_reset_thresholds.Content = u"↺ Reset to Defaults"
        self.btn_reset_thresholds.Background = brush("#FFFFFF")
        self.btn_reset_thresholds.Foreground = brush(DQT_TEXT_DARK)
        self.btn_reset_thresholds.Padding = Thickness(12, 8, 12, 8)
        self.btn_reset_thresholds.BorderBrush = brush(DQT_PRIMARY_DARK)
        self.btn_reset_thresholds.BorderThickness = Thickness(1)
        self.btn_reset_thresholds.Margin = Thickness(0, 0, 8, 0)
        self.btn_reset_thresholds.Cursor = Cursors.Hand
        self.btn_reset_thresholds.Click += self._on_reset_thresholds
        btn_group.Children.Add(self.btn_reset_thresholds)

        self.btn_save_thresholds = Button()
        self.btn_save_thresholds.Content = "Save & Apply"
        self.btn_save_thresholds.Background = brush(DQT_PRIMARY)
        self.btn_save_thresholds.Foreground = brush(DQT_TEXT_DARK)
        self.btn_save_thresholds.FontWeight = FontWeights.SemiBold
        self.btn_save_thresholds.Padding = Thickness(16, 8, 16, 8)
        self.btn_save_thresholds.BorderBrush = brush(DQT_PRIMARY_DARK)
        self.btn_save_thresholds.BorderThickness = Thickness(1)
        self.btn_save_thresholds.Cursor = Cursors.Hand
        self.btn_save_thresholds.Click += self._on_save_thresholds
        btn_group.Children.Add(self.btn_save_thresholds)

        WPFGrid.SetColumn(btn_group, 1)
        status_bar.Children.Add(btn_group)

        WPFGrid.SetRow(status_bar, 2)
        outer.Children.Add(status_bar)

        return outer

    def _on_save_thresholds(self, sender, args):
        """Validate every row, then apply + persist in one all-or-nothing
        step - a bad value in one metric must never silently save the
        other 11 while leaving that one row's edit lost."""
        new_values = {}
        for key, refs in self._threshold_boxes.items():
            label = METRIC_THRESHOLDS[key]["label"]
            try:
                t = [_parse_threshold_number(tb.Text) for tb in refs["boxes"]]
            except ValueError as ex:
                MessageBox.Show(
                    u"{}: {}".format(label, ex),
                    "Invalid Value", MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            if not _valid_thresholds_list(t):
                MessageBox.Show(
                    u"{}: the Amber value cannot be smaller than the Green "
                    u"value\n(Green ≤ Amber).".format(label),
                    "Invalid Thresholds", MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            w_text = (refs["weight_box"].Text or "").strip()
            try:
                w = int(w_text)
                is_int = float(w_text) == w
            except Exception:
                is_int = False
            if not is_int or not (1 <= w <= 5):
                MessageBox.Show(
                    u"{}: Weight must be a whole number from 1 to 5.".format(label),
                    "Invalid Weight", MessageBoxButton.OK, MessageBoxImage.Warning)
                return
            new_values[key] = (t, w)

        for key, (t, w) in new_values.items():
            METRIC_THRESHOLDS[key]["thresholds"] = t
            METRIC_THRESHOLDS[key]["weight"] = w
        _save_threshold_overrides()

        # Re-score/re-render from the metrics already collected - no need
        # to re-query Revit, only the grading policy changed.
        if self.metrics:
            self._update_score()
            self._build_heatmap()
            self._build_recommendations()
        self._build_links_table()

        self.txt_settings_status.Text = "Saved and applied at {}.".format(
            datetime.datetime.now().strftime("%H:%M:%S"))
        self.tabs.SelectedItem = self.tab_dashboard

    def _on_reset_thresholds(self, sender, args):
        result = MessageBox.Show(
            "Reset every metric's thresholds and weight to the built-in "
            "defaults?\n\nThis also deletes the saved settings file.",
            "Reset to Defaults", MessageBoxButton.YesNo, MessageBoxImage.Question)
        if result != MessageBoxResult.Yes:
            return

        _reset_threshold_overrides()
        for key, refs in self._threshold_boxes.items():
            cfg = METRIC_THRESHOLDS[key]
            for ci, tb in enumerate(refs["boxes"]):
                tb.Text = str(cfg["thresholds"][ci])
            refs["weight_box"].Text = str(cfg.get("weight", 1))

        if self.metrics:
            self._update_score()
            self._build_heatmap()
            self._build_recommendations()
        self._build_links_table()

        self.txt_settings_status.Text = "Reset to built-in defaults."

    # ---- LINKED MODELS TAB: one row per linked file ----
    LINK_COLUMNS = [(u"LINKED MODEL", 300), (u"INSTANCES", 80),
                    (u"STATUS", 95), (u"OVERALL", 190), (u"SCORE", 65),
                    (u"RED", 50), (u"AMBER", 60), (u"NEEDS ATTENTION", 340),
                    (u"DASHBOARD", 95)]

    def _make_links_tab(self):
        outer = WPFGrid()
        outer.Margin = Thickness(14)
        for h in [GridLength(1, GridUnitType.Auto),   # intro
                  GridLength(1, GridUnitType.Star),   # table
                  GridLength(1, GridUnitType.Auto)]:  # action bar
            rd = RowDefinition()
            rd.Height = h
            outer.RowDefinitions.Add(rd)

        intro = Border()
        intro.Background = brush(DQT_PRIMARY)
        intro.CornerRadius = WinCornerRadius(6)
        intro.Padding = Thickness(16, 12, 16, 12)
        intro.Margin = Thickness(0, 0, 0, 10)
        intro_txt = TextBlock()
        intro_txt.Text = (
            u"Every Revit link in this model - one row per linked file - "
            u"checked with the same 12 metrics and thresholds as the "
            u"Dashboard. \u201cAnalyze Linked Models\u201d reads each "
            u"loaded link, which can take a while when there are many. A "
            u"link that is not loaded cannot be read: reload it in Manage "
            u"Links first. \u201cOpen\u201d shows a link's full dashboard.")
        intro_txt.FontSize = 13
        intro_txt.TextWrapping = TextWrapping.Wrap
        intro_txt.Foreground = brush(DQT_TEXT_DARK)
        intro.Child = intro_txt
        WPFGrid.SetRow(intro, 0)
        outer.Children.Add(intro)

        table_border = Border()
        table_border.Background = brush("#FFFFFF")
        table_border.BorderBrush = brush(DQT_BORDER)
        table_border.BorderThickness = Thickness(1)
        table_border.CornerRadius = WinCornerRadius(6)
        table_border.Margin = Thickness(0, 0, 0, 10)
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto
        self.links_stack = StackPanel()
        sv.Content = self.links_stack
        table_border.Child = sv
        WPFGrid.SetRow(table_border, 1)
        outer.Children.Add(table_border)

        bar = WPFGrid()
        c1 = ColumnDefinition()
        c1.Width = GridLength(1, GridUnitType.Star)
        c2 = ColumnDefinition()
        c2.Width = GridLength(1, GridUnitType.Auto)
        bar.ColumnDefinitions.Add(c1)
        bar.ColumnDefinitions.Add(c2)
        self.txt_links_status = TextBlock()
        self.txt_links_status.FontSize = 12
        self.txt_links_status.Foreground = brush("#888888")
        self.txt_links_status.VerticalAlignment = VerticalAlignment.Center
        WPFGrid.SetColumn(self.txt_links_status, 0)
        bar.Children.Add(self.txt_links_status)

        self.btn_analyze_links = Button()
        self.btn_analyze_links.Content = u"\u27F3 Analyze Linked Models"
        self.btn_analyze_links.Background = brush(DQT_PRIMARY)
        self.btn_analyze_links.Foreground = brush(DQT_TEXT_DARK)
        self.btn_analyze_links.FontWeight = FontWeights.SemiBold
        self.btn_analyze_links.Padding = Thickness(16, 8, 16, 8)
        self.btn_analyze_links.BorderBrush = brush(DQT_PRIMARY_DARK)
        self.btn_analyze_links.BorderThickness = Thickness(1)
        self.btn_analyze_links.Cursor = Cursors.Hand
        self.btn_analyze_links.IsEnabled = any(m.loaded for m in self.linked_models)
        self.btn_analyze_links.Click += self._on_analyze_links
        WPFGrid.SetColumn(self.btn_analyze_links, 1)
        bar.Children.Add(self.btn_analyze_links)
        WPFGrid.SetRow(bar, 2)
        outer.Children.Add(bar)

        loaded = sum(1 for m in self.linked_models if m.loaded)
        self.txt_links_status.Text = "{} linked file(s), {} loaded.".format(
            len(self.linked_models), loaded)
        self._build_links_table()
        return outer

    def _link_cell(self, table, row, col, text, background, foreground=DQT_TEXT,
                   bold=False, center=False):
        b = Border()
        b.Background = brush(background)
        b.BorderBrush = brush("#E8E0D0")
        b.BorderThickness = Thickness(0, 0, 1, 1)
        b.Padding = Thickness(10, 6, 10, 6)
        t = TextBlock()
        t.Text = text
        t.FontSize = 12
        t.Foreground = brush(foreground)
        t.VerticalAlignment = VerticalAlignment.Center
        t.TextWrapping = TextWrapping.Wrap
        if bold:
            t.FontWeight = FontWeights.SemiBold
        if center:
            t.HorizontalAlignment = HorizontalAlignment.Center
        b.Child = t
        WPFGrid.SetRow(b, row)
        WPFGrid.SetColumn(b, col)
        table.Children.Add(b)
        return b

    def _build_links_table(self):
        """(Re)draw the Linked Models table from self.linked_models - called
        after an analysis and whenever the thresholds change."""
        if self.links_stack is None:
            return
        self.links_stack.Children.Clear()
        if not self.linked_models:
            none = TextBlock()
            none.Text = "This model has no Revit links."
            none.FontSize = 13
            none.Foreground = brush("#888888")
            none.Margin = Thickness(14)
            self.links_stack.Children.Add(none)
            return

        table = WPFGrid()
        for _, width in self.LINK_COLUMNS:
            cd = ColumnDefinition()
            cd.Width = GridLength(width)
            table.ColumnDefinitions.Add(cd)
        rd = RowDefinition()
        rd.Height = GridLength(36)
        table.RowDefinitions.Add(rd)
        for ci, (title, _) in enumerate(self.LINK_COLUMNS):
            cell = self._link_cell(table, 0, ci, title, DQT_PRIMARY,
                                   DQT_TEXT_DARK, bold=True)
            cell.BorderBrush = brush(DQT_PRIMARY_DARK)
            cell.BorderThickness = Thickness(0, 0, 1, 2)

        for index, model in enumerate(self.linked_models):
            r = index + 1
            rd = RowDefinition()
            rd.Height = GridLength(1, GridUnitType.Auto)
            rd.MinHeight = 40
            table.RowDefinitions.Add(rd)
            row = link_row(model)
            bg = "#FFFFFF" if r % 2 == 0 else "#FAF8F0"
            self._link_cell(table, r, 0, row["name"], bg, bold=True)
            self._link_cell(table, r, 1, str(row["instances"]), bg, center=True)
            self._link_cell(table, r, 2, row["status"], bg,
                            DQT_TEXT if model.loaded else HEALTH_RED)
            self._link_cell(table, r, 3, row["overall"], row["color"] or bg,
                            row["text_color"], bold=row["color"] is not None,
                            center=True)
            self._link_cell(table, r, 4, row["score"], bg, center=True)
            self._link_cell(table, r, 5, row["red"], bg,
                            HEALTH_RED if row["red"] not in ("-", "0") else DQT_TEXT,
                            center=True)
            self._link_cell(table, r, 6, row["amber"], bg,
                            "#B07800" if row["amber"] not in ("-", "0") else DQT_TEXT,
                            center=True)
            self._link_cell(table, r, 7, row["note"], bg, "#666666")

            action = Border()
            action.Background = brush(bg)
            action.BorderBrush = brush("#E8E0D0")
            action.BorderThickness = Thickness(0, 0, 0, 1)
            action.Padding = Thickness(4)
            btn = Button()
            btn.Content = u"Open \u25B8"
            btn.FontSize = 11
            btn.Padding = Thickness(10, 4, 10, 4)
            btn.Background = brush("#FFFFFF")
            btn.Foreground = brush(DQT_TEXT_DARK)
            btn.BorderBrush = brush(DQT_PRIMARY_DARK)
            btn.BorderThickness = Thickness(1)
            btn.Cursor = Cursors.Hand
            btn.HorizontalAlignment = HorizontalAlignment.Center
            btn.VerticalAlignment = VerticalAlignment.Center
            btn.IsEnabled = model.loaded
            btn.Tag = index
            btn.Click += self._on_open_link
            action.Child = btn
            WPFGrid.SetRow(action, r)
            WPFGrid.SetColumn(action, 8)
            table.Children.Add(action)

        self.links_stack.Children.Add(table)

    def _on_analyze_links(self, sender, args):
        for model in self.linked_models:
            analyze_linked_model(model)
        self._build_links_table()
        analyzed = sum(1 for m in self.linked_models if m.metrics is not None)
        not_loaded = sum(1 for m in self.linked_models if not m.loaded)
        failed = sum(1 for m in self.linked_models if m.error)
        text = "Analyzed {} linked model(s) at {}.".format(
            analyzed, datetime.datetime.now().strftime("%H:%M:%S"))
        if not_loaded:
            text += " {} not loaded.".format(not_loaded)
        if failed:
            text += " {} could not be read.".format(failed)
        self.txt_links_status.Text = text

    def _on_open_link(self, sender, args):
        try:
            model = self.linked_models[int(sender.Tag)]
        except Exception:
            return
        if not model.loaded:
            return
        try:
            ModelHealthWindow(model.doc, self.uidoc, link_name=model.name).ShowDialog()
        except Exception as ex:
            MessageBox.Show("Could not open the linked model's dashboard:\n{}".format(ex),
                            "Linked Models", MessageBoxButton.OK, MessageBoxImage.Error)

    # ---- HEADER ----
    def _make_header(self):
        border = Border()
        border.Background = brush(DQT_PRIMARY)
        border.CornerRadius = WinCornerRadius(6)
        border.Padding = Thickness(16, 12, 16, 12)
        border.Margin = Thickness(0, 0, 0, 10)
        g = WPFGrid()
        c1 = ColumnDefinition()
        c1.Width = GridLength(1, GridUnitType.Star)
        c2 = ColumnDefinition()
        c2.Width = GridLength(1, GridUnitType.Auto)
        c3 = ColumnDefinition()
        c3.Width = GridLength(1, GridUnitType.Auto)
        g.ColumnDefinitions.Add(c1)
        g.ColumnDefinitions.Add(c2)
        g.ColumnDefinitions.Add(c3)

        left = StackPanel()
        title = TextBlock()
        title.Text = "MODEL HEALTH CHECK"
        title.FontSize = 22
        title.FontWeight = FontWeights.Bold
        title.Foreground = brush(DQT_TEXT_DARK)
        left.Children.Add(title)
        self.txt_project = TextBlock()
        self.txt_project.Text = "Project: Loading..."
        self.txt_project.FontSize = 12
        self.txt_project.Foreground = brush(DQT_TEXT_DARK)
        self.txt_project.Margin = Thickness(0, 3, 0, 0)
        left.Children.Add(self.txt_project)
        WPFGrid.SetColumn(left, 0)
        g.Children.Add(left)

        right = StackPanel()
        right.HorizontalAlignment = HorizontalAlignment.Right
        right.VerticalAlignment = VerticalAlignment.Center
        t1 = TextBlock()
        t1.Text = "pyDQT Suite"
        t1.FontSize = 14
        t1.FontWeight = FontWeights.SemiBold
        t1.Foreground = brush(DQT_TEXT_DARK)
        t1.HorizontalAlignment = HorizontalAlignment.Right
        right.Children.Add(t1)
        t2 = TextBlock()
        t2.Text = "Copyright by Dang Quoc Truong - DQT"
        t2.FontSize = 9
        t2.Foreground = brush(DQT_TEXT_DARK)
        t2.Opacity = 0.7
        t2.HorizontalAlignment = HorizontalAlignment.Right
        right.Children.Add(t2)
        WPFGrid.SetColumn(right, 1)
        g.Children.Add(right)

        self.btn_help = Button()
        self.btn_help.Content = "? Help"
        self.btn_help.Background = brush("#FFFFFF")
        self.btn_help.Foreground = brush(DQT_TEXT_DARK)
        self.btn_help.Padding = Thickness(10, 4, 10, 4)
        self.btn_help.Margin = Thickness(12, 0, 0, 0)
        self.btn_help.VerticalAlignment = VerticalAlignment.Center
        self.btn_help.Cursor = Cursors.Hand
        self.btn_help.Click += self._on_help
        WPFGrid.SetColumn(self.btn_help, 2)
        g.Children.Add(self.btn_help)

        border.Child = g
        return border

    # ---- SCORE CARD WITH GAUGE ----
    def _make_score_card(self):
        border = Border()
        border.Background = brush("#FFFFFF")
        border.BorderBrush = brush(DQT_BORDER)
        border.BorderThickness = Thickness(1)
        border.CornerRadius = WinCornerRadius(6)
        border.Padding = Thickness(14, 10, 14, 10)
        border.Margin = Thickness(0, 0, 0, 10)

        g = WPFGrid()
        # Columns: Gauge | Score Text | Buttons + Mini Gauges
        for w in [GridLength(1, GridUnitType.Auto),
                   GridLength(1, GridUnitType.Star),
                   GridLength(1, GridUnitType.Auto)]:
            cd = ColumnDefinition()
            cd.Width = w
            g.ColumnDefinitions.Add(cd)

        # Col 0: Main gauge
        self.gauge_container = StackPanel()
        self.gauge_container.VerticalAlignment = VerticalAlignment.Center
        self.gauge_container.Margin = Thickness(0, 0, 15, 0)
        
        # Placeholder gauge - will be updated
        self.score_circle = Border()
        self.score_circle.Width = 100
        self.score_circle.Height = 100
        self.score_circle.CornerRadius = WinCornerRadius(50)
        self.score_circle.Background = brush(HEALTH_GREEN)
        cs = StackPanel()
        cs.VerticalAlignment = VerticalAlignment.Center
        cs.HorizontalAlignment = HorizontalAlignment.Center
        self.txt_grade = TextBlock()
        self.txt_grade.Text = "?"
        self.txt_grade.FontSize = 22
        self.txt_grade.FontWeight = FontWeights.Bold
        self.txt_grade.Foreground = brush("#FFFFFF")
        self.txt_grade.HorizontalAlignment = HorizontalAlignment.Center
        cs.Children.Add(self.txt_grade)
        self.txt_score_num = TextBlock()
        self.txt_score_num.Text = "--"
        self.txt_score_num.FontSize = 12
        self.txt_score_num.Foreground = brush("#FFFFFF")
        self.txt_score_num.HorizontalAlignment = HorizontalAlignment.Center
        self.txt_score_num.Opacity = 0.9
        cs.Children.Add(self.txt_score_num)
        self.score_circle.Child = cs
        self.gauge_container.Children.Add(self.score_circle)
        
        WPFGrid.SetColumn(self.gauge_container, 0)
        g.Children.Add(self.gauge_container)

        # Col 1: Score text
        mid = StackPanel()
        mid.VerticalAlignment = VerticalAlignment.Center
        self.txt_score_label = TextBlock()
        self.txt_score_label.Text = "Analyzing..."
        self.txt_score_label.FontSize = 18
        self.txt_score_label.FontWeight = FontWeights.Bold
        self.txt_score_label.Foreground = brush(DQT_TEXT)
        mid.Children.Add(self.txt_score_label)
        self.txt_summary = TextBlock()
        self.txt_summary.FontSize = 12
        self.txt_summary.Foreground = brush("#666666")
        self.txt_summary.Margin = Thickness(0, 4, 0, 0)
        self.txt_summary.TextWrapping = TextWrapping.Wrap
        mid.Children.Add(self.txt_summary)
        self.txt_date = TextBlock()
        self.txt_date.FontSize = 10
        self.txt_date.Foreground = brush("#999999")
        self.txt_date.Margin = Thickness(0, 4, 0, 0)
        mid.Children.Add(self.txt_date)

        # Metric counts
        self.txt_metric_counts = TextBlock()
        self.txt_metric_counts.FontSize = 11
        self.txt_metric_counts.Foreground = brush("#888888")
        self.txt_metric_counts.Margin = Thickness(0, 4, 0, 0)
        mid.Children.Add(self.txt_metric_counts)

        WPFGrid.SetColumn(mid, 1)
        g.Children.Add(mid)

        # Col 2: Buttons
        right_panel = StackPanel()
        right_panel.VerticalAlignment = VerticalAlignment.Center

        btn_row = StackPanel()
        btn_row.Orientation = Orientation.Horizontal
        btn_row.Margin = Thickness(0, 0, 0, 8)

        self.btn_refresh = Button()
        self.btn_refresh.Content = u"\u27F3 Re-Analyze"
        self.btn_refresh.Background = brush(DQT_PRIMARY)
        self.btn_refresh.Foreground = brush(DQT_TEXT_DARK)
        self.btn_refresh.FontWeight = FontWeights.SemiBold
        self.btn_refresh.Padding = Thickness(16, 8, 16, 8)
        self.btn_refresh.BorderBrush = brush(DQT_PRIMARY_DARK)
        self.btn_refresh.BorderThickness = Thickness(1)
        self.btn_refresh.Margin = Thickness(0, 0, 8, 0)
        self.btn_refresh.Cursor = Cursors.Hand
        self.btn_refresh.Click += self._on_refresh
        btn_row.Children.Add(self.btn_refresh)

        self.btn_export = Button()
        self.btn_export.Content = u"Export Report"
        self.btn_export.Background = brush("#FFFFFF")
        self.btn_export.Foreground = brush(DQT_TEXT_DARK)
        self.btn_export.Padding = Thickness(12, 8, 12, 8)
        self.btn_export.BorderBrush = brush(DQT_PRIMARY_DARK)
        self.btn_export.BorderThickness = Thickness(1)
        self.btn_export.Cursor = Cursors.Hand
        self.btn_export.Click += self._on_export
        btn_row.Children.Add(self.btn_export)

        right_panel.Children.Add(btn_row)

        # Score breakdown text
        self.txt_breakdown = TextBlock()
        self.txt_breakdown.FontSize = 10
        self.txt_breakdown.Foreground = brush("#888888")
        self.txt_breakdown.TextWrapping = TextWrapping.Wrap
        self.txt_breakdown.MaxWidth = 220
        right_panel.Children.Add(self.txt_breakdown)

        WPFGrid.SetColumn(right_panel, 2)
        g.Children.Add(right_panel)

        border.Child = g
        return border

    # ---- LEGEND ----
    def _make_legend(self):
        border = Border()
        border.Background = brush("#FFFFFF")
        border.BorderBrush = brush(DQT_BORDER)
        border.BorderThickness = Thickness(1)
        border.CornerRadius = WinCornerRadius(6)
        border.Padding = Thickness(10, 6, 10, 6)
        border.Margin = Thickness(0, 0, 0, 10)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.HorizontalAlignment = HorizontalAlignment.Center
        lbl = TextBlock()
        lbl.Text = "Health Scale:  "
        lbl.FontSize = 11
        lbl.FontWeight = FontWeights.SemiBold
        lbl.Foreground = brush(DQT_TEXT_DARK)
        lbl.VerticalAlignment = VerticalAlignment.Center
        sp.Children.Add(lbl)
        for level in RAG_LEVELS:
            b = Border()
            b.Background = brush(RAG_COLORS[level])
            b.CornerRadius = WinCornerRadius(3)
            b.Padding = Thickness(10, 3, 10, 3)
            b.Margin = Thickness(3, 0, 3, 0)
            t = TextBlock()
            t.Text = u"{} - {}".format(level, RAG_MEANING[level])
            t.FontSize = 11
            t.Foreground = brush(RAG_TEXT_COLORS[level])
            t.FontWeight = FontWeights.SemiBold
            b.Child = t
            sp.Children.Add(b)
        border.Child = sp
        return border

    # ---- FOOTER ----
    def _make_footer(self):
        border = Border()
        border.Background = brush(DQT_PRIMARY)
        border.CornerRadius = WinCornerRadius(4)
        border.Padding = Thickness(10, 6, 10, 6)
        t = TextBlock()
        t.Text = u"Copyright by Dang Quoc Truong - DQT \u00A9 2025"
        t.FontSize = 10
        t.Foreground = brush(DQT_TEXT_DARK)
        t.HorizontalAlignment = HorizontalAlignment.Center
        border.Child = t
        return border

    # ----------------------------------------------------------
    # ANALYSIS
    # ----------------------------------------------------------
    def _run_analysis(self):
        try:
            proj = self.doc.ProjectInformation
            proj_name = proj.Name if proj else "Untitled"
            file_name = os.path.basename(self.doc.PathName) if self.doc.PathName else "Unsaved"
            self.txt_project.Text = "Project: {}  |  File: {}".format(proj_name, file_name)
            if self.is_link:
                self.txt_project.Text = u"Linked model: {}  |  {}".format(
                    self.link_name, self.txt_project.Text)

            self.analyzer = ModelHealthAnalyzer(self.doc)
            self.metrics = self.analyzer.analyze()

            self._update_score()
            self._build_heatmap()
            self._build_recommendations()

            self.txt_date.Text = "Last analyzed: {}".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as ex:
            self.txt_score_label.Text = "Error: " + str(ex)

    def _update_score(self):
        score = get_health_score(self.metrics)
        grade, label, color = get_overall_status(score)

        self.txt_grade.Text = grade
        self.txt_grade.Foreground = brush(RAG_TEXT_COLORS[grade])
        self.txt_score_num.Text = str(score)
        self.txt_score_num.Foreground = brush(RAG_TEXT_COLORS[grade])
        self.txt_score_label.Text = "Model Health: {} - {}".format(grade, label)
        self.score_circle.Background = brush(color)

        # Update gauge
        self.gauge_container.Children.Clear()
        try:
            gauge = create_gauge(score, 130)
            self.gauge_container.Children.Add(gauge)
        except:
            # Fallback to circle if gauge fails
            self.gauge_container.Children.Add(self.score_circle)

        # Grade label under gauge
        grade_label = TextBlock()
        grade_label.Text = "{} - {}".format(grade, label)
        grade_label.FontSize = 13
        grade_label.FontWeight = FontWeights.Bold
        grade_label.Foreground = brush(color)
        grade_label.HorizontalAlignment = HorizontalAlignment.Center
        grade_label.Margin = Thickness(0, 0, 0, 0)
        self.gauge_container.Children.Add(grade_label)

        counts = count_statuses(self.metrics)
        self.txt_summary.Text = status_summary(counts)
        self.txt_metric_counts.Text = counts_text(counts)
        self.txt_breakdown.Text = (
            "Weighted Score: {}/100\nOverall: {} ({})\n"
            "Green from {}, Amber from {}".format(
                score, grade, label, OVERALL_GREEN_MIN, OVERALL_AMBER_MIN))

    # ----------------------------------------------------------
    # HEATMAP TABLE
    # ----------------------------------------------------------
    def _build_heatmap(self):
        self.metrics_stack.Children.Clear()

        table = WPFGrid()
        # Wider columns: Metric | Value | Bar | Status | Select
        col_widths = [190, 80, 360, 380, 90]
        for w in col_widths:
            cd = ColumnDefinition()
            cd.Width = GridLength(w)
            table.ColumnDefinitions.Add(cd)

        # Header row
        rd = RowDefinition()
        rd.Height = GridLength(36)
        table.RowDefinitions.Add(rd)
        for ci, htxt in enumerate(["METRIC", "VALUE", "HEALTH INDICATOR", "STATUS", "ACTION"]):
            b = Border()
            b.Background = brush(DQT_PRIMARY)
            b.BorderBrush = brush(DQT_PRIMARY_DARK)
            b.BorderThickness = Thickness(0, 0, 1, 2)
            b.Padding = Thickness(10, 6, 10, 6)
            tb = TextBlock()
            tb.Text = htxt
            tb.FontSize = 11
            tb.FontWeight = FontWeights.Bold
            tb.Foreground = brush(DQT_TEXT_DARK)
            tb.VerticalAlignment = VerticalAlignment.Center
            if ci >= 4:
                tb.HorizontalAlignment = HorizontalAlignment.Center
            b.Child = tb
            WPFGrid.SetRow(b, 0)
            WPFGrid.SetColumn(b, ci)
            table.Children.Add(b)

        # Data rows, in priority order under one header per impact tier
        row_idx = 0
        for tier, items in metrics_by_impact(self.metrics):
            row_idx += 1
            self._add_impact_header(table, row_idx, tier)
            for number, key in items:
                row_idx += 1
                self._add_metric_row(table, row_idx, number, key)

        self.metrics_stack.Children.Add(table)

    def _add_impact_header(self, table, row_idx, tier):
        """A full-width row naming the impact tier of the metrics below it."""
        rd = RowDefinition()
        rd.Height = GridLength(30)
        table.RowDefinitions.Add(rd)
        b = Border()
        b.Background = brush("#F6EBD2")
        b.BorderBrush = brush(DQT_PRIMARY_DARK)
        b.BorderThickness = Thickness(0, 0, 0, 1)
        b.Padding = Thickness(10, 4, 10, 4)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.VerticalAlignment = VerticalAlignment.Center
        name = TextBlock()
        name.Text = u"{} IMPACT".format(tier.upper())
        name.FontSize = 11
        name.FontWeight = FontWeights.Bold
        name.Foreground = brush(DQT_TEXT_DARK)
        name.VerticalAlignment = VerticalAlignment.Center
        sp.Children.Add(name)
        desc = TextBlock()
        desc.Text = u"  -  " + IMPACT_TIERS.get(tier, {}).get("description", "")
        desc.FontSize = 11
        desc.Foreground = brush("#7A6A50")
        desc.VerticalAlignment = VerticalAlignment.Center
        sp.Children.Add(desc)
        b.Child = sp
        WPFGrid.SetRow(b, row_idx)
        WPFGrid.SetColumn(b, 0)
        WPFGrid.SetColumnSpan(b, 5)
        table.Children.Add(b)

    def _add_metric_row(self, table, row_idx, number, key):
        """One metric's row: name, value, health bar, status, Select."""
        rd = RowDefinition()
        rd.Height = GridLength(50)  # Taller rows
        table.RowDefinitions.Add(rd)

        value = self.metrics[key]
        config = METRIC_THRESHOLDS[key]
        h_color = get_health_color(key, value)
        thresholds = config["thresholds"]
        row_bg = "#FFFFFF" if row_idx % 2 == 0 else "#FAF8F0"
        measured = value is not None
        # Elements of a linked model cannot be selected in the host
        is_selectable = (config.get("selectable", False) and measured
                         and value > 0 and not self.is_link)

        # Col 0: Name
        b0 = Border()
        b0.Background = brush(row_bg)
        b0.BorderBrush = brush("#E8E0D0")
        b0.BorderThickness = Thickness(0, 0, 1, 1)
        b0.Padding = Thickness(10, 6, 10, 6)
        b0.ToolTip = config["tooltip"]
        t0 = TextBlock()
        t0.Text = "{}. {}".format(number, config["label"])
        t0.FontSize = 12
        t0.FontWeight = FontWeights.SemiBold
        t0.Foreground = brush(DQT_TEXT)
        t0.VerticalAlignment = VerticalAlignment.Center
        b0.Child = t0
        WPFGrid.SetRow(b0, row_idx)
        WPFGrid.SetColumn(b0, 0)
        table.Children.Add(b0)

        # Col 1: Value
        b1 = Border()
        b1.Background = brush(h_color)
        b1.BorderBrush = brush("#E8E0D0")
        b1.BorderThickness = Thickness(0, 0, 1, 1)
        b1.Padding = Thickness(8, 6, 8, 6)
        t1 = TextBlock()
        t1.Text = format_value(key, value)
        t1.FontSize = 13
        t1.FontWeight = FontWeights.Bold
        t1.Foreground = brush(get_text_color(key, value))
        t1.HorizontalAlignment = HorizontalAlignment.Center
        t1.VerticalAlignment = VerticalAlignment.Center
        b1.Child = t1
        WPFGrid.SetRow(b1, row_idx)
        WPFGrid.SetColumn(b1, 1)
        table.Children.Add(b1)

        # Col 2: Bar - using Canvas for pixel-perfect rendering
        b2 = Border()
        b2.Background = brush(row_bg)
        b2.BorderBrush = brush("#E8E0D0")
        b2.BorderThickness = Thickness(0, 0, 1, 1)
        b2.Padding = Thickness(10, 12, 10, 12)
        
        BAR_W = 330
        BAR_H = 16
        bar_canvas = Canvas()
        bar_canvas.Width = BAR_W
        bar_canvas.Height = BAR_H
        
        # Background bar
        bar_bg = Border()
        bar_bg.Width = BAR_W
        bar_bg.Height = BAR_H
        bar_bg.Background = brush("#E0DDD5")
        bar_bg.CornerRadius = WinCornerRadius(3)
        Canvas.SetLeft(bar_bg, 0)
        Canvas.SetTop(bar_bg, 0)
        bar_canvas.Children.Add(bar_bg)
        
        # Fill bar
        max_t = bar_scale(thresholds)
        ratio = min(value / max_t, 1.0) if measured else 0
        fill_w = max(int(ratio * BAR_W), 3) if measured and value > 0 else 0
        if fill_w > 0:
            bar_fill = Border()
            bar_fill.Width = fill_w
            bar_fill.Height = BAR_H
            bar_fill.Background = brush(h_color)
            bar_fill.CornerRadius = WinCornerRadius(3)
            Canvas.SetLeft(bar_fill, 0)
            Canvas.SetTop(bar_fill, 0)
            bar_canvas.Children.Add(bar_fill)
        
        # Threshold markers
        for tv in thresholds:
            if tv > 0 and max_t > 0:
                mr = tv / max_t
                if mr <= 1.0:
                    mk = Border()
                    mk.Width = 1
                    mk.Height = BAR_H
                    mk.Background = brush("#999999")
                    mk.Opacity = 0.4
                    Canvas.SetLeft(mk, int(mr * BAR_W))
                    Canvas.SetTop(mk, 0)
                    bar_canvas.Children.Add(mk)
        
        b2.Child = bar_canvas
        WPFGrid.SetRow(b2, row_idx)
        WPFGrid.SetColumn(b2, 2)
        table.Children.Add(b2)

        # Col 3: Status (WIDER - full info)
        b3 = Border()
        b3.Background = brush(row_bg)
        b3.BorderBrush = brush("#E8E0D0")
        b3.BorderThickness = Thickness(0, 0, 1, 1)
        b3.Padding = Thickness(10, 5, 10, 5)

        info_sp = StackPanel()
        info_sp.VerticalAlignment = VerticalAlignment.Center

        status = get_status_text(key, value)
        weight = config.get("weight", 1)
        weight_stars = u"\u2605" * weight + u"\u2606" * (5 - weight)

        st = TextBlock()
        st.Text = u"Status: {} - {}".format(status, get_status_meaning(status))
        st.FontSize = 11
        st.FontWeight = FontWeights.SemiBold
        st.Foreground = brush(status_text_color(status))
        st.TextWrapping = TextWrapping.Wrap
        info_sp.Children.Add(st)

        wt = TextBlock()
        wt.Text = u"Impact: {}  |  Weight: {} ({}/5)".format(
            config.get("impact", ""), weight_stars, weight)
        wt.FontSize = 10
        wt.Foreground = brush("#888888")
        wt.Margin = Thickness(0, 2, 0, 0)
        info_sp.Children.Add(wt)

        tt = TextBlock()
        tt.Text = thresholds_text(thresholds)
        tt.FontSize = 9
        tt.Foreground = brush("#AAAAAA")
        tt.Margin = Thickness(0, 2, 0, 0)
        info_sp.Children.Add(tt)

        b3.Child = info_sp
        WPFGrid.SetRow(b3, row_idx)
        WPFGrid.SetColumn(b3, 3)
        table.Children.Add(b3)

        # Col 4: Select Button
        b4 = Border()
        b4.Background = brush(row_bg)
        b4.BorderBrush = brush("#E8E0D0")
        b4.BorderThickness = Thickness(0, 0, 0, 1)
        b4.Padding = Thickness(4, 4, 4, 4)
        if is_selectable:
            btn = Button()
            btn.Content = u"\u25BA Select"
            btn.FontSize = 10
            btn.Padding = Thickness(8, 4, 8, 4)
            btn.Background = brush("#FFFFFF")
            btn.Foreground = brush(DQT_TEXT_DARK)
            btn.BorderBrush = brush(DQT_PRIMARY_DARK)
            btn.BorderThickness = Thickness(1)
            btn.Cursor = Cursors.Hand
            btn.VerticalAlignment = VerticalAlignment.Center
            btn.HorizontalAlignment = HorizontalAlignment.Center
            btn.Tag = key
            btn.Click += self._on_select_elements
            b4.Child = btn
        else:
            na = TextBlock()
            na.Text = "--"
            na.FontSize = 10
            na.Foreground = brush("#CCCCCC")
            na.HorizontalAlignment = HorizontalAlignment.Center
            na.VerticalAlignment = VerticalAlignment.Center
            b4.Child = na
        WPFGrid.SetRow(b4, row_idx)
        WPFGrid.SetColumn(b4, 4)
        table.Children.Add(b4)

    # ----------------------------------------------------------
    # RECOMMENDATIONS
    # ----------------------------------------------------------
    def _build_recommendations(self):
        self.rec_panel.Children.Clear()
        title = TextBlock()
        title.Text = "RECOMMENDATIONS"
        title.FontSize = 13
        title.FontWeight = FontWeights.Bold
        title.Foreground = brush(DQT_TEXT_DARK)
        title.Margin = Thickness(0, 0, 0, 8)
        self.rec_panel.Children.Add(title)

        keys = recommended_keys(self.metrics)
        for key in keys:
            value = self.metrics[key]
            status = get_status_text(key, value)
            h_color = get_health_color(key, value)
            label = METRIC_THRESHOLDS[key]["label"]
            rec = RECOMMENDATIONS.get(key, "Review and optimize.")
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(0, 2, 0, 2)
            dot = Border()
            dot.Width = 8
            dot.Height = 8
            dot.CornerRadius = WinCornerRadius(4)
            dot.Background = brush(h_color)
            dot.VerticalAlignment = VerticalAlignment.Center
            dot.Margin = Thickness(0, 0, 8, 0)
            row.Children.Add(dot)
            lbl = TextBlock()
            lbl.Text = "{} ({}) - {}: ".format(label, value, status)
            lbl.FontSize = 11
            lbl.FontWeight = FontWeights.SemiBold
            lbl.Foreground = brush(DQT_TEXT)
            lbl.VerticalAlignment = VerticalAlignment.Center
            row.Children.Add(lbl)
            rtb = TextBlock()
            rtb.Text = rec
            rtb.FontSize = 11
            rtb.Foreground = brush("#666666")
            rtb.VerticalAlignment = VerticalAlignment.Center
            rtb.TextWrapping = TextWrapping.Wrap
            rtb.MaxWidth = 800
            row.Children.Add(rtb)
            self.rec_panel.Children.Add(row)

        if not keys:
            good = TextBlock()
            good.Text = "All metrics are Green. No action required."
            good.FontSize = 12
            good.Foreground = brush(HEALTH_GREEN)
            good.FontWeight = FontWeights.SemiBold
            self.rec_panel.Children.Add(good)

    # ----------------------------------------------------------
    # SELECT ELEMENTS
    # ----------------------------------------------------------
    def _on_select_elements(self, sender, args):
        if self.is_link:
            MessageBox.Show("Elements of a linked model cannot be selected "
                            "from the host model.", "Select Elements",
                            MessageBoxButton.OK, MessageBoxImage.Information)
            return
        try:
            metric_key = sender.Tag
            if not self.analyzer or metric_key not in self.analyzer.element_ids:
                MessageBox.Show("No elements available.\nTry Re-Analyze first.",
                    "Select Elements", MessageBoxButton.OK, MessageBoxImage.Information)
                return
            ids = self.analyzer.element_ids[metric_key]
            if not ids:
                MessageBox.Show("No elements found.", "Select Elements",
                    MessageBoxButton.OK, MessageBoxImage.Information)
                return
            MAX_SELECT = 5000
            if len(ids) > MAX_SELECT:
                result = MessageBox.Show(
                    "{} elements found.\nSelect first {}?".format(len(ids), MAX_SELECT),
                    "Large Selection", MessageBoxButton.YesNo, MessageBoxImage.Warning)
                if result != MessageBoxResult.Yes:
                    return
                ids = ids[:MAX_SELECT]
            id_list = List[ElementId]()
            for eid in ids:
                id_list.Add(eid)
            self.Close()
            self.uidoc.Selection.SetElementIds(id_list)
            try:
                if id_list.Count > 0:
                    self.uidoc.ShowElements(id_list)
            except:
                pass
        except Exception as ex:
            MessageBox.Show("Error selecting elements:\n{}".format(str(ex)),
                "Error", MessageBoxButton.OK, MessageBoxImage.Error)

    # ----------------------------------------------------------
    # EVENTS
    # ----------------------------------------------------------
    def _on_help(self, sender, args):
        if _open_help_page("model_health_check.html"):
            return
        MessageBox.Show(
            "Model Health Check\n\n"
            "Analyzes the model against 12 metrics and combines them into "
            "one weighted score. The metrics are listed by their impact on "
            "model performance and stability:\n"
            "  Critical: Warnings, CAD Imports, File Size, In-Place Families\n"
            "  High: Duplicate Elements, CAD Links, RVT Links\n"
            "  Moderate: Imported Images, Model Groups, Design Options\n"
            "  Low: Unplaced Rooms, Unpinned Links\n\n"
            "HEALTH SCALE (RAG)\n"
            "  Green - healthy, meeting expectations\n"
            "  Amber - needs attention, improvement recommended\n"
            "  Red - action required, high risk or major impact\n"
            "  Every metric, and the model as a whole, is graded on this "
            "scale.\n\n"
            "WORKFLOW\n"
            "  Re-Analyze re-runs all metrics against the current model.\n"
            "  Each row in the recommendations list can Select Elements to "
            "select the offending elements straight in Revit.\n"
            "  Export Report saves the dashboard as a report file.\n\n"
            "LINKED MODELS TAB\n"
            "  One row per Revit link. Analyze Linked Models checks every "
            "loaded link with the same metrics and thresholds; Open shows "
            "a link's full dashboard (read-only). A link that is not loaded "
            "must be reloaded in Manage Links first. A cloud model's file "
            "size cannot be measured and shows N/A.\n\n"
            "SETTINGS TAB\n"
            "  Edit each metric's Green and Amber values and weight (1-5) "
            "before running an analysis. Save & Apply writes them to "
            "threshold_config.json next to this tool and re-scores the "
            "dashboard immediately; Reset to Defaults restores the "
            "built-in values and deletes that file.",
            "Model Health Check - Help",
            MessageBoxButton.OK, MessageBoxImage.Information)

    def _on_refresh(self, sender, args):
        self._run_analysis()

    def _links_report_html(self):
        """The report's Linked Models section - empty for a linked model's
        own report, or when the model has no links."""
        if self.is_link or not self.linked_models:
            return ""
        if not any(m.metrics is not None or m.error for m in self.linked_models):
            return ('<div class="rec-box"><h3>LINKED MODELS</h3>'
                    '<div style="color:#888;">{} linked file(s) - not analyzed. Use '
                    'Linked Models &gt; Analyze Linked Models before exporting to '
                    'include them.</div></div>').format(len(self.linked_models))
        rows = ""
        for i, model in enumerate(self.linked_models):
            row = link_row(model)
            bg = "#FFFFFF" if i % 2 == 0 else "#FAF8F0"
            overall_style = ("background:{};color:{};font-weight:700;".format(row["color"], row["text_color"])
                             if row["color"] else "")
            rows += (u'<tr style="background:{bg};"><td style="padding:6px 10px;font-weight:600;">{name}</td>'
                     u'<td style="text-align:center;">{inst}</td><td>{status}</td>'
                     u'<td style="text-align:center;{ostyle}">{overall}</td>'
                     u'<td style="text-align:center;">{score}</td><td style="text-align:center;">{red}</td>'
                     u'<td style="text-align:center;">{amber}</td><td style="color:#666;">{note}</td></tr>').format(
                bg=bg, name=_html(row["name"]), inst=row["instances"], status=row["status"],
                ostyle=overall_style, overall=row["overall"], score=row["score"],
                red=row["red"], amber=row["amber"], note=_html(row["note"]))
        return (u'<div class="rec-box"><h3>LINKED MODELS</h3><table>'
                u'<tr><th>LINKED MODEL</th><th style="text-align:center;">INSTANCES</th><th>STATUS</th>'
                u'<th style="text-align:center;">OVERALL</th><th style="text-align:center;">SCORE</th>'
                u'<th style="text-align:center;">RED</th><th style="text-align:center;">AMBER</th>'
                u'<th>NEEDS ATTENTION</th></tr>{}</table></div>').format(rows)

    def _on_export(self, sender, args):
        """Export report as PDF using HTML rendering"""
        try:
            desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
            fname = os.path.basename(self.doc.PathName).replace(".rvt", "") if self.doc.PathName else "Model"
            fname = fname.replace(" ", "_")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            proj = self.doc.ProjectInformation
            proj_name = proj.Name if proj else "Untitled"
            file_name = os.path.basename(self.doc.PathName) if self.doc.PathName else "Unsaved"
            
            score = get_health_score(self.metrics)
            grade, label, grade_color = get_overall_status(score)
            counts = count_statuses(self.metrics)
            
            # Build metric rows HTML - priority order, one header per impact tier
            rows_html = ""
            i = 0
            for tier, items in metrics_by_impact(self.metrics):
                rows_html += """
                  <tr class="tier"><td colspan="4"><strong>{name} IMPACT</strong> &nbsp;-&nbsp; {desc}</td></tr>""".format(
                    name=tier.upper(), desc=IMPACT_TIERS[tier]["description"])
                for number, key in items:
                    value = self.metrics[key]
                    config = METRIC_THRESHOLDS[key]
                    h_color = get_health_color(key, value)
                    text_color = get_text_color(key, value)
                    thresholds = config["thresholds"]
                    status = get_status_text(key, value)
                    weight = config.get("weight", 1)
                    weight_stars = "&#9733;" * weight + "&#9734;" * (5 - weight)
                    val_str = format_value(key, value)
                    row_bg = "#FFFFFF" if i % 2 == 0 else "#FAF8F0"
                    i += 1
                
                    # Bar width as a percentage of the bar's scale
                    max_t = bar_scale(thresholds)
                    bar_pct = min(value / max_t * 100, 100) if value is not None and value > 0 else 0
                    empty_pct = 100 - bar_pct
                
                    rows_html += """
                    <tr style="background:{bg};">
                        <td style="padding:8px 10px;font-weight:600;border-bottom:1px solid #E8E0D0;">{label}</td>
                        <td style="padding:8px;text-align:center;background:{color};color:{tcolor};font-weight:700;border-bottom:1px solid #E8E0D0;">{val}</td>
                        <td style="padding:8px 10px;border-bottom:1px solid #E8E0D0;">
                            <table style="width:100%;border-collapse:collapse;height:14px;table-layout:fixed;"><tr>
                                <td style="width:{pct}%;background:{color};border-radius:3px 0 0 3px;height:14px;padding:0;"></td>
                                <td style="width:{epct}%;background:#E0DDD5;border-radius:0 3px 3px 0;height:14px;padding:0;"></td>
                            </tr></table>
                        </td>
                        <td style="padding:6px 10px;border-bottom:1px solid #E8E0D0;">
                            <div style="color:{scolor};font-weight:600;font-size:11px;">Status: {status} - {meaning}</div>
                            <div style="color:#888;font-size:9px;">Impact: {impact} &nbsp;|&nbsp; Weight: {stars} ({w}/5)</div>
                            <div style="color:#AAA;font-size:8px;">{thresholds}</div>
                        </td>
                    </tr>""".format(
                        bg=row_bg, label="{}. {}".format(number, config["label"]), color=h_color,
                        tcolor=text_color, val=val_str,
                        pct=round(bar_pct, 1), epct=round(empty_pct, 1),
                        scolor=status_text_color(status),
                        status=status, meaning=get_status_meaning(status),
                        impact=config.get("impact", ""), stars=weight_stars, w=weight,
                        thresholds=thresholds_text(thresholds).replace(u"\u2264", "&le;").replace(">", "&gt;"))
            
            # Build recommendations HTML - Amber and Red, in priority order
            rec_html = ""
            rec_keys = recommended_keys(self.metrics)
            for key in rec_keys:
                value = self.metrics[key]
                h_color = get_health_color(key, value)
                metric_label = METRIC_THRESHOLDS[key]["label"]
                rec = RECOMMENDATIONS.get(key, "Review and optimize.")
                rec_html += '<div style="margin:4px 0;"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{};margin-right:8px;vertical-align:middle;"></span><strong>{} ({}) - {}:</strong> <span style="color:#666;">{}</span></div>'.format(
                    h_color, metric_label, value, get_status_text(key, value), rec)
            if not rec_keys:
                rec_html = '<div style="color:#4CAF50;font-weight:600;">All metrics are Green. No action required.</div>'

            links_html = self._links_report_html()
            
            # Full HTML
            html = u"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Model Health Check Report - DQT</title>
<style>
    @page {{ size: A4 landscape; margin: 12mm; }}
    * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color-adjust: exact !important; }}
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 0; padding: 15px; background: #FEF8E7; color: #333; font-size: 11px; }}
    .header {{ background: #F0CC88; padding: 16px 20px; border-radius: 6px; margin-bottom: 15px; overflow: hidden; }}
    .header h1 {{ margin: 0; font-size: 22px; color: #5D4E37; float: left; }}
    .header .right {{ float: right; text-align: right; color: #5D4E37; }}
    .header .sub {{ font-size: 11px; color: #5D4E37; margin-top: 4px; }}
    .score-card {{ background: #FFF; border: 1px solid #D4B87A; border-radius: 6px; padding: 15px 20px; margin-bottom: 15px; overflow: hidden; }}
    .gauge {{ float: left; width: 90px; height: 90px; border-radius: 50%; background: {grade_color}; text-align: center; margin-right: 20px; }}
    .gauge .grade {{ font-size: 22px; font-weight: bold; color: {grade_text}; margin-top: 24px; }}
    .gauge .num {{ font-size: 12px; color: {grade_text}; opacity: 0.9; }}
    .score-text h2 {{ margin: 0 0 5px 0; font-size: 18px; color: #333; }}
    .score-text .summary {{ color: #666; font-size: 12px; }}
    .score-text .counts {{ color: #888; font-size: 10px; margin-top: 4px; }}
    .legend {{ background: #FFF; border: 1px solid #D4B87A; border-radius: 6px; padding: 8px 15px; margin-bottom: 15px; text-align: center; }}
    .legend span {{ display: inline-block; padding: 3px 10px; border-radius: 3px; color: #FFF; font-size: 10px; font-weight: 600; margin: 0 2px; -webkit-print-color-adjust: exact; }}
    table {{ width: 100%; border-collapse: collapse; background: #FFF; border: 1px solid #D4B87A; }}
    th {{ background: #F0CC88 !important; color: #5D4E37; padding: 8px 10px; text-align: left; font-size: 11px; border-bottom: 2px solid #D4B87A; }}
    tr.tier td {{ background: #F6EBD2; color: #5D4E37; padding: 6px 10px; font-size: 11px; border-bottom: 1px solid #D4B87A; }}
    .rec-box {{ background: #FFF; border: 1px solid #D4B87A; border-radius: 6px; padding: 12px 15px; margin-top: 15px; }}
    .rec-box h3 {{ margin: 0 0 8px 0; color: #5D4E37; font-size: 13px; }}
    .footer {{ background: #F0CC88; border-radius: 4px; padding: 8px; text-align: center; margin-top: 15px; font-size: 10px; color: #5D4E37; }}
</style>
</head>
<body>
    <div class="header">
        <h1>MODEL HEALTH CHECK</h1>
        <div class="right">
            <div style="font-size:14px;font-weight:600;">pyDQT Suite</div>
            <div style="font-size:9px;opacity:0.7;">Copyright by Dang Quoc Truong - DQT</div>
        </div>
        <div style="clear:both;"></div>
        <div class="sub">{link_note}Project: {proj} &nbsp;|&nbsp; File: {file}</div>
    </div>

    <div class="score-card">
        <div class="gauge">
            <div class="grade">{grade}</div>
            <div class="num">{score}</div>
        </div>
        <div class="score-text">
            <h2>Model Health: {grade} - {label}</h2>
            <div class="summary">{summary}</div>
            <div class="counts">{counts}</div>
            <div class="counts">Date: {date}</div>
        </div>
        <div style="clear:both;"></div>
    </div>

    <div class="legend">
        <strong>Health Scale:</strong>
        {legend}
    </div>

    <table>
        <tr>
            <th style="width:160px;">METRIC</th>
            <th style="width:70px;text-align:center;">VALUE</th>
            <th style="width:250px;">HEALTH INDICATOR</th>
            <th>STATUS</th>
        </tr>
        {rows}
    </table>

    <div class="rec-box">
        <h3>RECOMMENDATIONS</h3>
        {recs}
    </div>

    {links}

    <div class="footer">Copyright by Dang Quoc Truong - DQT &copy; 2025</div>
</body>
</html>""".format(
                grade_color=grade_color, grade_text=RAG_TEXT_COLORS[grade],
                proj=proj_name, file=file_name,
                grade=grade, score=score, label=label,
                summary=status_summary(counts),
                counts=counts_text(counts),
                legend="\n        ".join(
                    '<span style="background:{};color:{};">{} - {}</span>'.format(
                        RAG_COLORS[lv], RAG_TEXT_COLORS[lv], lv, RAG_MEANING[lv])
                    for lv in RAG_LEVELS),
                date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                rows=rows_html, recs=rec_html, links=links_html,
                link_note=(u"Linked model: {} &nbsp;|&nbsp; ".format(_html(self.link_name))
                           if self.is_link else ""))
            
            # Save HTML with UTF-8 encoding
            html_path = os.path.join(desktop, "ModelHealth_{}_{}.html".format(fname, ts))
            with codecs.open(html_path, 'w', 'utf-8') as f:
                f.write(html)
            
            # Auto-open in default browser
            try:
                System.Diagnostics.Process.Start(html_path)
            except:
                pass
            
            MessageBox.Show(
                "Report exported!\n\n{}\n\nFile opened in browser.\nUse Ctrl+P > Save as PDF to create PDF.".format(html_path),
                "Export Complete",
                MessageBoxButton.OK,
                MessageBoxImage.Information)

        except Exception as ex:
            MessageBox.Show("Export error:\n{}".format(str(ex)),
                "Error", MessageBoxButton.OK, MessageBoxImage.Error)


# ============================================================
# MAIN
# ============================================================
try:
    doc = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument
    window = ModelHealthWindow(doc, uidoc)
    window.ShowDialog()
except Exception as e:
    from pyrevit import forms
    forms.alert("Error launching Model Health Check:\n{}".format(str(e)),
                title="Model Health Check - DQT",
                exitscript=True)