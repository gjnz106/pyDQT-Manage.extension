# -*- coding: utf-8 -*-
"""
IFC-SG Parameter Checker v1.2 - DQT
Checks that required IFC+SG parameters exist and have values in Revit model elements.
Supports import from:
  - Autodesk Model Checker XML configuration files
  - Excel parameter mapping files (LTA/BCA format)

Based on CORENET X Code of Practice 3rd Edition September 2025.

Copyright (c) 2025 Dang Quoc Truong (DQT)
All rights reserved.
"""

__title__ = "IFC-SG\nChecker"
__author__ = "Dang Quoc Truong (DQT)"
__doc__ = "Check IFC+SG required parameters. Import rules from Autodesk XML or Excel."

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
import System
from System.Windows import *
from System.Windows.Controls import *
from System.Windows.Media import *
from System.Windows.Markup import XamlReader
from System.IO import StringReader
import os
import sys
import json
import codecs
import traceback
import datetime

# =====================================================================
# REVIT API COMPATIBILITY (2024/2025/2026+)
# =====================================================================
def _eid_int(eid):
    """Get integer value from ElementId - compatible with Revit 2024-2026+"""
    try:
        return eid.Value  # Revit 2026+
    except:
        return eid.IntegerValue  # Revit 2024/2025

def _get_group_type_id(pg_key):
    """Get ForgeTypeId for parameter group - compatible with Revit 2024-2026+
    pg_key: e.g. 'PG_IFC', 'PG_GEOMETRY', 'PG_FIRE_PROTECTION'
    """
    # Revit 2026+ uses GroupTypeId
    group_map = {
        "PG_IFC": "Ifc",
        "PG_GEOMETRY": "Geometry",
        "PG_FIRE_PROTECTION": "FireProtection",
        "PG_MATERIALS": "Materials",
        "PG_IDENTITY_DATA": "IdentityData",
        "PG_STRUCTURAL": "Structural",
        "PG_MECHANICAL": "Mechanical",
        "PG_CONSTRUCTION": "Construction",
        "PG_PLUMBING": "Plumbing",
        "PG_ELECTRICAL": "Electrical",
        "PG_PHASING": "Phasing",
        "PG_GENERAL": "General",
        "PG_DATA": "Data",
    }
    
    # Try GroupTypeId first (Revit 2022+, required in 2026)
    try:
        from Autodesk.Revit.DB import GroupTypeId
        attr_name = group_map.get(pg_key, "Ifc")
        return getattr(GroupTypeId, attr_name)
    except:
        pass
    
    # Fallback to BuiltInParameterGroup (Revit 2024/2025)
    try:
        return getattr(BuiltInParameterGroup, pg_key, BuiltInParameterGroup.PG_IFC)
    except:
        pass
    
    return None

def _create_ext_def_options(param_name):
    """Create ExternalDefinitionCreationOptions - compatible with Revit 2024-2026+"""
    # Try SpecTypeId first (Revit 2022+)
    try:
        opt = ExternalDefinitionCreationOptions(param_name, SpecTypeId.String.Text)
        opt.Visible = True
        return opt
    except:
        pass
    
    # Fallback to ParameterType (Revit 2021 and below - removed in 2026)
    try:
        opt = ExternalDefinitionCreationOptions(param_name, ParameterType.Text)
        opt.Visible = True
        return opt
    except:
        pass
    
    return None

def _bind_param_insert(document, defn, binding, pg_key="PG_IFC"):
    """Insert parameter binding - compatible with Revit 2024-2026+"""
    group_id = _get_group_type_id(pg_key)
    
    if group_id is not None:
        try:
            return document.ParameterBindings.Insert(defn, binding, group_id)
        except:
            pass
    
    # Fallback: try without group
    try:
        return document.ParameterBindings.Insert(defn, binding)
    except:
        pass
    
    return False


# =====================================================================
# REVIT CONTEXT
# =====================================================================
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
app = doc.Application

# =====================================================================
# PATHS
# =====================================================================
SCRIPT_DIR = os.path.dirname(__file__)
CONFIG_DIR = os.path.join(SCRIPT_DIR, "configs")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")

for d in [CONFIG_DIR, REPORTS_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)


def _open_help_page(html_filename):
    """Open this tool's page from the shared _IFCSG_Help folder in the
    default browser. Returns True on success, False if the caller should
    fall back to the in-app help text (e.g. the folder went missing)."""
    try:
        panel_dir = os.path.dirname(os.path.abspath(SCRIPT_DIR))
        path = os.path.join(panel_dir, "_IFCSG_Help", html_filename)
        if not os.path.isfile(path):
            return False
        os.startfile(path)
        return True
    except Exception:
        return False

# =====================================================================
# UI SCALE
# One layout transform on the root grid scales text, icons, buttons and
# spacing together, so nothing can be missed and the ratio stays tunable.
# =====================================================================
UI_SCALE = 1.04     # 1.3 x 0.8 - the 1.3 pass read too large in use
BASE_WIDTH = 1150
BASE_HEIGHT = 820

# How many missing element ids are kept per check. The results list, the
# per-category button and "Select All Failed" all read from this, so it has
# to be at least as large as the biggest of those slices.
MAX_STORED_IDS = 1000

# =====================================================================
# CATEGORY NAME MAPPING: Revit Category Name <-> BuiltInCategory
# =====================================================================
def _bic(*names):
    """First BuiltInCategory that exists in this Revit version.

    Category enum members come and go between releases - OST_Toposolid only
    exists from Revit 2024 - so resolve by name and fall back rather than
    referencing a member that may not be there."""
    for name in names:
        try:
            value = getattr(BuiltInCategory, name, None)
            if value is not None:
                return value
        except:
            pass
    return None


CATEGORY_MAP = {
    "Areas": _bic("OST_Areas"),
    "Generic Models": _bic("OST_GenericModel"),
    "Plumbing Fixtures": _bic("OST_PlumbingFixtures"),
    "Project Information": None,  # Special handling
    "Ceilings": _bic("OST_Ceilings"),
    "Doors": _bic("OST_Doors"),
    # Toposolid (Revit 2024+) is its own category - OST_Topography is the old
    # toposurface and finds nothing in a toposolid model.
    "Toposolid": _bic("OST_Toposolid", "OST_Topography"),
    "Toposolids": _bic("OST_Toposolid", "OST_Topography"),
    "Topography": _bic("OST_Topography"),
    "Floors": _bic("OST_Floors"),
    "Shaft Openings": _bic("OST_ShaftOpening"),
    "Windows": _bic("OST_Windows"),
    "Planting": _bic("OST_Planting"),
    "Specialty Equipment": _bic("OST_SpecialityEquipment"),
    "Parking": _bic("OST_Parking"),
    "Rooms": _bic("OST_Rooms"),
    "Walls": _bic("OST_Walls"),
    "Railings": _bic("OST_StairsRailing"),
    "Ramps": _bic("OST_Ramps"),
    "Model Groups": _bic("OST_IOSModelGroups"),
    "Roofs": _bic("OST_Roofs"),
    "Furniture": _bic("OST_Furniture"),
    "Stairs": _bic("OST_Stairs"),
    "Structural Framing": _bic("OST_StructuralFraming"),
    "Structural Columns": _bic("OST_StructuralColumns"),
    "Columns": _bic("OST_Columns"),
    "Structural Foundations": _bic("OST_StructuralFoundation"),
    "Structural Foundation": _bic("OST_StructuralFoundation"),
    "Electrical Equipment": _bic("OST_ElectricalEquipment"),
    "Electrical Fixtures": _bic("OST_ElectricalFixtures"),
    "Lighting Fixtures": _bic("OST_LightingFixtures"),
    "Duct Accessories": _bic("OST_DuctAccessory"),
    "Mechanical Equipment": _bic("OST_MechanicalEquipment"),
    "Pipes": _bic("OST_PipeCurves"),
    "Pipe Fittings": _bic("OST_PipeFitting"),
    "Ducts": _bic("OST_DuctCurves"),
    "Duct Fittings": _bic("OST_DuctFitting"),
    "Pipe Accessories": _bic("OST_PipeAccessory"),
    "Sprinklers": _bic("OST_Sprinklers"),
    "Casework": _bic("OST_Casework"),
    "Curtain Panels": _bic("OST_CurtainWallPanels"),
    "Curtain Wall Panels": _bic("OST_CurtainWallPanels"),
    "Curtain Wall Mullions": _bic("OST_CurtainWallMullions"),
    "Spaces": _bic("OST_MEPSpaces"),
}

# Case/whitespace-insensitive lookup so category names coming from an Excel
# sheet or a hand-edited config still resolve.
CATEGORY_LOOKUP = dict((k.strip().lower(), k) for k in CATEGORY_MAP)


def resolve_category_key(category_name):
    """Canonical CATEGORY_MAP key for a config's category name, or None when
    the category is not one this tool knows how to collect."""
    if category_name is None:
        return None
    return CATEGORY_LOOKUP.get(str(category_name).strip().lower())


