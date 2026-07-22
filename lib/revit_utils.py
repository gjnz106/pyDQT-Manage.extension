# -*- coding: utf-8 -*-
"""
Revit Utilities Module for DQT Manager Tools
Helper functions for Revit API operations

Copyright (c) 2025 Copyright by Dang Quoc Truong (DQT)
All rights reserved.
"""

from Autodesk.Revit.DB import Transaction, BuiltInParameter
from config import InvalidChars


# ============================================================================
# NAME OPERATIONS
# ============================================================================

def get_element_name(element):
    """Get element name using SYMBOL_NAME_PARAM
    
    Args:
        element: Revit element
        
    Returns:
        str: Element name or "Unnamed"
    """
    try:
        name_param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if name_param:
            return name_param.AsString() or "Unnamed"
    except:
        pass
    
    # Fallback to Name property
    try:
        return element.Name or "Unnamed"
    except:
        return "Unnamed"


def set_element_name(element, new_name):
    """Set element name
    
    Args:
        element: Revit element
        new_name: New name string
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Sanitize name first
        new_name = InvalidChars.sanitize(new_name)
        
        # Try using Name property (works for most types)
        element.Name = new_name
        return True
    except:
        pass
    
    # Fallback: try using parameter
    try:
        name_param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if name_param and not name_param.IsReadOnly:
            name_param.Set(new_name)
            return True
    except:
        pass
    
    return False


def sanitize_name(name):
    """Sanitize element name by removing invalid characters
    
    Args:
        name: String to sanitize
        
    Returns:
        str: Sanitized name
    """
    return InvalidChars.sanitize(name)


# ============================================================================
# TRANSACTION HELPERS
# ============================================================================

def safe_transaction(doc, name, action, *args, **kwargs):
    """Execute action within a safe transaction
    
    Args:
        doc: Revit document
        name: Transaction name
        action: Function to execute
        *args: Arguments for action
        **kwargs: Keyword arguments for action
        
    Returns:
        tuple: (success: bool, result: any, error: str or None)
    """
    t = Transaction(doc, name)
    t.Start()
    
    try:
        result = action(*args, **kwargs)
        t.Commit()
        return (True, result, None)
    except Exception as ex:
        if t.HasStarted():
            t.RollBack()
        return (False, None, str(ex))


# ============================================================================
# PARAMETER OPERATIONS
# ============================================================================

def get_parameter_value(element, param_name_or_builtin):
    """Get parameter value from element
    
    Args:
        element: Revit element
        param_name_or_builtin: Parameter name (str) or BuiltInParameter
        
    Returns:
        str: Parameter value as string, or None
    """
    try:
        if isinstance(param_name_or_builtin, str):
            param = element.LookupParameter(param_name_or_builtin)
        else:
            param = element.get_Parameter(param_name_or_builtin)
        
        if not param or not param.HasValue:
            return None
        
        # Try different value types
        storage_type = param.StorageType.ToString()
        
        if storage_type == "String":
            return param.AsString()
        elif storage_type == "Integer":
            return str(param.AsInteger())
        elif storage_type == "Double":
            return param.AsValueString() or str(param.AsDouble())
        elif storage_type == "ElementId":
            return str(param.AsElementId().IntegerValue)
        else:
            return param.AsValueString()
    except:
        return None


def set_parameter_value(element, param_name_or_builtin, value):
    """Set parameter value on element
    
    Args:
        element: Revit element
        param_name_or_builtin: Parameter name (str) or BuiltInParameter
        value: Value to set
        
    Returns:
        bool: True if successful
    """
    try:
        if isinstance(param_name_or_builtin, str):
            param = element.LookupParameter(param_name_or_builtin)
        else:
            param = element.get_Parameter(param_name_or_builtin)
        
        if not param or param.IsReadOnly:
            return False
        
        # Set based on storage type
        storage_type = param.StorageType.ToString()
        
        if storage_type == "String":
            param.Set(str(value))
        elif storage_type == "Integer":
            param.Set(int(value))
        elif storage_type == "Double":
            param.Set(float(value))
        else:
            return False
        
        return True
    except:
        return False


# ============================================================================
# USAGE CALCULATION
# ============================================================================

def calculate_usage(doc, element_type, type_id):
    """Calculate usage count for a type
    
    Args:
        doc: Revit document
        element_type: Type of elements to check (e.g., TextNote, Wall)
        type_id: ElementId of the type
        
    Returns:
        int: Number of instances using this type
    """
    from Autodesk.Revit.DB import FilteredElementCollector
    
    try:
        collector = FilteredElementCollector(doc).OfClass(element_type)
        count = 0
        
        for elem in collector:
            try:
                if elem.GetTypeId() == type_id:
                    count += 1
            except:
                continue
        
        return count
    except:
        return 0


def calculate_usage_percentage(usage_count, total_count):
    """Calculate usage percentage
    
    Args:
        usage_count: Number of instances
        total_count: Total number of all instances
        
    Returns:
        float: Percentage (0.0 to 100.0)
    """
    if total_count <= 0:
        return 0.0
    return round((float(usage_count) / total_count) * 100, 1)


# ============================================================================
# NAME CONFLICT CHECKING
# ============================================================================

def check_name_conflict(doc, element_class, new_name, exclude_id=None):
    """Check if name already exists
    
    Args:
        doc: Revit document
        element_class: Class of elements to check (e.g., TextNoteType)
        new_name: Name to check
        exclude_id: ElementId to exclude from check (the element being renamed)
        
    Returns:
        bool: True if conflict exists, False otherwise
    """
    from Autodesk.Revit.DB import FilteredElementCollector
    
    try:
        sanitized_new = InvalidChars.sanitize(new_name)
        
        collector = FilteredElementCollector(doc).OfClass(element_class)
        
        for elem in collector:
            # Skip self
            if exclude_id and elem.Id == exclude_id:
                continue
            
            try:
                existing_name = get_element_name(elem)
                sanitized_existing = InvalidChars.sanitize(existing_name)
                
                if sanitized_existing == sanitized_new:
                    return True
            except:
                continue
        
        return False
    except:
        return False


# ============================================================================
# ELEMENT OPERATIONS
# ============================================================================

def duplicate_element(element, new_name=None):
    """Duplicate an element type
    
    Args:
        element: Element to duplicate
        new_name: Name for duplicated element (optional)
        
    Returns:
        ElementId: ID of duplicated element, or InvalidElementId on failure
    """
    from Autodesk.Revit.DB import ElementId
    
    try:
        if new_name:
            new_id = element.Duplicate(new_name)
        else:
            original_name = get_element_name(element)
            new_id = element.Duplicate("Copy of " + original_name)
        
        return new_id
    except:
        return ElementId.InvalidElementId


def delete_element(doc, element_id):
    """Delete an element
    
    Args:
        doc: Revit document
        element_id: ElementId to delete
        
    Returns:
        bool: True if successful
    """
    try:
        doc.Delete(element_id)
        return True
    except:
        return False


# ============================================================================
# TYPE CHECKING
# ============================================================================

def is_system_type(element):
    """Check if element is a system/built-in type
    
    Args:
        element: Element to check
        
    Returns:
        bool: True if system type
    """
    try:
        # Check if name parameter is read-only
        name_param = element.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if name_param and name_param.IsReadOnly:
            return True
        
        # Check if it's a predefined type
        if hasattr(element, 'get_Parameter'):
            type_param = element.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_AND_TYPE_NAMES_PARAM)
            if type_param:
                type_name = type_param.AsString()
                if type_name and "System" in type_name:
                    return True
        
        return False
    except:
        return False