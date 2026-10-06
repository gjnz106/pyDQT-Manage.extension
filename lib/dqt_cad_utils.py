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

import System
from Autodesk.Revit.DB import (FilteredElementCollector, ImportInstance,
                               CADLinkType, ElementId)


def _eid_int(eid):
    """ElementId -> int, across Revit 2024-2026 (.Value vs .IntegerValue)."""
    if eid is None:
        return -1
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def make_element_id(value):
    """int -> ElementId, whichever constructor overload this build wants.

    Revit 2025+ made ElementId 64-bit, so a build may expose Int64, Int32
    or both; picking the wrong one is how an id silently turns into
    something Revit then refuses to act on."""
    try:
        return ElementId(value)
    except:
        pass
    try:
        return ElementId(System.Int64(value))
    except:
        pass
    return ElementId(System.Int32(value))


def get_instances_of_type(doc, type_id_int):
    """Every placed CAD instance currently using this type."""
    found = []
    for inst in get_cad_instances(doc):
        try:
            if _eid_int(inst.GetTypeId()) == type_id_int:
                found.append(inst)
        except:
            continue
    return found


def cad_type_of(doc, instance):
    """The CADLinkType behind an ImportInstance, or None."""
    try:
        return doc.GetElement(instance.GetTypeId())
    except:
        return None


def has_external_resource(cad_type):
    """True when the CAD type is loaded through an external resource server
    - a DWG linked from the cloud (Autodesk Docs / Forma, "Path Type: Cloud"
    in Manage Links). Such a link is NOT an external *file* reference, so
    IsExternalFileReference() is False for it; it shows up here instead."""
    try:
        refs = cad_type.GetExternalResourceReferences()
    except:
        return False
    if refs is None:
        return False
    try:
        return refs.Count > 0
    except:
        try:
            return len(refs) > 0
        except:
            return False


def is_cad_link_type(cad_type):
    """True when the CAD type itself shows it is a link - the only test
    there is for a type with no instance left. Any of these is enough, and
    an import (which embeds the geometry) keeps none of them:

    - Element.IsExternalFileReference() - a .dwg on disk or a server;
    - an external resource reference - a .dwg in the cloud (Autodesk Docs
      / Forma). A cloud link is NOT an external file reference, so it
      reports False above; going by IsExternalFileReference() alone is how
      a cloud link used to be counted as an Import;
    - an external file reference that resolves to a usable path. Any
      non-null reference is NOT proof on its own; one carrying no usable
      path is not a link.
    """
    if cad_type is None:
        return False

    try:
        if cad_type.IsExternalFileReference():
            return True
    except:
        pass

    if has_external_resource(cad_type):
        return True

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


def is_cad_link(doc, instance):
    """True for a CAD Link, False for a CAD Import (embedded geometry).

    1) ImportInstance.IsLinked - Revit's own answer for the instance, and
       right for every kind of link: a .dwg on disk, on a server or in the
       cloud (Autodesk Docs / Forma). Used whenever the build has it.
    2) Only when IsLinked is missing (this suite's CadtoWall tool found it
       missing on some Revit 2026 builds): what the CAD type shows - see
       is_cad_link_type.
    """
    try:
        return bool(instance.IsLinked)
    except:
        pass
    return is_cad_link_type(cad_type_of(doc, instance))


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
