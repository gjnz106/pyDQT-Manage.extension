# -*- coding: utf-8 -*-
"""
Smart Purge v2.0 - Configuration
Color scheme and settings

Compatible with Revit 2024, 2025, 2026, 2027

Copyright (c) 2025 Dang Quoc Truong (DQT)
"""

__author__ = "Dang Quoc Truong (DQT)"


class Colors:
    """DQT Brand Color Scheme"""
    
    # Primary colors (DQT Branding)
    HEADER = "#F0CC88"           # Gold header background
    BACKGROUND = "#FEF8E7"       # Light cream background
    BORDER = "#D4B87A"           # Gold border
    ACCENT = "#5D4E37"           # Dark brown accent
    
    # Text colors
    TEXT_PRIMARY = "#333333"     # Dark text
    TEXT_SECONDARY = "#666666"   # Secondary text
    TEXT_LIGHT = "#999999"       # Light/muted text
    
    # Status colors
    HIGHLIGHT = "#FF6B35"        # Orange highlight for counts
    SUCCESS = "#4CAF50"          # Green for safe items
    WARNING = "#FFC107"          # Yellow/amber warning
    DANGER = "#F44336"           # Red danger
    
    # Button colors
    BUTTON_PRIMARY = "#FF6B35"   # Orange primary button
    BUTTON_SUCCESS = "#4CAF50"   # Green success button
    BUTTON_DANGER = "#F44336"    # Red danger button
    BUTTON_NEUTRAL = "#9E9E9E"   # Gray neutral button
    
    # Common colors
    White = "#FFFFFF"
    Black = "#000000"
    
    # Alias for backward compatibility
    PRIMARY = HEADER
    SECONDARY = BACKGROUND


class Fonts:
    """Font sizes for UI"""
    
    TITLE = 22
    SUBTITLE = 14
    HEADER = 14
    BODY = 13
    SMALL = 11
    TINY = 10


class Settings:
    """Application settings"""
    
    # Window dimensions
    WINDOW_WIDTH = 850
    WINDOW_HEIGHT = 950
    
    # Default settings
    DEFAULT_DRY_RUN = True
    DEFAULT_DELETE_SYSTEM = False
    
    # Application info
    APP_NAME = "Smart Purge"
    APP_VERSION = "2.0.1"
    AUTHOR = "Dang Quoc Truong (DQT)"
    COPYRIGHT = "Copyright (c) 2025 Dang Quoc Truong (DQT)"
