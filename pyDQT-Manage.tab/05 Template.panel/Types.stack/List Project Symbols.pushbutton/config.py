# -*- coding: utf-8 -*-
"""Shift-click config for List Project Symbols."""

import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here not in _sys.path:
    _sys.path.insert(0, _here)

import listsymbolsconfig

listsymbolsconfig.config_categories()
