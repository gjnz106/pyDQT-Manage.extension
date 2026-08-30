# -*- coding: utf-8 -*-
"""
Revit Utilities - Helper functions for Revit API compatibility
Compatible with Revit 2024, 2025, 2026, 2027

Copyright (c) 2026 Dang Quoc Truong (DQT)

IMPORTANT COMPATIBILITY NOTE:
- Revit 2024/2025: ElementId.IntegerValue works
- Revit 2026+: ElementId.IntegerValue was removed, use ElementId.Value instead
- _eid_int() below works across all versions - use it instead of touching
  .IntegerValue or .Value directly anywhere else in this tool
"""

__author__ = "Dang Quoc Truong (DQT)"


def get_element_id_value(element_id):
    """Get the integer value of an ElementId - works for Revit 2024-2027."""
    if element_id is None:
        return -1

    try:
        # Revit 2026+ method first (.Value)
        if hasattr(element_id, 'Value'):
            return element_id.Value
    except Exception:
        pass

    try:
        # Fallback to Revit 2024/2025 method (.IntegerValue)
        if hasattr(element_id, 'IntegerValue'):
            return element_id.IntegerValue
    except Exception:
        pass

    # Last resort - try to convert to int
    try:
        return int(str(element_id))
    except Exception:
        return -1


def _eid_int(element_id):
    """Shorthand alias for get_element_id_value.

    Usage:
        from revit_utils import _eid_int
        id_value = _eid_int(element.Id)
    """
    return get_element_id_value(element_id)