# =====================================================================
# CONFIG PARSER - Parse XML / Excel / JSON into internal format
# =====================================================================
class ParamCheckConfig:
    """
    Internal config format:
    {
        "name": "IFC+SG COP3",
        "source": "XML",
        "disciplines": {
            "ARC": {
                "enabled": True,
                "categories": {
                    "Doors": {
                        "enabled": True,
                        "params": ["ClearHeight", "ClearWidth", "FireRating", ...]
                    }
                }
            }
        }
    }
    """
    
    def __init__(self):
        self.name = ""
        self.source = ""
        self.description = ""
        self.disciplines = {}
    
    @staticmethod
    def from_xml(filepath):
        """Parse Autodesk Model Checker XML configuration"""
        import xml.etree.ElementTree as ET
        
        config = ParamCheckConfig()
        config.source = "XML"
        
        tree = ET.parse(filepath)
        root = tree.getroot()
        config.name = root.get("Name", "Imported XML Config")
        config.description = root.get("Description", "")

        # Autodesk writes these files with the Heading/Section/Check elements
        # at varying depths, so search the whole subtree instead of only the
        # direct children - two of the shipped CORENET configs nest them one
        # level deeper and used to import as completely empty.
        for heading in root.iter("Heading"):
            disc_name = heading.get("HeadingText", "") or heading.get("Name", "")
            disc_enabled = heading.get("IsChecked", "True") == "True"

            categories = {}
            for section in heading.iter("Section"):
                cat_name = section.get("SectionName", "") or section.get("Name", "")
                cat_enabled = section.get("IsChecked", "True") == "True"

                params = []
                for check in section.iter("Check"):
                    param_name = (check.get("CheckName", "") or
                                  check.get("Name", "") or
                                  check.get("ParameterName", ""))
                    if param_name:
                        params.append(param_name)

                if cat_name and params:
                    if cat_name in categories:
                        params.extend(categories[cat_name]["params"])
                    categories[cat_name] = {
                        "enabled": cat_enabled,
                        "params": sorted(set(params))
                    }

            if categories:
                if disc_name in config.disciplines:
                    config.disciplines[disc_name]["categories"].update(categories)
                else:
                    config.disciplines[disc_name or "Imported"] = {
                        "enabled": disc_enabled,
                        "categories": categories
                    }

        return config
    
    @staticmethod
    def from_excel(filepath):
        """
        Parse Excel parameter mapping file.
        Expected format:
        Column A: Discipline (ARC/STR/MEP)
        Column B: Revit Category
        Column C: Parameter Name
        Column D: Required (Yes/No) [optional]
        """
        config = ParamCheckConfig()
        config.source = "Excel"
        config.name = os.path.splitext(os.path.basename(filepath))[0]
        
        excel_app = None
        wb = None
        try:
            clr.AddReference('Microsoft.Office.Interop.Excel')
            from Microsoft.Office.Interop import Excel as ExcelInterop

            excel_app = ExcelInterop.ApplicationClass()
            excel_app.Visible = False
            excel_app.DisplayAlerts = False

            wb = excel_app.Workbooks.Open(filepath)
            ws = wb.Sheets[1]
            
            # Find data range
            used = ws.UsedRange
            rows = used.Rows.Count
            
            for r in range(2, rows + 1):  # Skip header
                disc = str(ws.Cells[r, 1].Value2 or "").strip()
                cat = str(ws.Cells[r, 2].Value2 or "").strip()
                param = str(ws.Cells[r, 3].Value2 or "").strip()
                required = str(ws.Cells[r, 4].Value2 or "Yes").strip().lower()
                
                if not disc or not cat or not param:
                    continue
                if required in ("no", "false", "0"):
                    continue
                
                if disc not in config.disciplines:
                    config.disciplines[disc] = {"enabled": True, "categories": {}}
                if cat not in config.disciplines[disc]["categories"]:
                    config.disciplines[disc]["categories"][cat] = {"enabled": True, "params": []}
                
                if param not in config.disciplines[disc]["categories"][cat]["params"]:
                    config.disciplines[disc]["categories"][cat]["params"].append(param)
            
            wb.Close(False)
            wb = None
            excel_app.Quit()
            System.Runtime.InteropServices.Marshal.ReleaseComObject(excel_app)
            excel_app = None

        except Exception as e:
            raise Exception("Excel parse error: {}".format(str(e)))
        finally:
            # Without this an EXCEL.EXE stays running invisibly whenever the
            # read throws part-way through.
            try:
                if wb is not None:
                    wb.Close(False)
            except:
                pass
            try:
                if excel_app is not None:
                    excel_app.Quit()
                    System.Runtime.InteropServices.Marshal.ReleaseComObject(excel_app)
            except:
                pass

        return config
    
    @staticmethod
    def from_json(filepath):
        """Load from saved JSON config"""
        config = ParamCheckConfig()
        with codecs.open(filepath, 'r', 'utf-8') as f:
            data = json.load(f)
        config.name = data.get("name", "")
        config.source = data.get("source", "JSON")
        config.description = data.get("description", "")
        config.disciplines = data.get("disciplines", {})
        return config
    
    def to_json(self, filepath):
        """Save config as JSON"""
        data = {
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "disciplines": self.disciplines
        }
        with codecs.open(filepath, 'w', 'utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_total_stats(self):
        """Return total disciplines, categories, parameters"""
        total_disc = len(self.disciplines)
        total_cat = 0
        total_param = 0
        for d in self.disciplines.values():
            cats = d.get("categories", {})
            total_cat += len(cats)
            for c in cats.values():
                total_param += len(c.get("params", []))
        return total_disc, total_cat, total_param


# =====================================================================
# CHECKER ENGINE - Run parameter checks against model
# =====================================================================
class CheckResult:
    """Result for one category check"""
    def __init__(self, discipline, category, param_name, status,
                 total_elements=0, missing_count=0, element_ids=None,
                 unmapped=False):
        self.discipline = discipline
        self.category = category
        self.param_name = param_name
        self.status = status  # "pass", "fail", "warning", "skip", "no_elements"
        self.total_elements = total_elements
        self.missing_count = missing_count
        self.element_ids = element_ids or []
        # True when the config names a category this tool cannot collect, as
        # opposed to a category that is simply empty in this model. Both come
        # back as "no_elements" but they mean very different things.
        self.unmapped = unmapped


class ParamChecker:
    """Check IFC+SG parameters in Revit model"""
    
    def __init__(self, document):
        self.doc = document
        self._element_cache = {}   # category -> list of elements
        self._type_cache = {}      # type element id -> {param name: has value}

    def is_mapped(self, category_name):
        """True when this tool knows how to collect the config's category."""
        if str(category_name).strip().lower() == "project information":
            return True
        return resolve_category_key(category_name) is not None

    def _get_elements(self, category_name):
        """Get all instance elements for a Revit category"""
        if category_name in self._element_cache:
            return self._element_cache[category_name]

        key = resolve_category_key(category_name)
        bic = CATEGORY_MAP.get(key) if key else None
        elements = []

        if key == "Project Information" or \
                str(category_name).strip().lower() == "project information":
            # Special: only 1 element
            elements = [self.doc.ProjectInformation]
        elif bic is not None:
            try:
                collector = FilteredElementCollector(self.doc)\
                    .OfCategory(bic)\
                    .WhereElementIsNotElementType()
                elements = list(collector)
            except:
                elements = []

        self._element_cache[category_name] = elements
        return elements

    def _param_has_value(self, p):
        """True when a parameter holds something a checker would accept."""
        try:
            if not p.HasValue:
                return False
            if p.StorageType == StorageType.String:
                val = p.AsString()
                return val is not None and val.strip() != ""
            elif p.StorageType == StorageType.ElementId:
                return p.AsElementId() != ElementId.InvalidElementId
            return True
        except:
            return False

    def _collect_param_map(self, element):
        """{parameter name: has a value} for one element, built in one pass.

        Reading every parameter once and looking the wanted names up in the
        result is what keeps a 40-parameter category from re-walking each
        element's whole parameter list 40 times."""
        found = {}
        try:
            for p in element.Parameters:
                try:
                    name = p.Definition.Name
                except:
                    continue
                # An element can carry the same name twice (instance + shared);
                # any one of them holding a value is enough to pass.
                if found.get(name):
                    continue
                found[name] = self._param_has_value(p)
        except:
            pass
        return found

    def _get_type_param_map(self, element):
        """Parameter map of the element's type, cached per type.

        Plenty of IFC+SG parameters (FireRating, IfcExportAs, material data)
        are type parameters. Checking instances only reported every one of
        them as missing on every element."""
        try:
            type_id = element.GetTypeId()
        except:
            return {}
        if type_id is None or type_id == ElementId.InvalidElementId:
            return {}

        key = _eid_int(type_id)
        if key in self._type_cache:
            return self._type_cache[key]

        type_map = {}
        try:
            el_type = self.doc.GetElement(type_id)
            if el_type is not None:
                type_map = self._collect_param_map(el_type)
        except:
            type_map = {}

        self._type_cache[key] = type_map
        return type_map

    def _lookup(self, param_map, lower_map, param_name):
        """Has-value lookup: exact name first, then case-insensitive.

        Config files and Revit shared parameters disagree on casing often
        enough ("FireRating" vs "Firerating") that an exact-only match
        produced failures for parameters that are actually filled in."""
        if param_name in param_map:
            return param_map[param_name]
        return lower_map.get(param_name.strip().lower())
    
    def run_check(self, config, progress_callback=None):
        """
        Run all parameter checks.
        Returns list of CheckResult per discipline/category/param.
        """
        results = []
        self._element_cache = {}
        self._type_cache = {}

        total_checks = 0
        for d_data in config.disciplines.values():
            if not d_data.get("enabled", True):
                continue
            for c_data in d_data.get("categories", {}).values():
                if not c_data.get("enabled", True):
                    continue
                total_checks += len(c_data.get("params", []))
        
        current = 0

        for disc_name, disc_data in config.disciplines.items():
            if not disc_data.get("enabled", True):
                continue

            for cat_name, cat_data in disc_data.get("categories", {}).items():
                if not cat_data.get("enabled", True):
                    continue

                params = cat_data.get("params", [])
                mapped = self.is_mapped(cat_name)
                if progress_callback:
                    progress_callback(current, total_checks,
                                      "{} > {}".format(disc_name, cat_name))
                elements = self._get_elements(cat_name) if mapped else []

                if not elements:
                    for param_name in params:
                        results.append(CheckResult(
                            disc_name, cat_name, param_name,
                            "no_elements", 0, 0, None, not mapped))
                        current += 1
                    if progress_callback:
                        progress_callback(current, total_checks,
                                          "{} > {}".format(disc_name, cat_name))
                    continue

                # One pass over the elements collecting every wanted parameter
                # at once, rather than one full pass per parameter.
                missing_ids = dict((p, []) for p in params)
                total = len(elements)

                for el in elements:
                    try:
                        inst_map = self._collect_param_map(el)
                        type_map = self._get_type_param_map(el)
                        inst_lower = dict((k.strip().lower(), v)
                                          for k, v in inst_map.items())
                        type_lower = dict((k.strip().lower(), v)
                                          for k, v in type_map.items())
                        el_id = _eid_int(el.Id)
                    except:
                        continue

                    for param_name in params:
                        has = self._lookup(inst_map, inst_lower, param_name)
                        if not has:
                            # Fall back to the type - a value there is what
                            # gets exported to IFC for this element.
                            has = self._lookup(type_map, type_lower, param_name)
                        if not has:
                            missing_ids[param_name].append(el_id)

                for param_name in params:
                    missing = len(missing_ids[param_name])

                    if missing == 0:
                        status = "pass"
                    elif missing == total:
                        # All missing - likely parameter doesn't exist
                        status = "fail"
                    else:
                        status = "warning"  # Partial

                    results.append(CheckResult(
                        disc_name, cat_name, param_name,
                        status, total, missing,
                        missing_ids[param_name][:MAX_STORED_IDS]))

                    current += 1

                if progress_callback:
                    progress_callback(current, total_checks,
                                      "{} > {}".format(disc_name, cat_name))

        return results


# =====================================================================
# EXCEL REPORT
# =====================================================================
XLSX_FORMAT = 51  # xlOpenXMLWorkbook - SaveAs must be told, or Excel picks
                  # its own default format and the .xlsx name lies about it.

INVALID_FILENAME_CHARS = '\\/:*?"<>|\r\n\t'
MAX_PATH = 250    # Excel refuses to save beyond the Windows path limit


def safe_filename(text, max_length=40):
    """Filename-safe, length-capped version of a piece of text.

    Revit project names on CORENET jobs run to 250+ characters with commas
    and brackets in them. Dropped into a filename they blow past the Windows
    path limit and Excel's SaveAs fails - which is exactly what stopped the
    export from working."""
    if not text:
        return ""
    cleaned = "".join(" " if c in INVALID_FILENAME_CHARS else c for c in text)
    cleaned = " ".join(cleaned.split())        # collapse runs of whitespace
    cleaned = cleaned.strip(" .")              # Windows dislikes both at the end
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].strip(" .")
    return cleaned


