# -*- coding: utf-8 -*-
"""
Configuration Module for DQT Manager Tools
Centralized colors, settings, and constants

Copyright (c) 2025 Copyright by Dang Quoc Truong (DQT)
All rights reserved.
"""

from System.Windows.Media import Color

# ============================================================================
# COLORS
# ============================================================================

class Colors:
    """Centralized color definitions for consistent UI"""
    
    # Header colors
    HEADER_BACKGROUND = Color.FromRgb(240, 204, 136)  # Yellow-orange #F0CC88
    HEADER_BORDER = Color.FromRgb(212, 165, 116)      # Darker orange
    HEADER_TEXT = Color.FromRgb(51, 51, 51)           # Dark gray
    HEADER_SUBTITLE = Color.FromRgb(102, 102, 102)    # Medium gray
    
    # Footer colors
    FOOTER_BACKGROUND = Color.FromRgb(240, 204, 136)  # Same as header
    FOOTER_BORDER = Color.FromRgb(212, 165, 116)
    FOOTER_COPYRIGHT = Color.FromRgb(80, 80, 80)      # Dark gray
    
    # DataGrid colors
    GRID_BACKGROUND = Color.FromRgb(255, 255, 255)    # White
    GRID_ALTERNATING = Color.FromRgb(250, 250, 250)   # Light gray
    GRID_BORDER = Color.FromRgb(221, 221, 221)        # Border gray
    GRID_HEADER_BG = Color.FromRgb(245, 245, 245)     # Header background
    
    # Button colors
    BTN_BATCH_RENAME = Color.FromRgb(76, 175, 80)     # Green
    BTN_EDIT_PROPS = Color.FromRgb(156, 39, 176)      # Purple
    BTN_RENAME = Color.FromRgb(33, 150, 243)          # Blue
    BTN_DUPLICATE = Color.FromRgb(255, 152, 0)        # Orange
    BTN_DELETE = Color.FromRgb(244, 67, 54)           # Red
    BTN_REFRESH = Color.FromRgb(96, 125, 139)         # Blue-gray
    BTN_CLOSE = Color.FromRgb(158, 158, 158)          # Gray
    BTN_APPLY = Color.FromRgb(76, 175, 80)            # Green
    BTN_CANCEL = Color.FromRgb(158, 158, 158)         # Gray
    
    # Dialog colors
    DIALOG_BACKGROUND = Color.FromRgb(248, 248, 248)  # Light gray


# ============================================================================
# SETTINGS
# ============================================================================

class Settings:
    """General settings for all manager tools"""
    
    # Window settings
    DEFAULT_WIDTH = 1000
    DEFAULT_HEIGHT = 720
    MIN_WIDTH = 800
    MIN_HEIGHT = 600
    
    # Grid settings
    ENABLE_SORTING = True
    ENABLE_MULTI_SELECT = True
    ALTERNATING_ROWS = True
    
    # Feature flags
    DEFAULT_HAS_BATCH_RENAME = True
    DEFAULT_HAS_EDIT_PROPERTIES = False
    DEFAULT_HAS_DUPLICATE = True
    DEFAULT_HAS_DELETE = True
    
    # Copyright
    COPYRIGHT_TEXT = u"\u00A9 2024 Dang Quoc Truong (DQT) | All Rights Reserved"
    AUTHOR = "Dang Quoc Truong (DQT)"
    AUTHOR_SHORT = "DQT"


# ============================================================================
# COLUMN CONFIGURATIONS
# ============================================================================

class ColumnConfig:
    """Standard column configurations"""
    
    # Standard columns present in all tools
    STANDARD_COLUMNS = [
        {'name': 'Select', 'width': 60, 'sortable': False, 'type': 'checkbox'},
        {'name': 'Name', 'width': 300, 'sortable': True, 'type': 'text'},
        {'name': 'Usage', 'width': 80, 'sortable': True, 'type': 'text'},
        {'name': 'Usage %', 'width': 80, 'sortable': True, 'type': 'text'},
        {'name': 'ID', 'width': 100, 'sortable': True, 'type': 'text'}
    ]


# ============================================================================
# PROPERTY TYPES FOR EDIT DIALOG
# ============================================================================

class PropertyType:
    """Property types for Edit Properties Dialog"""
    
    TEXTBOX = 'textbox'
    COMBOBOX = 'combobox'
    CHECKBOX = 'checkbox'
    MULTICATEGORY = 'multicategory'  # Special for Parameter Manager
    NUMBER = 'number'
    READONLY = 'readonly'


# ============================================================================
# INVALID CHARACTERS
# ============================================================================

class InvalidChars:
    """Invalid characters for Revit element names"""
    
    REVIT_NAME_INVALID = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
    
    @staticmethod
    def sanitize(name):
        """Remove invalid characters from name"""
        if not name:
            return name
        
        sanitized = name
        for char in InvalidChars.REVIT_NAME_INVALID:
            sanitized = sanitized.replace(char, '')
        
        return sanitized.strip() or "Unnamed"


# ============================================================================
# BUTTON CONFIGURATIONS
# ============================================================================

class ButtonConfig:
    """Standard button configurations"""
    
    BATCH_RENAME = {
        'text': 'Batch Rename',
        'width': 100,
        'color': Colors.BTN_BATCH_RENAME
    }
    
    EDIT_PROPERTIES = {
        'text': 'Edit Properties',
        'width': 110,
        'color': Colors.BTN_EDIT_PROPS
    }
    
    RENAME = {
        'text': 'Rename',
        'width': 80,
        'color': Colors.BTN_RENAME
    }
    
    DUPLICATE = {
        'text': 'Duplicate',
        'width': 80,
        'color': Colors.BTN_DUPLICATE
    }
    
    DELETE = {
        'text': 'Delete',
        'width': 80,
        'color': Colors.BTN_DELETE
    }
    
    REFRESH = {
        'text': 'Refresh',
        'width': 80,
        'color': Colors.BTN_REFRESH
    }
    
    CLOSE = {
        'text': 'Close',
        'width': 80,
        'color': Colors.BTN_CLOSE
    }