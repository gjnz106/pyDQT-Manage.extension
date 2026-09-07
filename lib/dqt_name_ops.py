# -*- coding: utf-8 -*-
"""
Shared name transformations for the DQT rename tools.

Family Manager renames families inside the open project; Purge Families
renames .rfa files in a folder. Both build the new name from the same
options, so the rules live here rather than being copied into each tool.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

import os
import re

CASE_MODES = ["none", "upper", "lower", "title"]

# Characters Windows refuses in a file name.
INVALID_FILENAME_CHARS = '\\/:*?"<>|'

# Revit's automatic backups: FamilyName.0001.rfa / Project.0042.rvt
_BACKUP_RE = re.compile(r'^.+\.\d{4}\.(rfa|rvt)$', re.IGNORECASE)


def is_revit_backup(filename):
    return bool(_BACKUP_RE.match(filename or ""))


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
def title_case_name(name):
    """Capitalise each word, treating underscore, hyphen and space as
    separators and leaving the separators exactly where they were."""
    return re.sub(r'[^_\-\s]+',
                  lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(),
                  name or "")


def convert_case(name, mode, keep_upper=0):
    """Apply a case conversion, optionally forcing the first keep_upper
    characters to UPPERCASE and leaving them out of the conversion, so a
    project prefix survives it: keep_upper=5 turns Lb_wh_Ano into LB_WH_Ano.

    Every conversion preserves length, so the kept head splices back by index.
    keep_upper works on its own too - with no conversion selected it just
    uppercases the prefix."""
    name = name or ""

    if mode == "upper":
        converted = name.upper()
    elif mode == "lower":
        converted = name.lower()
    elif mode == "title":
        converted = title_case_name(name)
    else:
        converted = name

    try:
        keep = int(keep_upper or 0)
    except (TypeError, ValueError):
        keep = 0
    keep = max(0, min(keep, len(name)))
    if keep:
        converted = name[:keep].upper() + converted[keep:]
    return converted


def strip_spaces(name):
    """Remove every space, including the non-breaking space that copy-paste
    from Excel or a PDF leaves behind - it is invisible in a grid but makes
    two names that look identical compare as different."""
    return re.sub(u'[\\s ]+', '', name or "")


# ---------------------------------------------------------------------------
# Building a new name
# ---------------------------------------------------------------------------
def build_new_name(name, prefix="", suffix="", find="", replace="",
                   case_mode="none", keep_upper=0, remove_spaces=False):
    """Apply every rename option, in the order they are presented.

    Unlike the in-project rename dialog, these combine rather than override
    each other: renaming a folder of families usually means stripping a junk
    substring AND adding the project prefix in one pass."""
    result = name or ""

    if find:
        result = result.replace(find, replace or "")

    result = (prefix or "") + result + (suffix or "")
    result = convert_case(result, case_mode, keep_upper)

    if remove_spaces:
        result = strip_spaces(result)

    return result


def filename_problem(name):
    """Why this cannot be a file name, or None."""
    if not (name or "").strip():
        return "the new name would be empty"
    bad = sorted({c for c in name if c in INVALID_FILENAME_CHARS})
    if bad:
        return "contains {}".format(" ".join(bad))
    if name != name.strip():
        return "starts or ends with a space"
    if name.endswith("."):
        return "ends with a dot"
    return None


# ---------------------------------------------------------------------------
# Planning a folder rename
# ---------------------------------------------------------------------------
def plan_renames(paths, **options):
    """Work out what each file would be renamed to, without touching disk.

    Returns a list of {path, old, new, target, status, reason}, where status
    is 'rename', 'unchanged' or 'skip'.

    Targets are only checked once every file has been planned, so two files
    resolving to the same name means the second is skipped rather than
    silently overwriting the first. A file whose own name is being freed does
    not block the file taking it, which is what makes a case-only rename
    (abc.rfa -> ABC.rfa) work on a case-insensitive filesystem."""
    plan = []

    for path in paths:
        folder = os.path.dirname(path)
        filename = os.path.basename(path)
        old, ext = os.path.splitext(filename)

        entry = {"path": path, "old": old, "new": old, "target": path,
                 "status": "unchanged", "reason": ""}

        if is_revit_backup(filename):
            entry["status"] = "skip"
            entry["reason"] = "Revit backup file"
            plan.append(entry)
            continue

        new = build_new_name(old, **options)
        entry["new"] = new

        problem = filename_problem(new)
        if problem:
            entry["status"] = "skip"
            entry["reason"] = problem
            plan.append(entry)
            continue

        if new == old:
            plan.append(entry)
            continue

        entry["target"] = os.path.join(folder, new + ext)
        entry["status"] = "rename"
        plan.append(entry)

    # Names that will be free once the plan runs.
    leaving = set()
    for entry in plan:
        if entry["status"] == "rename":
            leaving.add(entry["path"].lower())

    claimed = set()
    for entry in plan:
        if entry["status"] != "rename":
            continue
        target_key = entry["target"].lower()
        if target_key in claimed:
            entry["status"] = "skip"
            entry["reason"] = "another file is already renamed to this"
        elif os.path.exists(entry["target"]) and target_key not in leaving:
            entry["status"] = "skip"
            entry["reason"] = "a file with that name already exists"
        else:
            claimed.add(target_key)

    return plan


def apply_renames(plan):
    """Rename every planned file. Returns (renamed_count, failures) where
    failures is a list of (old_name, reason). A file that cannot be renamed -
    read-only, open in Revit, permissions - is recorded and the rest of the
    batch continues."""
    renamed = 0
    failures = []

    for entry in plan:
        if entry.get("status") != "rename":
            continue
        try:
            os.rename(entry["path"], entry["target"])
            entry["path"] = entry["target"]
            entry["status"] = "renamed"
            renamed += 1
        except Exception as ex:
            entry["status"] = "skip"
            entry["reason"] = str(ex)
            failures.append((entry["old"], str(ex)))

    return renamed, failures