class ExcelReporter:
    """Generate Excel report for IFC-SG parameter check"""

    def __init__(self, doc):
        self.doc = doc

    def _rgb(self, r, g, b):
        return r + (g * 256) + (b * 256 * 256)

    def generate(self, config, results, filepath):
        clr.AddReference('Microsoft.Office.Interop.Excel')
        from Microsoft.Office.Interop import Excel as ExcelInterop

        excel_app = ExcelInterop.ApplicationClass()
        excel_app.Visible = False
        excel_app.DisplayAlerts = False

        wb = None
        try:
            wb = excel_app.Workbooks.Add()
            
            # --- Sheet 1: Summary ---
            ws = wb.Sheets[1]
            ws.Name = "Summary"
            
            ws.Cells[1, 1].Value2 = "IFC-SG PARAMETER CHECK REPORT"
            ws.Cells[1, 1].Font.Size = 16
            ws.Cells[1, 1].Font.Bold = True
            ws.Range["A1:E1"].Merge()
            ws.Range["A1:E1"].Interior.Color = self._rgb(240, 204, 136)
            
            row = 3
            info = [
                ("Project", self.doc.ProjectInformation.Name or "N/A"),
                ("Config", config.name),
                ("Source", config.source),
                ("Date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ]
            for label, val in info:
                ws.Cells[row, 1].Value2 = label
                ws.Cells[row, 1].Font.Bold = True
                ws.Cells[row, 2].Value2 = val
                row += 1
            
            row += 1
            # Stats
            total = len(results)
            passed = len([r for r in results if r.status == "pass"])
            failed = len([r for r in results if r.status == "fail"])
            warning = len([r for r in results if r.status == "warning"])
            no_elem = len([r for r in results if r.status == "no_elements"])
            
            stats = [("Total Checks", total), ("Passed", passed),
                     ("Failed (all missing)", failed), ("Warning (partial)", warning),
                     ("No Elements", no_elem)]
            for label, val in stats:
                ws.Cells[row, 1].Value2 = label
                ws.Cells[row, 1].Font.Bold = True
                ws.Cells[row, 2].Value2 = val
                row += 1
            
            ws.Columns["A:E"].AutoFit()
            
            # --- Sheet 2: Detailed Results ---
            ws2 = wb.Sheets.Add(After=wb.Sheets[wb.Sheets.Count])
            ws2.Name = "Detailed Results"
            
            headers = ["Discipline", "Category", "Parameter", "Status",
                       "Total Elements", "Missing Count", "Element IDs (sample)",
                       "Note"]
            for i, h in enumerate(headers, 1):
                ws2.Cells[1, i].Value2 = h
                ws2.Cells[1, i].Font.Bold = True
                ws2.Cells[1, i].Interior.Color = self._rgb(240, 204, 136)
            
            row = 2
            status_colors = {
                "pass": self._rgb(200, 230, 201),
                "fail": self._rgb(255, 205, 210),
                "warning": self._rgb(255, 236, 179),
                "no_elements": self._rgb(224, 224, 224),
            }
            
            for r in results:
                ws2.Cells[row, 1].Value2 = r.discipline
                ws2.Cells[row, 2].Value2 = r.category
                ws2.Cells[row, 3].Value2 = r.param_name
                ws2.Cells[row, 4].Value2 = r.status.upper()
                ws2.Cells[row, 5].Value2 = r.total_elements
                ws2.Cells[row, 6].Value2 = r.missing_count
                ws2.Cells[row, 7].Value2 = ", ".join(str(eid) for eid in r.element_ids[:20])
                if getattr(r, "unmapped", False):
                    ws2.Cells[row, 8].Value2 = "Category not supported by this checker"

                color = status_colors.get(r.status)
                if color:
                    ws2.Cells[row, 4].Interior.Color = color
                row += 1

            ws2.Columns["A:H"].AutoFit()
            
            # --- Sheet 3: Failed Only ---
            ws3 = wb.Sheets.Add(After=wb.Sheets[wb.Sheets.Count])
            ws3.Name = "Failed Parameters"
            
            fail_headers = ["Discipline", "Category", "Parameter", "Missing Count", "Total Elements"]
            for i, h in enumerate(fail_headers, 1):
                ws3.Cells[1, i].Value2 = h
                ws3.Cells[1, i].Font.Bold = True
                ws3.Cells[1, i].Interior.Color = self._rgb(255, 205, 210)
            
            row = 2
            for r in results:
                if r.status in ("fail", "warning"):
                    ws3.Cells[row, 1].Value2 = r.discipline
                    ws3.Cells[row, 2].Value2 = r.category
                    ws3.Cells[row, 3].Value2 = r.param_name
                    ws3.Cells[row, 4].Value2 = r.missing_count
                    ws3.Cells[row, 5].Value2 = r.total_elements
                    row += 1
            
            if row == 2:
                ws3.Cells[2, 1].Value2 = "All parameters passed!"
                ws3.Range["A2:E2"].Merge()
            
            ws3.Columns["A:E"].AutoFit()

            wb.SaveAs(filepath, XLSX_FORMAT)
            wb.Close()
            excel_app.Quit()
            System.Runtime.InteropServices.Marshal.ReleaseComObject(excel_app)
            return True

        except Exception as e:
            # Clean up without letting the cleanup itself throw - a bare
            # wb.Close() here used to raise NameError when the failure
            # happened before the workbook existed, hiding the real error.
            try:
                if wb is not None:
                    wb.Close(False)
            except:
                pass
            try:
                excel_app.Quit()
                System.Runtime.InteropServices.Marshal.ReleaseComObject(excel_app)
            except:
                pass
            raise e


# =====================================================================
# WPF UI
# =====================================================================
XAML_STR = '''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="IFC-SG Parameter Checker v1.2 - DQT"
        Height="820" Width="1150"
        MinHeight="600" MinWidth="880"
        WindowStartupLocation="CenterScreen"
        Background="#FEF8E7">
    
    <Window.Resources>
        <Style x:Key="CardBorder" TargetType="Border">
            <Setter Property="Background" Value="White"/>
            <Setter Property="BorderBrush" Value="#D4B87A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="CornerRadius" Value="4"/>
            <Setter Property="Padding" Value="12,8"/>
        </Style>
        <Style x:Key="BtnPrimary" TargetType="Button">
            <Setter Property="Background" Value="#F0CC88"/>
            <Setter Property="Foreground" Value="#5D4E37"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Padding" Value="12,7"/>
            <Setter Property="BorderBrush" Value="#D4B87A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="FontSize" Value="11"/>
        </Style>
        <Style x:Key="BtnSecondary" TargetType="Button">
            <Setter Property="Background" Value="White"/>
            <Setter Property="Foreground" Value="#5D4E37"/>
            <Setter Property="Padding" Value="10,6"/>
            <Setter Property="BorderBrush" Value="#D4B87A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="FontSize" Value="11"/>
        </Style>
        <Style x:Key="BtnSuccess" TargetType="Button">
            <Setter Property="Background" Value="#C8E6C9"/>
            <Setter Property="Foreground" Value="#2E7D32"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Padding" Value="14,8"/>
            <Setter Property="BorderBrush" Value="#81C784"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="FontSize" Value="13"/>
        </Style>
        <Style x:Key="BtnDanger" TargetType="Button">
            <Setter Property="Background" Value="#FFCDD2"/>
            <Setter Property="Foreground" Value="#C62828"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Padding" Value="10,6"/>
            <Setter Property="BorderBrush" Value="#EF9A9A"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
        </Style>
    </Window.Resources>
    
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        
        <!-- Row 0: Header -->
        <Border Grid.Row="0" Background="#F0CC88" CornerRadius="5" Padding="14,10" Margin="0,0,0,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0">
                    <TextBlock Text="IFC-SG Parameter Checker v1.2" FontSize="17" FontWeight="Bold"/>
                    <TextBlock Text="by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37"/>
                    <TextBlock Text="Check required IFC+SG parameters in Revit model" FontSize="11" Foreground="#5D4E37" Margin="0,2,0,0"/>
                </StackPanel>
                <Button x:Name="btnHelp" Grid.Column="1" Content="? Help" Padding="10,4"
                        Background="White" VerticalAlignment="Center"/>
            </Grid>
        </Border>
        
        <!-- Row 1: Config Import Bar -->
        <Border Grid.Row="1" Style="{StaticResource CardBorder}" Margin="0,0,0,8">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                
                <TextBlock Grid.Column="0" Text="Config:" FontWeight="SemiBold" 
                           FontSize="12" VerticalAlignment="Center" Margin="0,0,8,0" Foreground="#5D4E37"/>
                <ComboBox x:Name="cmbConfig" Grid.Column="1" Padding="8,5" FontSize="11"/>
                
                <Button x:Name="btnImportXML" Grid.Column="2" Content="Import XML" 
                        Style="{StaticResource BtnPrimary}" Margin="6,0,0,0"/>
                <Button x:Name="btnImportExcel" Grid.Column="3" Content="Import Excel" 
                        Style="{StaticResource BtnPrimary}" Margin="4,0,0,0"/>
                <Button x:Name="btnSaveConfig" Grid.Column="4" Content="Save JSON" 
                        Style="{StaticResource BtnSecondary}" Margin="4,0,0,0"/>
                <Button x:Name="btnDeleteConfig" Grid.Column="5" Content="Delete" 
                        Style="{StaticResource BtnDanger}" Margin="4,0,0,0"/>
            </Grid>
        </Border>
        
        <!-- Row 2: Summary Cards -->
        <Grid Grid.Row="2" Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            
            <Border Grid.Column="0" Style="{StaticResource CardBorder}" Margin="0,0,3,0">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock x:Name="txtTotalParams" Text="0" FontSize="20" FontWeight="Bold" Foreground="#5D4E37" HorizontalAlignment="Center"/>
                    <TextBlock Text="Params" FontSize="9" Foreground="#999" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="1" Style="{StaticResource CardBorder}" Margin="2,0,2,0">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock x:Name="txtCategories" Text="0" FontSize="20" FontWeight="Bold" Foreground="#5D4E37" HorizontalAlignment="Center"/>
                    <TextBlock Text="Categories" FontSize="9" Foreground="#999" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="2" Style="{StaticResource CardBorder}" Margin="2,0,2,0" Background="#E8F5E9">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock x:Name="txtPassed" Text="0" FontSize="20" FontWeight="Bold" Foreground="#2E7D32" HorizontalAlignment="Center"/>
                    <TextBlock Text="Passed" FontSize="9" Foreground="#388E3C" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="3" Style="{StaticResource CardBorder}" Margin="2,0,2,0" Background="#FFEBEE">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock x:Name="txtFailed" Text="0" FontSize="20" FontWeight="Bold" Foreground="#C62828" HorizontalAlignment="Center"/>
                    <TextBlock Text="Failed" FontSize="9" Foreground="#D32F2F" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="4" Style="{StaticResource CardBorder}" Margin="2,0,2,0" Background="#FFF8E1">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock x:Name="txtWarning" Text="0" FontSize="20" FontWeight="Bold" Foreground="#F57F17" HorizontalAlignment="Center"/>
                    <TextBlock Text="Partial" FontSize="9" Foreground="#F9A825" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="5" Style="{StaticResource CardBorder}" Margin="3,0,0,0" Background="#ECEFF1">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock x:Name="txtNoElem" Text="0" FontSize="20" FontWeight="Bold" Foreground="#546E7A" HorizontalAlignment="Center"/>
                    <TextBlock Text="No Elem" FontSize="9" Foreground="#78909C" HorizontalAlignment="Center"/>
                </StackPanel>
            </Border>
        </Grid>
        
        <!-- Row 3: Main Content -->
        <Grid Grid.Row="3" Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="250"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            
            <!-- Left: Discipline/Category tree -->
            <Border Grid.Column="0" Style="{StaticResource CardBorder}" Margin="0,0,4,0">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                    </Grid.RowDefinitions>
                    
                    <TextBlock Grid.Row="0" Text="Disciplines / Categories" FontWeight="Bold"
                               FontSize="12" Foreground="#5D4E37" Margin="0,0,0,6"/>

                    <StackPanel Grid.Row="1" Margin="0,0,0,6">
                        <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
                            <Button x:Name="btnExpandAll" Content="Expand"
                                    Style="{StaticResource BtnSecondary}" Padding="6,3" FontSize="10" Margin="0,0,4,0"/>
                            <Button x:Name="btnCollapseAll" Content="Collapse"
                                    Style="{StaticResource BtnSecondary}" Padding="6,3" FontSize="10"/>
                        </StackPanel>
                        <StackPanel Orientation="Horizontal">
                            <TextBlock Text="Tick:" FontSize="10" VerticalAlignment="Center"
                                       Foreground="#888" Margin="0,0,5,0"/>
                            <Button x:Name="btnTreeAll" Content="All"
                                    Style="{StaticResource BtnSecondary}" Padding="6,3" FontSize="10" Margin="0,0,4,0"/>
                            <Button x:Name="btnTreeNone" Content="None"
                                    Style="{StaticResource BtnSecondary}" Padding="6,3" FontSize="10" Margin="0,0,4,0"/>
                            <Button x:Name="btnTreeInvert" Content="Invert"
                                    Style="{StaticResource BtnSecondary}" Padding="6,3" FontSize="10"/>
                        </StackPanel>
                        <TextBlock Text="Click a row to select - Shift + click for a range"
                                   FontSize="9" TextWrapping="Wrap"
                                   Foreground="#AAA" Margin="0,3,0,0"/>
                    </StackPanel>

                    <TreeView x:Name="tvCategories" Grid.Row="2" 
                              BorderBrush="#E0E0E0" BorderThickness="1" Background="White">
                    </TreeView>
                </Grid>
            </Border>
            
            <!-- Right: Results -->
            <Border Grid.Column="1" Style="{StaticResource CardBorder}" Margin="4,0,0,0">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                    </Grid.RowDefinitions>

                    <TextBlock Grid.Row="0" x:Name="txtResultHeader" Text="Load a config and click Run Check"
                               FontWeight="Bold" FontSize="12" Foreground="#5D4E37" Margin="0,0,0,4"/>
                    
                    <!-- Filter bar -->
                    <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="0,0,0,6">
                        <TextBlock Text="Filter:" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="#888"/>
                        <Button x:Name="btnFilterAll" Content="All" Style="{StaticResource BtnSecondary}" 
                                Padding="8,3" FontSize="10" Margin="0,0,3,0"/>
                        <Button x:Name="btnFilterFail" Content="Failed" Style="{StaticResource BtnDanger}" 
                                Padding="8,3" FontSize="10" Margin="0,0,3,0"/>
                        <Button x:Name="btnFilterWarn" Content="Partial" Style="{StaticResource BtnSecondary}" 
                                Padding="8,3" FontSize="10" Margin="0,0,3,0"/>
                        <Button x:Name="btnFilterPass" Content="Passed" Style="{StaticResource BtnSecondary}" 
                                Padding="8,3" FontSize="10" Margin="0,0,8,0"/>
                        <Button x:Name="btnSelectAllFailed" Content="&#x25BA; Select All Failed" 
                                Style="{StaticResource BtnDanger}" Padding="8,3" FontSize="10" 
                                Margin="0,0,8,0" IsEnabled="False"/>
                        <TextBlock Text="Search:" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="#888"/>
                        <TextBox x:Name="txtSearch" Width="150" Padding="4,3" FontSize="11"/>
                    </StackPanel>

                    <!-- Multi-select bar -->
                    <Border Grid.Row="2" Background="#FAF6EC" BorderBrush="#E8E0D0"
                            BorderThickness="1" CornerRadius="3" Padding="6,4" Margin="0,0,0,6">
                        <StackPanel>
                            <StackPanel Orientation="Horizontal">
                                <TextBlock Text="Multi-select:" FontSize="11" VerticalAlignment="Center"
                                           Margin="0,0,6,0" Foreground="#5D4E37" FontWeight="SemiBold"/>
                                <Button x:Name="btnTickAll" Content="Select All"
                                        Style="{StaticResource BtnSecondary}" Padding="8,3" FontSize="10" Margin="0,0,3,0"/>
                                <Button x:Name="btnTickNone" Content="Un-select"
                                        Style="{StaticResource BtnSecondary}" Padding="8,3" FontSize="10" Margin="0,0,3,0"/>
                                <Button x:Name="btnTickInvert" Content="Invert"
                                        Style="{StaticResource BtnSecondary}" Padding="8,3" FontSize="10" Margin="0,0,3,0"/>
                                <Button x:Name="btnTickFailed" Content="Tick Failed"
                                        Style="{StaticResource BtnSecondary}" Padding="8,3" FontSize="10" Margin="0,0,10,0"/>
                                <TextBlock Text="(Shift + click = range)" FontSize="10"
                                           VerticalAlignment="Center" Foreground="#AAA" Margin="0,0,10,0"/>
                                <TextBlock x:Name="txtTickCount" Text="0 rows ticked" FontSize="11"
                                           VerticalAlignment="Center" Foreground="#888"/>
                            </StackPanel>
                            <StackPanel Orientation="Horizontal" Margin="0,5,0,0">
                                <Button x:Name="btnSelectTicked" Content="&#x25BA; Select Ticked in Revit"
                                        Style="{StaticResource BtnPrimary}" Padding="10,3" FontSize="10" IsEnabled="False" Margin="0,0,4,0"/>
                                <Button x:Name="btnZoomTicked" Content="&#x1F50D; Zoom To Ticked"
                                        Style="{StaticResource BtnSecondary}" Padding="10,3" FontSize="10" IsEnabled="False" Margin="0,0,4,0"/>
                                <Button x:Name="btnIsolateTicked" Content="&#x1F441; Isolate Ticked"
                                        Style="{StaticResource BtnSecondary}" Padding="10,3" FontSize="10" IsEnabled="False" Margin="0,0,4,0"/>
                                <Button x:Name="btnResetIsolate" Content="Reset Isolate/Hide"
                                        Style="{StaticResource BtnSecondary}" Padding="10,3" FontSize="10"/>
                            </StackPanel>
                        </StackPanel>
                    </Border>

                    <!-- Results list -->
                    <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto">
                        <StackPanel x:Name="spResults"/>
                    </ScrollViewer>
                </Grid>
            </Border>
        </Grid>
        
        <!-- Row 4: Action Buttons -->
        <Grid Grid.Row="4" Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            
            <TextBlock x:Name="txtStatus" Grid.Column="0" Text="Ready. Import a config or select saved config." 
                       FontSize="11" Foreground="#888" VerticalAlignment="Center"/>
            
            <Button x:Name="btnRunCheck" Grid.Column="1" Content="&#x25B6; Run Check" 
                    Style="{StaticResource BtnSuccess}" Margin="0,0,6,0" IsEnabled="False"/>
            <Button x:Name="btnExportExcel" Grid.Column="2" Content="&#x1F4CA; Export Excel" 
                    Style="{StaticResource BtnPrimary}" Margin="0,0,6,0" IsEnabled="False"/>
            <Button x:Name="btnClose" Grid.Column="3" Content="Close" 
                    Style="{StaticResource BtnSecondary}"/>
        </Grid>
        
        <!-- Row 5: Footer -->
        <Border Grid.Row="5" Background="#F5F0E0" CornerRadius="3" Padding="8,4">
            <Grid>
                <TextBlock Text="IFC-SG Parameter Checker v1.2 | Dang Quoc Truong (DQT)" 
                           FontSize="9" Foreground="#999" HorizontalAlignment="Left"/>
                <TextBlock x:Name="txtFooter" Text="" 
                           FontSize="9" Foreground="#999" HorizontalAlignment="Right"/>
            </Grid>
        </Border>
    </Grid>
</Window>
'''


# =====================================================================
# MAIN WINDOW
# =====================================================================
class IFCSGCheckerWindow:
    """Main IFC-SG Parameter Checker window"""
    
    def __init__(self):
        self.config = None
        self.results = None
        self.all_results = []
        self.checker = ParamChecker(doc)
        self.reporter = ExcelReporter(doc)
        # Row checkboxes currently on screen: [(CheckBox, CheckResult), ...]
        self.row_checks = []
        self.disc_checks = []
        self.cat_checks = []
        # Guards the discipline -> categories cascade during bulk ticking.
        self._suspend_cascade = False
        # Anchors for shift + click range ticking.
        self._last_cat_index = None
        self._last_row_index = None
        # Blue fill painted across a ticked row/category/discipline - the
        # same visual regardless of whether the tick came from a direct
        # click, a shift-click range, or a parent cascade. Light enough that
        # the row's own text colours stay readable on top of it.
        try:
            self._tick_brush = BrushConverter().ConvertFromString("#BBDEFB")
        except:
            self._tick_brush = None
        # A row's background before it was ever selected, so unticking puts
        # back what was there (a result row's pass/fail colour, a tree row's
        # transparent) instead of clearing it.
        self._base_bg = {}

        # Parse XAML
        self.window = XamlReader.Parse(XAML_STR)

        self._get_controls()
        self._apply_ui_scale()
        self._mute_tree_selection()
        self._bind_events()
        self._load_saved_configs()

        self.txtFooter.Text = "{} | {}".format(
            doc.ProjectInformation.Name or "Untitled",
            datetime.datetime.now().strftime("%Y-%m-%d"))

    def _apply_ui_scale(self):
        """Scale the whole window by UI_SCALE.

        One layout transform on the root grid enlarges text, icons, buttons
        and spacing by the same factor, including the rows built in code -
        far safer than editing every FontSize and Width by hand and missing
        some. The window grows to match, then gets clamped to the screen so
        it still fits on a laptop."""
        try:
            root = self.window.Content
            root.LayoutTransform = ScaleTransform(UI_SCALE, UI_SCALE)
        except:
            return

        try:
            work = System.Windows.SystemParameters.WorkArea
            max_w = work.Width * 0.96
            max_h = work.Height * 0.94
            self.window.Width = min(BASE_WIDTH * UI_SCALE, max_w)
            self.window.Height = min(BASE_HEIGHT * UI_SCALE, max_h)
            self.window.MinWidth = min(880 * UI_SCALE, max_w)
            self.window.MinHeight = min(600 * UI_SCALE, max_h)
        except:
            pass

    def _mute_tree_selection(self):
        """Blank out the TreeView's own selection highlight.

        Rows paint their own blue fill when they are ticked. WPF's built-in
        highlight marks a different thing - the one focused item - so leaving
        it on puts a second, contradictory colour under ours. Best effort per
        key: an older WPF without the inactive pair still gets the active one
        muted, and a total failure only means the stock highlight shows too."""
        try:
            resources = self.tvCategories.Resources
        except:
            return
        clear = System.Windows.Media.Brushes.Transparent
        try:
            text = BrushConverter().ConvertFromString("#333333")
        except:
            text = None
        for key_name, brush in (("HighlightBrushKey", clear),
                                ("HighlightTextBrushKey", text),
                                ("InactiveSelectionHighlightBrushKey", clear),
                                ("InactiveSelectionHighlightTextBrushKey", text)):
            try:
                key = getattr(System.Windows.SystemColors, key_name, None)
                if key is not None and brush is not None:
                    resources[key] = brush
            except:
                pass

    def _pump_ui(self):
        """Let WPF repaint mid-operation.

        The check and the export both run on the UI thread (the Revit API
        demands it), so without this the status text never actually appears
        and the window looks frozen."""
        try:
            self.window.Dispatcher.Invoke(
                System.Windows.Threading.DispatcherPriority.Background,
                System.Action(lambda: None))
        except:
            pass

    def _get_controls(self):
        names = [
            "cmbConfig", "btnImportXML", "btnImportExcel", "btnSaveConfig", "btnDeleteConfig",
            "txtTotalParams", "txtCategories", "txtPassed", "txtFailed", "txtWarning", "txtNoElem",
            "tvCategories", "btnExpandAll", "btnCollapseAll",
            "btnTreeAll", "btnTreeNone", "btnTreeInvert",
            "txtResultHeader", "spResults",
            "btnFilterAll", "btnFilterFail", "btnFilterWarn", "btnFilterPass",
            "btnSelectAllFailed", "txtSearch",
            "btnTickAll", "btnTickNone", "btnTickInvert", "btnTickFailed",
            "txtTickCount", "btnSelectTicked", "btnZoomTicked", "btnIsolateTicked",
            "btnResetIsolate",
            "txtStatus", "btnRunCheck", "btnExportExcel", "btnClose", "txtFooter",
            "btnHelp"
        ]
        for name in names:
            setattr(self, name, self.window.FindName(name))

    def _bind_events(self):
        self.btnHelp.Click += self._on_help
        self.btnImportXML.Click += self._on_import_xml
        self.btnImportExcel.Click += self._on_import_excel
        self.btnSaveConfig.Click += self._on_save_config
        self.btnDeleteConfig.Click += self._on_delete_config
        self.cmbConfig.SelectionChanged += self._on_config_changed
        self.btnExpandAll.Click += self._on_expand_all
        self.btnCollapseAll.Click += self._on_collapse_all
        self.btnTreeAll.Click += lambda s, e: self._set_tree_checked("all")
        self.btnTreeNone.Click += lambda s, e: self._set_tree_checked("none")
        self.btnTreeInvert.Click += lambda s, e: self._set_tree_checked("invert")
        self.btnTickAll.Click += lambda s, e: self._set_rows_ticked("all")
        self.btnTickNone.Click += lambda s, e: self._set_rows_ticked("none")
        self.btnTickInvert.Click += lambda s, e: self._set_rows_ticked("invert")
        self.btnTickFailed.Click += lambda s, e: self._set_rows_ticked("failed")
        self.btnSelectTicked.Click += self._on_select_ticked
        self.btnZoomTicked.Click += self._on_zoom_ticked
        self.btnIsolateTicked.Click += self._on_isolate_ticked
        self.btnResetIsolate.Click += self._on_reset_isolate
        self.btnFilterAll.Click += lambda s, e: self._apply_filter("all")
        self.btnFilterFail.Click += lambda s, e: self._apply_filter("fail")
        self.btnFilterWarn.Click += lambda s, e: self._apply_filter("warning")
        self.btnFilterPass.Click += lambda s, e: self._apply_filter("pass")
        self.txtSearch.TextChanged += lambda s, e: self._apply_filter(self._current_filter)
        self.btnSelectAllFailed.Click += self._on_select_all_failed
        self.btnRunCheck.Click += self._on_run_check
        self.btnExportExcel.Click += self._on_export_excel
        self.btnClose.Click += lambda s, e: self.window.Close()
        self._current_filter = "all"
    
    # =================================================================
    # CONFIG MANAGEMENT
    # =================================================================
    def _on_help(self, sender, args):
        """? button in the header: open the tool's help page, or fall back
        to the in-app summary if the help folder is not there."""
        if _open_help_page("ifcsg_checker.html"):
            return
        System.Windows.MessageBox.Show(
            "IFC-SG Parameter Checker\n\n"
            "Checks that the parameters CORENET X requires actually exist and "
            "carry a value on the model's elements, then lets you select the "
            "failing ones straight in Revit.\n\n"
            "STAT CARDS\n"
            "  PARAMS / CATEGORIES - size of the selected requirement set\n"
            "  PASSED   - every element has the parameter filled in\n"
            "  FAILED   - no element has it (usually the parameter is absent)\n"
            "  PARTIAL  - some elements have it, some do not\n"
            "  NO ELEM  - nothing of that category in this model\n\n"
            "WORKFLOW\n"
            "  1. Load a config (Import XML / Excel, or pick a saved one)\n"
            "  2. Pick the disciplines and categories to cover - click "
            "anywhere on a row to select it, Shift+Click for a range, or use "
            "Tick All / None / Invert. Selected rows are filled blue\n"
            "  3. Run Check, then filter the results (All / Failed / Partial / "
            "Passed) or search\n"
            "  4. Tick result rows (Select All / Un-select / Invert / Tick "
            "Failed, or Shift+Click for a range), then:\n"
            "       - Select Ticked in Revit - sets the Revit selection\n"
            "       - Zoom To Ticked - selects and frames them in the view\n"
            "       - Isolate Ticked - temporarily isolates them; Reset "
            "Isolate/Hide brings everything back\n"
            "  5. Export Excel writes Summary / Detailed / Failed sheets\n\n"
            "A category the tool cannot collect is marked \"not supported\" "
            "rather than being reported as simply empty.",
            "Parameter Checker - Help",
            MessageBoxButton.OK, MessageBoxImage.Information)

    def _load_saved_configs(self):
        self.cmbConfig.Items.Clear()
        if os.path.exists(CONFIG_DIR):
            for f in sorted(os.listdir(CONFIG_DIR)):
                if f.endswith('.json'):
                    self.cmbConfig.Items.Add(os.path.splitext(f)[0])
        if self.cmbConfig.Items.Count > 0:
            self.cmbConfig.SelectedIndex = 0
    
    def _on_config_changed(self, sender, args):
        sel = self.cmbConfig.SelectedItem
        if sel:
            path = os.path.join(CONFIG_DIR, str(sel) + ".json")
            try:
                self.config = ParamCheckConfig.from_json(path)
                self._refresh_tree()
                self._update_config_stats()
                d, c, p = self.config.get_total_stats()
                self._update_selection_status()
                if p == 0:
                    # A config that parsed to nothing used to load silently
                    # and then "check" zero parameters.
                    self.txtStatus.Text = (
                        "Config '{}' has no parameters in it - re-import the "
                        "source XML or pick another config.".format(self.config.name))
                else:
                    self.txtStatus.Text = "Config loaded: {} ({}) - {} params".format(
                        self.config.name, self.config.source, p)
            except Exception as e:
                self.txtStatus.Text = "Error loading config: {}".format(str(e))
    
    def _on_import_xml(self, sender, args):
        from System.Windows.Forms import OpenFileDialog, DialogResult
        dlg = OpenFileDialog()
        dlg.Filter = "XML Files (*.xml)|*.xml|All Files (*.*)|*.*"
        dlg.Title = "Import Autodesk Model Checker XML"
        
        if dlg.ShowDialog() == DialogResult.OK:
            try:
                # Validate before replacing the loaded config, so a dud file
                # cannot leave the window pointing at an empty one.
                imported = ParamCheckConfig.from_xml(dlg.FileName)
                d, c, p = imported.get_total_stats()
                if p == 0:
                    System.Windows.MessageBox.Show(
                        "No parameters found in that XML.\n\nExpected "
                        "Heading / Section / Check elements as written by the "
                        "Autodesk Model Checker.",
                        "Nothing imported", MessageBoxButton.OK,
                        MessageBoxImage.Warning)
                    return

                self.config = imported
                # Auto-save as JSON
                name = os.path.splitext(os.path.basename(dlg.FileName))[0]
                save_path = os.path.join(CONFIG_DIR, name + ".json")
                self.config.to_json(save_path)
                
                self._load_saved_configs()
                # Select the new one
                for i in range(self.cmbConfig.Items.Count):
                    if str(self.cmbConfig.Items[i]) == name:
                        self.cmbConfig.SelectedIndex = i
                        break
                
                d, c, p = self.config.get_total_stats()
                self.txtStatus.Text = "Imported XML: {} disciplines, {} categories, {} params".format(d, c, p)
            except Exception as e:
                System.Windows.MessageBox.Show(
                    "Error importing XML:\n{}".format(str(e)),
                    "Import Error", MessageBoxButton.OK, MessageBoxImage.Error)
    
    def _on_import_excel(self, sender, args):
        from System.Windows.Forms import OpenFileDialog, DialogResult
        dlg = OpenFileDialog()
        dlg.Filter = "Excel Files (*.xlsx;*.xls)|*.xlsx;*.xls|All Files (*.*)|*.*"
        dlg.Title = "Import Excel Parameter Mapping"
        
        if dlg.ShowDialog() == DialogResult.OK:
            try:
                imported = ParamCheckConfig.from_excel(dlg.FileName)
                d, c, p = imported.get_total_stats()
                if p == 0:
                    System.Windows.MessageBox.Show(
                        "No parameters found in that sheet.\n\nExpected "
                        "column A = Discipline, B = Category, C = Parameter, "
                        "with a header row.",
                        "Nothing imported", MessageBoxButton.OK,
                        MessageBoxImage.Warning)
                    return

                self.config = imported
                name = os.path.splitext(os.path.basename(dlg.FileName))[0]
                save_path = os.path.join(CONFIG_DIR, name + ".json")
                self.config.to_json(save_path)
                
                self._load_saved_configs()
                for i in range(self.cmbConfig.Items.Count):
                    if str(self.cmbConfig.Items[i]) == name:
                        self.cmbConfig.SelectedIndex = i
                        break
                
                d, c, p = self.config.get_total_stats()
                self.txtStatus.Text = "Imported Excel: {} disciplines, {} categories, {} params".format(d, c, p)
            except Exception as e:
                System.Windows.MessageBox.Show(
                    "Error importing Excel:\n{}".format(str(e)),
                    "Import Error", MessageBoxButton.OK, MessageBoxImage.Error)
    
    def _on_save_config(self, sender, args):
        if not self.config:
            return
        from System.Windows.Forms import SaveFileDialog, DialogResult
        dlg = SaveFileDialog()
        dlg.Filter = "JSON Files (*.json)|*.json"
        dlg.Title = "Save Config"
        dlg.InitialDirectory = CONFIG_DIR
        if dlg.ShowDialog() == DialogResult.OK:
            self.config.to_json(dlg.FileName)
            self.txtStatus.Text = "Config saved: {}".format(dlg.FileName)
    
    def _on_delete_config(self, sender, args):
        sel = self.cmbConfig.SelectedItem
        if not sel:
            return
        result = System.Windows.MessageBox.Show(
            "Delete config '{}'?".format(sel),
            "Confirm", MessageBoxButton.YesNo, MessageBoxImage.Warning)
        if result == MessageBoxResult.Yes:
            path = os.path.join(CONFIG_DIR, str(sel) + ".json")
            if os.path.exists(path):
                os.remove(path)
            self._load_saved_configs()
    
    # =================================================================
    # TREE VIEW
    # =================================================================
    def _refresh_tree(self):
        self.tvCategories.Items.Clear()
        self.disc_checks = []   # [(CheckBox, discipline name)]
        self.cat_checks = []    # [(CheckBox, discipline name, category name)]
        self._last_cat_index = None
        self._base_bg = {}      # rows are gone; their remembered fills go too
        if not self.config:
            return

        converter = BrushConverter()

        for disc_name, disc_data in self.config.disciplines.items():
            # Discipline node
            disc_item = TreeViewItem()
            disc_item.IsExpanded = True
            # Let the header fill the row so its selection fill does too.
            disc_item.HorizontalContentAlignment = \
                System.Windows.HorizontalAlignment.Stretch
            
            # Wrapping border lets a ticked discipline fill blue, same as a
            # ticked category or result row - independent of the TreeView's
            # own (single-item) selection highlight. It stretches the full
            # width so the fill covers the whole row, and carries a
            # Transparent background because a Border with no brush at all
            # is invisible to the mouse over its empty space.
            disc_row = System.Windows.Controls.Border()
            disc_row.BorderThickness = System.Windows.Thickness(0)
            disc_row.CornerRadius = System.Windows.CornerRadius(2)
            disc_row.Padding = System.Windows.Thickness(2, 1, 2, 1)
            disc_row.HorizontalAlignment = System.Windows.HorizontalAlignment.Stretch
            disc_row.Background = System.Windows.Media.Brushes.Transparent
            disc_row.Cursor = System.Windows.Input.Cursors.Hand
            disc_row.PreviewMouseLeftButtonDown += self._on_disc_row_click

            disc_sp = StackPanel()
            disc_sp.Orientation = System.Windows.Controls.Orientation.Horizontal

            chk_disc = CheckBox()
            chk_disc.IsChecked = System.Nullable[System.Boolean](
                bool(disc_data.get("enabled", True)))
            chk_disc.Margin = System.Windows.Thickness(0, 0, 6, 0)
            chk_disc.Tag = (disc_name, disc_row)
            chk_disc.Checked += self._on_disc_toggled
            chk_disc.Unchecked += self._on_disc_toggled
            self.disc_checks.append((chk_disc, disc_name))
            disc_row.Tag = chk_disc     # the row click drives this box
            self._apply_checkbox_highlight(chk_disc, disc_row)

            lbl_disc = TextBlock()
            lbl_disc.Text = u"{} ({} categories)".format(
                disc_name, len(disc_data.get("categories", {})))
            lbl_disc.FontWeight = System.Windows.FontWeights.Bold
            lbl_disc.FontSize = 12
            try:
                lbl_disc.Foreground = converter.ConvertFromString("#5D4E37")
            except:
                pass
            
            disc_sp.Children.Add(chk_disc)
            disc_sp.Children.Add(lbl_disc)
            disc_row.Child = disc_sp
            disc_item.Header = disc_row
            
            # Category nodes
            for cat_name, cat_data in disc_data.get("categories", {}).items():
                cat_item = TreeViewItem()
                cat_item.HorizontalContentAlignment = \
                    System.Windows.HorizontalAlignment.Stretch

                cat_row = System.Windows.Controls.Border()
                cat_row.BorderThickness = System.Windows.Thickness(0)
                cat_row.CornerRadius = System.Windows.CornerRadius(2)
                cat_row.Padding = System.Windows.Thickness(2, 1, 2, 1)
                cat_row.HorizontalAlignment = System.Windows.HorizontalAlignment.Stretch
                cat_row.Background = System.Windows.Media.Brushes.Transparent
                cat_row.Cursor = System.Windows.Input.Cursors.Hand
                cat_row.PreviewMouseLeftButtonDown += self._on_cat_row_click

                cat_sp = StackPanel()
                cat_sp.Orientation = System.Windows.Controls.Orientation.Horizontal

                chk_cat = CheckBox()
                chk_cat.IsChecked = System.Nullable[System.Boolean](
                    bool(cat_data.get("enabled", True)))
                chk_cat.Margin = System.Windows.Thickness(0, 0, 6, 0)
                chk_cat.Tag = (disc_name, cat_name, cat_row)
                chk_cat.Checked += self._on_cat_toggled
                chk_cat.Unchecked += self._on_cat_toggled
                self.cat_checks.append((chk_cat, disc_name, cat_name))
                # The row, not the box, owns the click - see _on_cat_row_click.
                cat_row.Tag = chk_cat
                cat_row.ToolTip = ("Click anywhere on the row to select it, "
                                   "Shift + click to select a range")
                self._apply_checkbox_highlight(chk_cat, cat_row)

                param_count = len(cat_data.get("params", []))
                lbl_cat = TextBlock()
                lbl_cat.Text = u"{} ({} params)".format(cat_name, param_count)
                lbl_cat.FontSize = 11
                if not self.checker.is_mapped(cat_name):
                    # Flag it here rather than letting the whole category come
                    # back as a silent row of "no elements" after the run.
                    lbl_cat.Text += u"  - not supported"
                    try:
                        lbl_cat.Foreground = converter.ConvertFromString("#B0A48C")
                    except:
                        pass

                cat_sp.Children.Add(chk_cat)
                cat_sp.Children.Add(lbl_cat)
                cat_row.Child = cat_sp
                cat_item.Header = cat_row
                
                disc_item.Items.Add(cat_item)

            self.tvCategories.Items.Add(disc_item)

        # A config saved while a discipline was off but its categories were
        # still on would otherwise load into that same dead state.
        self._sync_all_disciplines()
    
    # =================================================================
    # SHIFT + CLICK RANGE TICKING
    # =================================================================
    def _shift_held(self):
        try:
            modifiers = System.Windows.Input.Keyboard.Modifiers
            shift = System.Windows.Input.ModifierKeys.Shift
            return (modifiers & shift) == shift
        except:
            return False

    def _index_of(self, pairs, checkbox):
        for index, entry in enumerate(pairs):
            if entry[0] is checkbox:
                return index
        return None

    def _range_tick(self, pairs, checkbox, anchor, on_done):
        """Tick or untick every box between the anchor and the clicked one.

        Returns the new anchor, or None when this was not a shift-click and
        the caller should just record the plain click. The clicked box is set
        here rather than left to WPF, so the caller marks the event handled
        to stop it toggling a second time."""
        index = self._index_of(pairs, checkbox)
        if index is None:
            return None
        if anchor is None or anchor >= len(pairs) or anchor == index:
            return None

        # The clicked box drives the whole range, so shift-clicking a ticked
        # box clears the range and shift-clicking an empty one fills it.
        state = not bool(checkbox.IsChecked)
        low, high = min(anchor, index), max(anchor, index)

        self._suspend_cascade = True
        try:
            for position in range(low, high + 1):
                target = pairs[position][0]
                if target.IsEnabled:
                    target.IsChecked = System.Nullable[System.Boolean](state)
        finally:
            self._suspend_cascade = False

        on_done()
        return anchor

    def _on_cat_row_click(self, sender, args):
        """Select a category by clicking anywhere on its row.

        The checkbox used to be the only hit target, so clicking a category
        name did nothing and picking several meant hitting a run of tiny
        boxes - which is what "cannot multi-select" meant in practice. The
        whole row is handled here, the box included, so WPF must not toggle
        it a second time on the way back up: hence Handled."""
        checkbox = sender.Tag
        if checkbox is None:
            return
        args.Handled = True
        index = self._index_of(self.cat_checks, checkbox)
        if index is None:
            return

        def done():
            self._sync_all_disciplines()
            self._update_selection_status()

        if self._shift_held():
            if self._range_tick(self.cat_checks, checkbox,
                                self._last_cat_index, done) is not None:
                return      # anchor stays put, ready for the next range
        # The Checked/Unchecked handler does the cascade and the counters.
        checkbox.IsChecked = System.Nullable[System.Boolean](
            not bool(checkbox.IsChecked))
        self._last_cat_index = index

    def _on_disc_row_click(self, sender, args):
        """Select a whole discipline by clicking anywhere on its row.

        No shift-range here on purpose: ticking a discipline cascades down to
        its categories, and a range tick deliberately suspends that cascade,
        so a discipline range would leave parents and children disagreeing."""
        checkbox = sender.Tag
        if checkbox is None:
            return
        args.Handled = True
        checkbox.IsChecked = System.Nullable[System.Boolean](
            not bool(checkbox.IsChecked))

    def _on_row_preview_click(self, sender, args):
        if self._shift_held():
            if self._range_tick(self.row_checks, sender,
                                self._last_row_index,
                                self._update_tick_count) is not None:
                args.Handled = True
                return
        self._last_row_index = self._index_of(self.row_checks, sender)

    def _set_checked(self, checkbox, state):
        """Set a checkbox without letting the cascade run.

        Used whenever the code, rather than the user, moves a box - the
        Checked/Unchecked handlers still record the config change, they just
        do not push the change back the other way and fight themselves."""
        if bool(checkbox.IsChecked) == bool(state):
            return
        previous = self._suspend_cascade
        self._suspend_cascade = True
        try:
            checkbox.IsChecked = System.Nullable[System.Boolean](bool(state))
        finally:
            self._suspend_cascade = previous

    def _apply_checkbox_highlight(self, checkbox, border):
        """Fill a row with the selection blue while its checkbox is ticked.

        Called from every tick path - a direct click anywhere on the row, a
        shift-click range, a bulk Select All/Invert/Tick Failed, and a
        discipline cascading down to its categories - so a tick always reads
        as an ordinary filled selection across the whole row.

        The row's background before it was first selected is remembered so
        unticking restores it: a result row goes back to its pass/fail
        colour rather than being left blank."""
        if border is None:
            return
        try:
            if border not in self._base_bg:
                self._base_bg[border] = border.Background
            if bool(checkbox.IsChecked):
                border.Background = self._tick_brush
            else:
                border.Background = self._base_bg[border]
        except:
            pass

    def _on_disc_toggled(self, sender, args):
        disc_name, disc_row = sender.Tag
        self._apply_checkbox_highlight(sender, disc_row)
        state = bool(sender.IsChecked)
        if disc_name in self.config.disciplines:
            self.config.disciplines[disc_name]["enabled"] = state

        # Ticking a discipline ticks everything under it, so one click covers
        # a whole discipline instead of twenty categories.
        if not self._suspend_cascade:
            previous = self._suspend_cascade
            self._suspend_cascade = True
            try:
                for chk, chk_disc, _cat in self.cat_checks:
                    if chk_disc == disc_name:
                        chk.IsChecked = System.Nullable[System.Boolean](state)
            finally:
                self._suspend_cascade = previous
            self._update_selection_status()

    def _on_cat_toggled(self, sender, args):
        disc, cat, cat_row = sender.Tag
        self._apply_checkbox_highlight(sender, cat_row)
        if disc in self.config.disciplines:
            cats = self.config.disciplines[disc].get("categories", {})
            if cat in cats:
                cats[cat]["enabled"] = bool(sender.IsChecked)

        if not self._suspend_cascade:
            self._sync_discipline(disc)
            self._update_selection_status()

    def _sync_discipline(self, disc_name):
        """Make a discipline follow its categories: on when any of them is.

        A discipline that stays unticked makes run_check skip every category
        under it, so ticking a category while its discipline was off looked
        like Run Check doing nothing at all."""
        any_on = False
        for chk, chk_disc, _cat in self.cat_checks:
            if chk_disc == disc_name and bool(chk.IsChecked):
                any_on = True
                break
        for chk, chk_disc in self.disc_checks:
            if chk_disc == disc_name:
                self._set_checked(chk, any_on)
                break

    def _sync_all_disciplines(self):
        for _chk, disc_name in self.disc_checks:
            self._sync_discipline(disc_name)

    def _set_tree_checked(self, mode):
        """Tick every discipline and category at once: all / none / invert.

        Only the categories are set here; the disciplines are reconciled
        afterwards so a parent can never end up contradicting its children."""
        if not self.config:
            return

        self._suspend_cascade = True
        try:
            for chk, _disc, _cat in self.cat_checks:
                if mode == "all":
                    state = True
                elif mode == "none":
                    state = False
                else:
                    state = not bool(chk.IsChecked)
                chk.IsChecked = System.Nullable[System.Boolean](state)
        finally:
            self._suspend_cascade = False

        self._sync_all_disciplines()
        self._update_selection_status()

    def _selection_totals(self):
        """(categories, parameters) the next run will actually cover."""
        cats = 0
        params = 0
        if not self.config:
            return cats, params
        for _disc_name, disc_data in self.config.disciplines.items():
            if not disc_data.get("enabled", True):
                continue
            for _cat_name, cat_data in disc_data.get("categories", {}).items():
                if not cat_data.get("enabled", True):
                    continue
                cats += 1
                params += len(cat_data.get("params", []))
        return cats, params

    def _update_selection_status(self):
        """Show how much of the config the next run will actually cover."""
        if not self.config:
            return
        cats, params = self._selection_totals()
        self.txtTotalParams.Text = str(params)
        self.txtCategories.Text = str(cats)
        # Run Check used to stay enabled with nothing selected and then
        # silently produce no results, which read as the tool being dead.
        self.btnRunCheck.IsEnabled = params > 0
        if params > 0:
            self.txtStatus.Text = "{} categories / {} parameters selected".format(
                cats, params)
        else:
            self.txtStatus.Text = "Nothing selected - tick at least one category."

    def _on_expand_all(self, sender, args):
        for item in self.tvCategories.Items:
            item.IsExpanded = True

    def _on_collapse_all(self, sender, args):
        for item in self.tvCategories.Items:
            item.IsExpanded = False

    def _update_config_stats(self):
        if self.config:
            d, c, p = self.config.get_total_stats()
            self.txtTotalParams.Text = str(p)
            self.txtCategories.Text = str(c)
    
    # =================================================================
    # RUN CHECK
    # =================================================================
    def _on_run_check(self, sender, args):
        if not self.config:
            return

        cats, params = self._selection_totals()
        if params == 0:
            # Say so instead of running an empty check and reporting nothing,
            # which is indistinguishable from the button not working.
            self.txtStatus.Text = "Nothing selected - tick at least one category."
            System.Windows.MessageBox.Show(
                "No categories are ticked, so there is nothing to check.\n\n"
                "Tick the disciplines or categories you want on the left, or "
                "press Tick: All.",
                "Nothing selected", MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        self.txtStatus.Text = "Running IFC-SG parameter checks..."
        self.window.Cursor = System.Windows.Input.Cursors.Wait
        self.btnRunCheck.IsEnabled = False
        self._pump_ui()

        def on_progress(current, total, label=""):
            self.txtStatus.Text = "Checking {}/{} - {}".format(
                current, total, label)
            self._pump_ui()

        try:
            self.results = self.checker.run_check(self.config, on_progress)
            self.all_results = list(self.results)
            
            # Update cards
            passed = len([r for r in self.results if r.status == "pass"])
            failed = len([r for r in self.results if r.status == "fail"])
            warning = len([r for r in self.results if r.status == "warning"])
            no_elem = len([r for r in self.results if r.status == "no_elements"])
            
            self.txtPassed.Text = str(passed)
            self.txtFailed.Text = str(failed)
            self.txtWarning.Text = str(warning)
            self.txtNoElem.Text = str(no_elem)
            
            self._current_filter = "all"
            self._render_results(self.results)
            
            self.btnExportExcel.IsEnabled = True
            self.btnSelectAllFailed.IsEnabled = True
            self.txtResultHeader.Text = "Check Results ({} checks)".format(len(self.results))

            unmapped = len([r for r in self.results if getattr(r, "unmapped", False)])
            status = "Done: {} passed, {} failed, {} partial, {} no elements".format(
                passed, failed, warning, no_elem)
            if unmapped:
                status += " ({} in categories this tool cannot collect)".format(unmapped)
            self.txtStatus.Text = status

        except Exception as e:
            self.txtStatus.Text = "Error: {}".format(str(e))
            System.Windows.MessageBox.Show(
                "Error:\n{}".format(traceback.format_exc()),
                "Error", MessageBoxButton.OK, MessageBoxImage.Error)
        finally:
            self.btnRunCheck.IsEnabled = self._selection_totals()[1] > 0
            self.window.Cursor = System.Windows.Input.Cursors.Arrow
    
    def _apply_filter(self, filter_type):
        self._current_filter = filter_type
        if not self.all_results:
            return
        
        search_text = self.txtSearch.Text.strip().lower() if self.txtSearch.Text else ""
        
        filtered = []
        for r in self.all_results:
            # Status filter
            if filter_type == "fail" and r.status not in ("fail",):
                continue
            if filter_type == "warning" and r.status not in ("warning",):
                continue
            if filter_type == "pass" and r.status not in ("pass",):
                continue
            
            # Search filter
            if search_text:
                searchable = "{}{}{}".format(
                    r.discipline, r.category, r.param_name).lower()
                if search_text not in searchable:
                    continue
            
            filtered.append(r)
        
        self._render_results(filtered)
    
    def _on_select_all_failed(self, sender, args):
        """Select ALL failed elements across all categories in Revit"""
        if not self.all_results:
            return
        all_ids = []
        for r in self.all_results:
            if r.status in ("fail", "warning"):
                all_ids.extend(r.element_ids)
        unique_ids = list(set(all_ids))
        if unique_ids:
            self._select_elements_in_revit(unique_ids[:2000])
            self.txtStatus.Text = "Selected {} failed elements in Revit".format(len(unique_ids))
        else:
            self.txtStatus.Text = "No failed elements to select"
    
    def _select_elements_in_revit(self, element_ids):
        """Select elements in Revit (no zoom - see _on_zoom_ticked for that)."""
        try:
            ids = System.Collections.Generic.List[ElementId]()
            for eid in element_ids:
                try:
                    ids.Add(ElementId(int(eid)))  # Revit 2026: accepts Int64
                except:
                    pass
            if ids.Count > 0:
                uidoc.Selection.SetElementIds(ids)
                self.txtStatus.Text = "Selected {} elements in Revit".format(ids.Count)
        except Exception as e:
            self.txtStatus.Text = "Select error: {}".format(str(e))
    
    def _compute_category_stats(self, results):
        """Compute % completion per discipline > category"""
        stats = {}  # "disc|cat" -> {total, passed, failed, warning, no_elem, pct}
        for r in results:
            key = "{}|{}".format(r.discipline, r.category)
            if key not in stats:
                stats[key] = {"total": 0, "pass": 0, "fail": 0, "warning": 0, "no_elements": 0}
            stats[key]["total"] += 1
            stats[key][r.status] = stats[key].get(r.status, 0) + 1
        
        for key, s in stats.items():
            checkable = s["total"] - s.get("no_elements", 0)
            if checkable > 0:
                s["pct"] = int(round(s["pass"] / float(checkable) * 100))
            else:
                s["pct"] = -1  # No elements to check
        return stats
    
    def _render_results(self, results):
        # Forget the remembered fills of the rows about to be thrown away.
        # The tree's entries have to survive a re-run, so this drops just
        # these borders rather than resetting the whole map.
        for old_chk, _old_row in self.row_checks:
            try:
                self._base_bg.pop(old_chk.Tag, None)
            except:
                pass
        self.spResults.Children.Clear()
        self.row_checks = []
        self._last_row_index = None
        converter = BrushConverter()
        
        status_bg = {
            "pass": "#E8F5E9", "fail": "#FFEBEE",
            "warning": "#FFF8E1", "no_elements": "#ECEFF1"
        }
        status_fg = {
            "pass": "#2E7D32", "fail": "#C62828",
            "warning": "#F57F17", "no_elements": "#78909C"
        }
        status_icon = {
            "pass": u"\u2714", "fail": u"\u2718",
            "warning": u"\u26A0", "no_elements": u"\u23F8"
        }
        
        # Compute category stats for progress bars
        cat_stats = self._compute_category_stats(self.all_results)
        
        current_disc = ""
        current_cat = ""
        
        for r in results:
            # Discipline header
            if r.discipline != current_disc:
                current_disc = r.discipline
                current_cat = ""
                
                disc_border = System.Windows.Controls.Border()
                disc_border.Margin = System.Windows.Thickness(0, 8, 0, 2)
                disc_border.Padding = System.Windows.Thickness(8, 4, 8, 4)
                try:
                    disc_border.Background = converter.ConvertFromString("#F0CC88")
                except:
                    pass
                disc_border.CornerRadius = System.Windows.CornerRadius(3)
                
                disc_txt = TextBlock()
                disc_txt.Text = r.discipline
                disc_txt.FontWeight = System.Windows.FontWeights.Bold
                disc_txt.FontSize = 13
                try:
                    disc_txt.Foreground = converter.ConvertFromString("#5D4E37")
                except:
                    pass
                disc_border.Child = disc_txt
                self.spResults.Children.Add(disc_border)
            
            # Category header with progress bar
            if r.category != current_cat:
                current_cat = r.category
                stat_key = "{}|{}".format(r.discipline, r.category)
                stat = cat_stats.get(stat_key, {})
                pct = stat.get("pct", 0)
                cat_pass = stat.get("pass", 0)
                cat_no_elem = stat.get("no_elements", 0)
                cat_fail = stat.get("fail", 0)
                cat_warn = stat.get("warning", 0)
                
                # Category container
                cat_border = System.Windows.Controls.Border()
                cat_border.Margin = System.Windows.Thickness(0, 4, 0, 2)
                cat_border.Padding = System.Windows.Thickness(4, 3, 4, 3)
                cat_border.CornerRadius = System.Windows.CornerRadius(3)
                try:
                    cat_border.Background = converter.ConvertFromString("#F9F6EE")
                    cat_border.BorderBrush = converter.ConvertFromString("#E8E0D0")
                except:
                    pass
                cat_border.BorderThickness = System.Windows.Thickness(1)
                
                cat_grid = Grid()
                cg1 = ColumnDefinition()
                cg1.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
                cg2 = ColumnDefinition()
                cg2.Width = System.Windows.GridLength(200)
                cg3 = ColumnDefinition()
                cg3.Width = System.Windows.GridLength(80)
                cat_grid.ColumnDefinitions.Add(cg1)
                cat_grid.ColumnDefinitions.Add(cg2)
                cat_grid.ColumnDefinitions.Add(cg3)
                
                # Category name + counts
                cat_info = StackPanel()
                cat_name_txt = TextBlock()
                cat_name_txt.Text = u"\u25B8 {}".format(r.category)
                cat_name_txt.FontWeight = System.Windows.FontWeights.SemiBold
                cat_name_txt.FontSize = 11
                try:
                    cat_name_txt.Foreground = converter.ConvertFromString("#5D4E37")
                except:
                    pass
                cat_info.Children.Add(cat_name_txt)
                
                # Sub stats text
                sub_parts = []
                if cat_pass > 0:
                    sub_parts.append("{} pass".format(cat_pass))
                if cat_fail > 0:
                    sub_parts.append("{} fail".format(cat_fail))
                if cat_warn > 0:
                    sub_parts.append("{} partial".format(cat_warn))
                if cat_no_elem > 0:
                    sub_parts.append("{} N/A".format(cat_no_elem))
                
                sub_txt = TextBlock()
                sub_txt.Text = " | ".join(sub_parts)
                sub_txt.FontSize = 9
                try:
                    sub_txt.Foreground = converter.ConvertFromString("#999")
                except:
                    pass
                cat_info.Children.Add(sub_txt)
                Grid.SetColumn(cat_info, 0)
                cat_grid.Children.Add(cat_info)
                
                # Progress bar
                if pct >= 0:
                    prog_sp = StackPanel()
                    prog_sp.VerticalAlignment = System.Windows.VerticalAlignment.Center
                    prog_sp.Margin = System.Windows.Thickness(4, 0, 4, 0)
                    
                    # Bar background
                    bar_border = System.Windows.Controls.Border()
                    bar_border.Height = 10
                    bar_border.CornerRadius = System.Windows.CornerRadius(5)
                    try:
                        bar_border.Background = converter.ConvertFromString("#E0E0E0")
                    except:
                        pass
                    
                    # Bar fill
                    bar_grid = Grid()
                    bar_bg = System.Windows.Controls.Border()
                    bar_bg.Height = 10
                    bar_bg.CornerRadius = System.Windows.CornerRadius(5)
                    try:
                        bar_bg.Background = converter.ConvertFromString("#E0E0E0")
                    except:
                        pass
                    bar_grid.Children.Add(bar_bg)
                    
                    bar_fill = System.Windows.Controls.Border()
                    bar_fill.Height = 10
                    bar_fill.CornerRadius = System.Windows.CornerRadius(5)
                    bar_fill.HorizontalAlignment = System.Windows.HorizontalAlignment.Left
                    # Width as percentage
                    bar_fill.Width = max(1, pct * 1.8)  # 180px max width
                    
                    if pct >= 80:
                        fill_color = "#66BB6A"
                    elif pct >= 50:
                        fill_color = "#FFA726"
                    else:
                        fill_color = "#EF5350"
                    try:
                        bar_fill.Background = converter.ConvertFromString(fill_color)
                    except:
                        pass
                    bar_grid.Children.Add(bar_fill)
                    
                    prog_sp.Children.Add(bar_grid)
                    
                    Grid.SetColumn(prog_sp, 1)
                    cat_grid.Children.Add(prog_sp)
                
                # Percentage text + Select All Failed button
                pct_sp = StackPanel()
                pct_sp.VerticalAlignment = System.Windows.VerticalAlignment.Center
                pct_sp.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
                
                if pct >= 0:
                    pct_txt = TextBlock()
                    pct_txt.Text = "{}%".format(pct)
                    pct_txt.FontSize = 12
                    pct_txt.FontWeight = System.Windows.FontWeights.Bold
                    pct_txt.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
                    try:
                        if pct >= 80:
                            pct_txt.Foreground = converter.ConvertFromString("#2E7D32")
                        elif pct >= 50:
                            pct_txt.Foreground = converter.ConvertFromString("#F57F17")
                        else:
                            pct_txt.Foreground = converter.ConvertFromString("#C62828")
                    except:
                        pass
                    pct_sp.Children.Add(pct_txt)
                else:
                    na_txt = TextBlock()
                    na_txt.Text = "N/A"
                    na_txt.FontSize = 11
                    na_txt.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
                    try:
                        na_txt.Foreground = converter.ConvertFromString("#999")
                    except:
                        pass
                    pct_sp.Children.Add(na_txt)
                
                # Select all failed in this category
                if cat_fail > 0 or cat_warn > 0:
                    all_fail_ids = []
                    for ar in self.all_results:
                        if ar.discipline == r.discipline and ar.category == r.category:
                            if ar.status in ("fail", "warning"):
                                all_fail_ids.extend(ar.element_ids)
                    
                    if all_fail_ids:
                        sel_all_btn = Button()
                        sel_all_btn.Content = "Select"
                        sel_all_btn.FontSize = 9
                        sel_all_btn.Padding = System.Windows.Thickness(4, 1, 4, 1)
                        sel_all_btn.Margin = System.Windows.Thickness(0, 2, 0, 0)
                        sel_all_btn.Cursor = System.Windows.Input.Cursors.Hand
                        sel_all_btn.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
                        try:
                            sel_all_btn.Background = converter.ConvertFromString("#FFCDD2")
                            sel_all_btn.Foreground = converter.ConvertFromString("#C62828")
                            sel_all_btn.BorderBrush = converter.ConvertFromString("#EF9A9A")
                        except:
                            pass
                        sel_all_btn.BorderThickness = System.Windows.Thickness(1)
                        # Store IDs - deduplicate
                        unique_ids = list(set(all_fail_ids))[:500]
                        sel_all_btn.Tag = unique_ids
                        sel_all_btn.Click += self._on_select_btn_click
                        pct_sp.Children.Add(sel_all_btn)
                
                Grid.SetColumn(pct_sp, 2)
                cat_grid.Children.Add(pct_sp)
                
                cat_border.Child = cat_grid
                self.spResults.Children.Add(cat_border)
            
            # Parameter row
            row_border = System.Windows.Controls.Border()
            row_border.Margin = System.Windows.Thickness(16, 1, 0, 1)
            row_border.Padding = System.Windows.Thickness(8, 3, 8, 3)
            row_border.CornerRadius = System.Windows.CornerRadius(2)
            # No outline until ticked - the pass/fail background stays the
            # only colour on an untouched row.
            row_border.BorderThickness = System.Windows.Thickness(0)
            try:
                row_border.Background = converter.ConvertFromString(
                    status_bg.get(r.status, "#FAFAFA"))
            except:
                pass
            
            row_grid = Grid()
            c0 = ColumnDefinition()
            c0.Width = System.Windows.GridLength(22)
            c1 = ColumnDefinition()
            c1.Width = System.Windows.GridLength(28)
            c2 = ColumnDefinition()
            c2.Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
            c3 = ColumnDefinition()
            c3.Width = System.Windows.GridLength(120)
            c4 = ColumnDefinition()
            c4.Width = System.Windows.GridLength(55)
            row_grid.ColumnDefinitions.Add(c0)
            row_grid.ColumnDefinitions.Add(c1)
            row_grid.ColumnDefinitions.Add(c2)
            row_grid.ColumnDefinitions.Add(c3)
            row_grid.ColumnDefinitions.Add(c4)

            # Tick box - lets several rows be picked and sent to Revit as one
            # selection instead of one row at a time.
            row_chk = CheckBox()
            row_chk.VerticalAlignment = System.Windows.VerticalAlignment.Center
            row_chk.Cursor = System.Windows.Input.Cursors.Hand
            row_chk.IsEnabled = bool(r.element_ids)
            row_chk.Tag = row_border    # so the tick handler can outline this row
            row_chk.Checked += self._on_row_tick_changed
            row_chk.Unchecked += self._on_row_tick_changed
            row_chk.PreviewMouseLeftButtonDown += self._on_row_preview_click
            row_chk.ToolTip = "Shift + click to tick a range of rows"
            Grid.SetColumn(row_chk, 0)
            row_grid.Children.Add(row_chk)
            self.row_checks.append((row_chk, r))

            # Icon
            icon = TextBlock()
            icon.Text = status_icon.get(r.status, "?")
            icon.FontSize = 12
            icon.VerticalAlignment = System.Windows.VerticalAlignment.Center
            try:
                icon.Foreground = converter.ConvertFromString(
                    status_fg.get(r.status, "#666"))
            except:
                pass
            Grid.SetColumn(icon, 1)
            row_grid.Children.Add(icon)

            # Param name
            name_txt = TextBlock()
            name_txt.Text = r.param_name
            name_txt.FontSize = 11
            name_txt.VerticalAlignment = System.Windows.VerticalAlignment.Center
            Grid.SetColumn(name_txt, 2)
            row_grid.Children.Add(name_txt)

            # Count info
            if r.status == "no_elements":
                count_text = "Not supported" if getattr(r, "unmapped", False) \
                    else "No elements"
            elif r.status == "pass":
                count_text = "{} OK".format(r.total_elements)
            else:
                count_text = "{}/{} missing".format(r.missing_count, r.total_elements)
            
            count_txt = TextBlock()
            count_txt.Text = count_text
            count_txt.FontSize = 10
            count_txt.VerticalAlignment = System.Windows.VerticalAlignment.Center
            count_txt.HorizontalAlignment = System.Windows.HorizontalAlignment.Right
            try:
                count_txt.Foreground = converter.ConvertFromString(
                    status_fg.get(r.status, "#888"))
            except:
                pass
            Grid.SetColumn(count_txt, 3)
            row_grid.Children.Add(count_txt)
            
            # Select button for failed/warning params
            if r.status in ("fail", "warning") and r.element_ids:
                sel_btn = Button()
                sel_btn.Content = u"\u25BA Select"
                sel_btn.FontSize = 9
                sel_btn.Padding = System.Windows.Thickness(3, 1, 3, 1)
                sel_btn.VerticalAlignment = System.Windows.VerticalAlignment.Center
                sel_btn.Cursor = System.Windows.Input.Cursors.Hand
                try:
                    sel_btn.Background = converter.ConvertFromString("#FFF3E0")
                    sel_btn.Foreground = converter.ConvertFromString("#E65100")
                    sel_btn.BorderBrush = converter.ConvertFromString("#FFCC80")
                except:
                    pass
                sel_btn.BorderThickness = System.Windows.Thickness(1)
                sel_btn.Tag = list(r.element_ids)[:MAX_STORED_IDS]
                sel_btn.Click += self._on_select_btn_click
                Grid.SetColumn(sel_btn, 4)
                row_grid.Children.Add(sel_btn)
            
            row_border.Child = row_grid
            self.spResults.Children.Add(row_border)

        # Rebuilding the list drops every tick box, so reset the counter.
        self._update_tick_count()

    def _on_select_btn_click(self, sender, args):
        """Handle select button click - select elements in Revit"""
        ids = sender.Tag
        if ids:
            self._select_elements_in_revit(ids)

    # =================================================================
    # MULTI-SELECT (row tick boxes)
    # =================================================================
    def _on_row_tick_changed(self, sender, args):
        self._apply_checkbox_highlight(sender, sender.Tag)
        # Recounting on every box would be quadratic during a bulk tick, and
        # a full run has hundreds of rows - the bulk callers count once.
        if not self._suspend_cascade:
            self._update_tick_count()

    def _set_rows_ticked(self, mode):
        """Bulk tick the visible result rows: all / none / invert / failed.

        Only rows that actually carry element ids can be ticked - ticking a
        passing row would contribute nothing to the Revit selection."""
        self._suspend_cascade = True
        try:
            for chk, result in self.row_checks:
                if not chk.IsEnabled:
                    continue
                if mode == "all":
                    state = True
                elif mode == "none":
                    state = False
                elif mode == "failed":
                    state = result.status in ("fail", "warning")
                else:
                    state = not bool(chk.IsChecked)
                chk.IsChecked = System.Nullable[System.Boolean](state)
        finally:
            self._suspend_cascade = False
        self._update_tick_count()

    def _ticked_results(self):
        return [r for chk, r in self.row_checks if bool(chk.IsChecked)]

    def _ticked_element_ids(self):
        """Element ids behind every ticked row, deduplicated."""
        ids = set()
        for r in self._ticked_results():
            ids.update(r.element_ids)
        return ids

    def _ticked_ids_as_net_list(self):
        """Ticked element ids as a .NET List[ElementId] - Zoom and Isolate
        both call Revit API methods that need a real ICollection<ElementId>,
        not a Python list/set."""
        ids = self._ticked_element_ids()
        if not ids:
            return None
        net_ids = System.Collections.Generic.List[ElementId]()
        for eid in ids:
            try:
                net_ids.Add(ElementId(int(eid)))
            except:
                pass
        return net_ids if net_ids.Count > 0 else None

    def _update_tick_count(self):
        ticked = self._ticked_results()
        ids = self._ticked_element_ids()
        self.txtTickCount.Text = "{} rows ticked / {} elements".format(
            len(ticked), len(ids))
        has_ids = len(ids) > 0
        self.btnSelectTicked.IsEnabled = has_ids
        self.btnZoomTicked.IsEnabled = has_ids
        self.btnIsolateTicked.IsEnabled = has_ids

    def _on_select_ticked(self, sender, args):
        """Select every element behind the ticked rows, in one go."""
        ids = self._ticked_element_ids()
        if not ids:
            self.txtStatus.Text = "Tick at least one row that has elements."
            return
        self._select_elements_in_revit(list(ids))

    def _on_zoom_ticked(self, sender, args):
        """Select and frame every element behind the ticked rows."""
        net_ids = self._ticked_ids_as_net_list()
        if net_ids is None:
            self.txtStatus.Text = "Tick at least one row that has elements."
            return
        try:
            uidoc.Selection.SetElementIds(net_ids)
            uidoc.ShowElements(net_ids)
            self.txtStatus.Text = "Zoomed to {} element(s).".format(net_ids.Count)
        except Exception as e:
            self.txtStatus.Text = "Zoom error: {}".format(str(e))

    def _on_isolate_ticked(self, sender, args):
        """Temporarily isolate every element behind the ticked rows in the
        active view - Reset Isolate/Hide undoes it."""
        net_ids = self._ticked_ids_as_net_list()
        if net_ids is None:
            self.txtStatus.Text = "Tick at least one row that has elements."
            return
        view = doc.ActiveView
        if view is None:
            self.txtStatus.Text = "No active view to isolate in."
            return
        t = Transaction(doc, "DQT - Isolate Ticked Elements")
        try:
            t.Start()
            view.IsolateElementsTemporary(net_ids)
            t.Commit()
            uidoc.Selection.SetElementIds(net_ids)
            self.txtStatus.Text = "Isolated {} element(s) in the active view.".format(
                net_ids.Count)
        except Exception as e:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            self.txtStatus.Text = "Isolate error: {}".format(str(e))

    def _on_reset_isolate(self, sender, args):
        """Exit temporary hide/isolate on the active view, if it is active."""
        view = doc.ActiveView
        if view is None:
            return
        t = None
        try:
            if not view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate):
                self.txtStatus.Text = "Nothing to reset - the view is not isolated."
                return
            t = Transaction(doc, "DQT - Reset Temporary Isolate/Hide")
            t.Start()
            view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
            t.Commit()
            self.txtStatus.Text = "Temporary isolate/hide reset."
        except Exception as e:
            if t is not None and t.HasStarted() and not t.HasEnded():
                t.RollBack()
            self.txtStatus.Text = "Reset error: {}".format(str(e))

    # =================================================================
    # EXPORT
    # =================================================================
    def _default_report_name(self):
        """Suggested report filename, short enough for Windows to accept.

        The project name is sanitised and capped: a real CORENET project name
        is long enough on its own to push the full path past the Windows
        limit, which made SaveAs fail every time."""
        try:
            project = safe_filename(doc.ProjectInformation.Name, 40)
        except:
            project = ""
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if project:
            name = "IFC-SG_Check_{}_{}".format(project, stamp)
        else:
            name = "IFC-SG_Check_{}".format(stamp)

        # Trim further if the folder path itself is deep.
        room = MAX_PATH - len(REPORTS_DIR) - len(".xlsx") - 1
        if room > 20 and len(name) > room:
            name = "IFC-SG_Check_{}".format(stamp)
        return name

    def _on_export_excel(self, sender, args):
        if not self.all_results or not self.config:
            self.txtStatus.Text = "Run a check first - there is nothing to export."
            return
        from System.Windows.Forms import SaveFileDialog, DialogResult

        dlg = SaveFileDialog()
        dlg.Filter = "Excel Files (*.xlsx)|*.xlsx"
        dlg.DefaultExt = "xlsx"
        dlg.AddExtension = True
        dlg.FileName = self._default_report_name()
        dlg.InitialDirectory = REPORTS_DIR

        if dlg.ShowDialog() == DialogResult.OK:
            path = dlg.FileName
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"

            if len(path) > MAX_PATH:
                System.Windows.MessageBox.Show(
                    "That path is {} characters long - Excel cannot save "
                    "beyond about {}.\n\nPick a shorter file name or a folder "
                    "closer to the drive root.".format(len(path), MAX_PATH),
                    "Path too long", MessageBoxButton.OK, MessageBoxImage.Warning)
                return

            self.txtStatus.Text = "Exporting..."
            self.window.Cursor = System.Windows.Input.Cursors.Wait
            self._pump_ui()
            try:
                self.reporter.generate(self.config, self.all_results, path)
                self.txtStatus.Text = "Exported: {}".format(os.path.basename(path))
                result = System.Windows.MessageBox.Show(
                    "Report exported!\nOpen now?", "Done",
                    MessageBoxButton.YesNo, MessageBoxImage.Information)
                if result == MessageBoxResult.Yes:
                    os.startfile(path)
            except Exception as e:
                self.txtStatus.Text = "Export failed: {}".format(str(e))
                # Show the whole traceback - "export does not work" with no
                # detail is impossible to act on.
                System.Windows.MessageBox.Show(
                    "Export error:\n{}\n\nMake sure Microsoft Excel is "
                    "installed and the file is not already open.\n\n{}".format(
                        str(e), traceback.format_exc()),
                    "Error", MessageBoxButton.OK, MessageBoxImage.Error)
            finally:
                self.window.Cursor = System.Windows.Input.Cursors.Arrow
    
    def show(self):
        self.window.ShowDialog()


# =====================================================================
# ENTRY POINT
# =====================================================================
try:
    window = IFCSGCheckerWindow()
    window.show()
except Exception as e:
    print("Error: {}".format(str(e)))
    print(traceback.format_exc())