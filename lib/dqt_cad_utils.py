# -*- coding: utf-8 -*-
"""
Shared CAD import/link classification for the DQT tools.

CAD Import Manager and Model Health Check both have to answer the same two
questions - "is this DWG linked or embedded?" and "are there CAD types left
with no instances?" - and they used to answer them with their own copies of
the logic, which is how they ended up disagreeing with each other and with
ACC's Model Analytics. The answers live here so there is only one of each.

Copyright (c) 2026 Dang Quoc Truong (DQT)
All rights reserved.
"""

from Autodesk.Revit.DB import (FilteredElementCollector, ImportInstance,
                               CADLinkType)


def _eid_int(eid):
    """ElementId -> int, across Revit 2024-2026 (.Value vs .IntegerValue)."""
    if eid is None:
        return -1
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def cad_type_of(doc, instance):
    """The CADLinkType behind an ImportInstance, or None."""
    try:
        return doc.GetElement(instance.GetTypeId())
    except:
        return None


def is_cad_link(doc, instance):
    """True for a CAD Link, False for a CAD Import (embedded geometry).

    Asked in order of how definitive each answer is:

    1) Element.IsExternalFileReference() on the CAD type. A Link keeps an
       external .dwg on disk and reports True; a true Import embedded the
       geometry at import time and has no external file, so it reports
       False. This is the documented, version-stable way to ask, and it is
       asked first precisely because (2) is not reliable everywhere.
    2) ImportInstance.IsLinked, when (1) is unavailable - the instance
       level property, which this suite's CadtoWall tool found missing on
       some Revit 2026 builds.
    3) An external file reference that actually resolves to a path. Any
       non-null return here is NOT proof of a link on its own; a reference
       carrying no usable path is not one.
    """
    cad_type = cad_type_of(doc, instance)

    if cad_type is not None:
        try:
            return bool(cad_type.IsExternalFileReference())
        except:
            pass

    try:
        return bool(instance.IsLinked)
    except:
        pass

    if cad_type is not None:
        try:
            efr = cad_type.GetExternalFileReference()
        except:
            efr = None
        if efr is not None:
            try:
                path = efr.GetAbsolutePath()
                if path is not None and path.Empty:
                    return False
            except:
                pass
            return True

    return False


def get_cad_instances(doc):
    """Every placed CAD import/link instance in the document."""
    try:
        return list(FilteredElementCollector(doc).OfClass(ImportInstance)
                    .WhereElementIsNotElementType())
    except:
        return []


def get_all_cad_types(doc):
    """Every CAD type ("Import Symbol") in the document.

    OfClass(CADLinkType) is the direct route, but it is unioned with a
    sweep over all element types, matched by isinstance or by class name.
    A CAD type carrying no Category has been seen to slip past the class
    filter, and those are exactly the orphans this is used to hunt - the
    ones ACC's Model Analytics reports long after every instance is gone.
    """
    found = {}

    try:
        for cad_type in FilteredElementCollector(doc).OfClass(CADLinkType):
            try:
                found[_eid_int(cad_type.Id)] = cad_type
            except:
                continue
    except:
        pass

    try:
        for elem in FilteredElementCollector(doc).WhereElementIsElementType():
            try:
                if _eid_int(elem.Id) in found:
                    continue
                if isinstance(elem, CADLinkType) or \
                        elem.GetType().Name == "CADLinkType":
                    found[_eid_int(elem.Id)] = elem
            except:
                continue
    except:
        pass

    return list(found.values())


def get_unused_cad_types(doc):
    """CAD types with zero placed instances left.

    Deleting every instance of a CAD import does NOT delete its Type -
    Revit never auto-purges a Type just because its instance count reaches
    zero, exactly like a WallType left behind after its last wall. Since
    ACC's Model Analytics reports CAD imports at the TYPE level, an orphan
    like this keeps being reported indefinitely even though the model has
    no instances of it at all.
    """
    used_type_ids = set()
    for inst in get_cad_instances(doc):
        try:
            used_type_ids.add(_eid_int(inst.GetTypeId()))
        except:
            continue

    unused = []
    for cad_type in get_all_cad_types(doc):
        try:
            if _eid_int(cad_type.Id) not in used_type_ids:
                unused.append(cad_type)
        except:
            continue
    return unused
