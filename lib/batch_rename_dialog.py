# -*- coding: utf-8 -*-
"""
Batch Rename Dialog for DQT Tools
Version: FIXED - Proper sanitization and rename method

Copyright (c) 2025 Copyright by Dang Quoc Truong (DQT)
All rights reserved.

Author: DQT

FEATURES:
1. Prefix/Suffix Tab
2. Find/Replace Tab  
3. Type/Segments Tab (for patterns with type/segments info)
4. Custom Position Tab
"""

from System.Windows import (
    Window, MessageBox, MessageBoxButton, MessageBoxImage,
    Thickness, HorizontalAlignment, VerticalAlignment, WindowStartupLocation
)
from System.Windows.Controls import (
    Grid, StackPanel, TextBox, Button, Label,
    RadioButton, CheckBox, Separator, GroupBox, TabControl, TabItem,
    RowDefinition, ColumnDefinition, Orientation, TextBlock, WrapPanel
)
from System.Windows.Media import SolidColorBrush, Color, Brushes
from System import EventHandler, Windows
import re


def sanitize_revit_name(name):
    """Sanitize name by removing invalid Revit characters
    
    Note: Brackets [] and parentheses () are ALLOWED in Revit element names!
    Only remove the truly invalid characters.
    """
    if not name:
        return name
    
    # Remove ONLY the invalid characters for Revit element names
    # Brackets [] and Parentheses () are VALID!
    invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
    
    sanitized = name
    for char in invalid_chars:
        sanitized = sanitized.replace(char, '')
    
    # Trim whitespace
    sanitized = sanitized.strip()
    
    # Ensure not empty
    if not sanitized:
        sanitized = "Unnamed"
    
    return sanitized


class BatchRenameDialog(Window):
    """Dialog for batch renaming elements with 4 modes"""
    
    def __init__(self, doc, selected_items, parent):
        """Initialize batch rename dialog"""
        self.doc = doc
        self.parent = parent
        self.selected_items = selected_items
        self.result = None
        
        # Window properties
        self.Title = "Batch Rename - {} items selected".format(len(selected_items))
        self.Width = 700
        self.Height = 750
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = Windows.ResizeMode.CanResize
        
        # Create UI
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the dialog UI"""
        main_grid = Grid()
        main_grid.Margin = Thickness(10)
        
        # Define rows
        main_grid.RowDefinitions.Add(RowDefinition())
        main_grid.RowDefinitions.Add(RowDefinition())
        main_grid.RowDefinitions.Add(RowDefinition())
        main_grid.RowDefinitions.Add(RowDefinition())
        
        main_grid.RowDefinitions[0].Height = Windows.GridLength(40)
        main_grid.RowDefinitions[1].Height = Windows.GridLength(1, Windows.GridUnitType.Star)
        main_grid.RowDefinitions[2].Height = Windows.GridLength(150)
        main_grid.RowDefinitions[3].Height = Windows.GridLength(50)
        
        # Title
        title = Label()
        title.Content = "Batch Rename - {} items selected".format(len(self.selected_items))
        title.FontSize = 16
        title.FontWeight = Windows.FontWeights.Bold
        title.HorizontalAlignment = HorizontalAlignment.Center
        Grid.SetRow(title, 0)
        main_grid.Children.Add(title)
        
        # Tab control
        self.tab_control = TabControl()
        self.tab_control.Margin = Thickness(0, 5, 0, 5)
        Grid.SetRow(self.tab_control, 1)
        
        # Create tabs
        self.create_prefix_suffix_tab()
        self.create_find_replace_tab()
        self.create_type_segments_tab()
        self.create_custom_position_tab()
        
        main_grid.Children.Add(self.tab_control)
        
        # Preview section
        preview_group = self.create_preview_section()
        Grid.SetRow(preview_group, 2)
        main_grid.Children.Add(preview_group)
        
        # Buttons
        buttons_panel = self.create_buttons_panel()
        Grid.SetRow(buttons_panel, 3)
        main_grid.Children.Add(buttons_panel)
        
        self.Content = main_grid
        
        # Update preview initially
        self.update_preview()
        
    def create_prefix_suffix_tab(self):
        """Create Prefix/Suffix tab"""
        tab = TabItem()
        tab.Header = "Prefix/Suffix"
        
        stack = StackPanel()
        stack.Margin = Thickness(10)
        
        # Instruction
        instruction = Label()
        instruction.Content = "Add prefix and/or suffix to selected items:"
        instruction.FontWeight = Windows.FontWeights.Bold
        instruction.Margin = Thickness(0, 0, 0, 10)
        stack.Children.Add(instruction)
        
        # Prefix
        prefix_label = Label()
        prefix_label.Content = "Prefix:"
        stack.Children.Add(prefix_label)
        
        self.prefix_textbox = TextBox()
        self.prefix_textbox.Height = 25
        self.prefix_textbox.Margin = Thickness(0, 0, 0, 10)
        self.prefix_textbox.TextChanged += self.on_text_changed
        stack.Children.Add(self.prefix_textbox)
        
        # Suffix
        suffix_label = Label()
        suffix_label.Content = "Suffix:"
        stack.Children.Add(suffix_label)
        
        self.suffix_textbox = TextBox()
        self.suffix_textbox.Height = 25
        self.suffix_textbox.Margin = Thickness(0, 0, 0, 10)
        self.suffix_textbox.TextChanged += self.on_text_changed
        stack.Children.Add(self.suffix_textbox)
        
        tab.Content = stack
        self.tab_control.Items.Add(tab)
        
    def create_find_replace_tab(self):
        """Create Find/Replace tab"""
        tab = TabItem()
        tab.Header = "Find/Replace"
        
        stack = StackPanel()
        stack.Margin = Thickness(10)
        
        # Instruction
        instruction = Label()
        instruction.Content = "Find and replace text in item names:"
        instruction.FontWeight = Windows.FontWeights.Bold
        instruction.Margin = Thickness(0, 0, 0, 10)
        stack.Children.Add(instruction)
        
        # Find
        find_label = Label()
        find_label.Content = "Find:"
        stack.Children.Add(find_label)
        
        self.find_textbox = TextBox()
        self.find_textbox.Height = 25
        self.find_textbox.Margin = Thickness(0, 0, 0, 10)
        self.find_textbox.TextChanged += self.on_text_changed
        stack.Children.Add(self.find_textbox)
        
        # Replace
        replace_label = Label()
        replace_label.Content = "Replace with:"
        stack.Children.Add(replace_label)
        
        self.replace_textbox = TextBox()
        self.replace_textbox.Height = 25
        self.replace_textbox.Margin = Thickness(0, 0, 0, 10)
        self.replace_textbox.TextChanged += self.on_text_changed
        stack.Children.Add(self.replace_textbox)
        
        # Case sensitive
        self.case_check = CheckBox()
        self.case_check.Content = "Case sensitive"
        self.case_check.Margin = Thickness(0, 0, 0, 5)
        self.case_check.Checked += self.on_text_changed
        self.case_check.Unchecked += self.on_text_changed
        stack.Children.Add(self.case_check)
        
        # Whole word
        self.whole_word_check = CheckBox()
        self.whole_word_check.Content = "Match whole word only"
        self.whole_word_check.Checked += self.on_text_changed
        self.whole_word_check.Unchecked += self.on_text_changed
        stack.Children.Add(self.whole_word_check)
        
        tab.Content = stack
        self.tab_control.Items.Add(tab)
        
    def create_type_segments_tab(self):
        """Create Type/Segments tab for adding text type/size info"""
        tab = TabItem()
        tab.Header = "Type/Segments"
        
        scroll = Windows.Controls.ScrollViewer()
        scroll.VerticalScrollBarVisibility = Windows.Controls.ScrollBarVisibility.Auto
        
        stack = StackPanel()
        stack.Margin = Thickness(10)
        
        # Instruction
        instruction = Label()
        instruction.Content = "Add Type and/or Size information to selected items:"
        instruction.FontWeight = Windows.FontWeights.Bold
        instruction.Margin = Thickness(0, 0, 0, 10)
        stack.Children.Add(instruction)
        
        # Remove current name option
        self.remove_name_check = CheckBox()
        self.remove_name_check.Content = "Remove Current Name"
        self.remove_name_check.Margin = Thickness(0, 0, 0, 5)
        self.remove_name_check.Checked += self.on_text_changed
        self.remove_name_check.Unchecked += self.on_text_changed
        stack.Children.Add(self.remove_name_check)
        
        help_label = Label()
        help_label.Content = "(Create new name using only Type/Size information)"
        help_label.Foreground = Brushes.Gray
        help_label.FontSize = 10
        help_label.Margin = Thickness(20, 0, 0, 10)
        stack.Children.Add(help_label)
        
        # Add Type section
        type_header = Label()
        type_header.Content = "Add Type:"
        type_header.FontWeight = Windows.FontWeights.Bold
        type_header.Margin = Thickness(0, 5, 0, 5)
        stack.Children.Add(type_header)
        
        type_panel = WrapPanel()
        type_panel.Margin = Thickness(20, 0, 0, 0)
        
        self.type_none_radio = RadioButton()
        self.type_none_radio.Content = "None"
        self.type_none_radio.GroupName = "TypeGroup"
        self.type_none_radio.IsChecked = True
        self.type_none_radio.Margin = Thickness(0, 0, 20, 5)
        self.type_none_radio.Checked += self.on_text_changed
        type_panel.Children.Add(self.type_none_radio)
        
        self.type_prefix_radio = RadioButton()
        self.type_prefix_radio.Content = "As Prefix"
        self.type_prefix_radio.GroupName = "TypeGroup"
        self.type_prefix_radio.Margin = Thickness(0, 0, 20, 5)
        self.type_prefix_radio.Checked += self.on_text_changed
        type_panel.Children.Add(self.type_prefix_radio)
        
        self.type_suffix_radio = RadioButton()
        self.type_suffix_radio.Content = "As Suffix"
        self.type_suffix_radio.GroupName = "TypeGroup"
        self.type_suffix_radio.Margin = Thickness(0, 0, 20, 5)
        self.type_suffix_radio.Checked += self.on_text_changed
        type_panel.Children.Add(self.type_suffix_radio)
        
        stack.Children.Add(type_panel)
        
        # Type format
        type_format_label = Label()
        type_format_label.Content = "Type Format:"
        type_format_label.Margin = Thickness(20, 5, 0, 5)
        stack.Children.Add(type_format_label)
        
        type_format_panel = WrapPanel()
        type_format_panel.Margin = Thickness(40, 0, 0, 10)
        
        self.type_brackets_check = CheckBox()
        self.type_brackets_check.Content = "Use dashes -- (Revit-safe)"
        self.type_brackets_check.IsChecked = True
        self.type_brackets_check.Margin = Thickness(0, 0, 20, 0)
        self.type_brackets_check.Checked += self.on_text_changed
        self.type_brackets_check.Unchecked += self.on_text_changed
        type_format_panel.Children.Add(self.type_brackets_check)
        
        self.type_parentheses_check = CheckBox()
        self.type_parentheses_check.Content = "Use parentheses ()"
        self.type_parentheses_check.Margin = Thickness(0, 0, 20, 0)
        self.type_parentheses_check.Checked += self.on_text_changed
        self.type_parentheses_check.Unchecked += self.on_text_changed
        type_format_panel.Children.Add(self.type_parentheses_check)
        
        stack.Children.Add(type_format_panel)
        
        # Add Size section
        size_header = Label()
        size_header.Content = "Add Size:"
        size_header.FontWeight = Windows.FontWeights.Bold
        size_header.Margin = Thickness(0, 10, 0, 5)
        stack.Children.Add(size_header)
        
        size_panel = WrapPanel()
        size_panel.Margin = Thickness(20, 0, 0, 0)
        
        self.size_none_radio = RadioButton()
        self.size_none_radio.Content = "None"
        self.size_none_radio.GroupName = "SizeGroup"
        self.size_none_radio.IsChecked = True
        self.size_none_radio.Margin = Thickness(0, 0, 20, 5)
        self.size_none_radio.Checked += self.on_text_changed
        size_panel.Children.Add(self.size_none_radio)
        
        self.size_prefix_radio = RadioButton()
        self.size_prefix_radio.Content = "As Prefix"
        self.size_prefix_radio.GroupName = "SizeGroup"
        self.size_prefix_radio.Margin = Thickness(0, 0, 20, 5)
        self.size_prefix_radio.Checked += self.on_text_changed
        size_panel.Children.Add(self.size_prefix_radio)
        
        self.size_suffix_radio = RadioButton()
        self.size_suffix_radio.Content = "As Suffix"
        self.size_suffix_radio.GroupName = "SizeGroup"
        self.size_suffix_radio.Margin = Thickness(0, 0, 20, 5)
        self.size_suffix_radio.Checked += self.on_text_changed
        size_panel.Children.Add(self.size_suffix_radio)
        
        stack.Children.Add(size_panel)
        
        # Size format
        size_format_label = Label()
        size_format_label.Content = "Size Format:"
        size_format_label.Margin = Thickness(20, 5, 0, 5)
        stack.Children.Add(size_format_label)
        
        size_format_panel = WrapPanel()
        size_format_panel.Margin = Thickness(40, 0, 0, 10)
        
        self.size_brackets_check = CheckBox()
        self.size_brackets_check.Content = "Use dashes -- (Revit-safe)"
        self.size_brackets_check.IsChecked = True
        self.size_brackets_check.Margin = Thickness(0, 0, 20, 0)
        self.size_brackets_check.Checked += self.on_text_changed
        self.size_brackets_check.Unchecked += self.on_text_changed
        size_format_panel.Children.Add(self.size_brackets_check)
        
        self.size_parentheses_check = CheckBox()
        self.size_parentheses_check.Content = "Use parentheses ()"
        self.size_parentheses_check.Margin = Thickness(0, 0, 20, 0)
        self.size_parentheses_check.Checked += self.on_text_changed
        self.size_parentheses_check.Unchecked += self.on_text_changed
        size_format_panel.Children.Add(self.size_parentheses_check)
        
        stack.Children.Add(size_format_panel)
        
        # Add Segments section (NEW for Line Patterns)
        segments_header = Label()
        segments_header.Content = "Add Segments (Line Patterns only):"
        segments_header.FontWeight = Windows.FontWeights.Bold
        segments_header.Margin = Thickness(0, 15, 0, 5)
        stack.Children.Add(segments_header)
        
        segments_panel = WrapPanel()
        segments_panel.Margin = Thickness(20, 0, 0, 0)
        
        self.segments_none_radio = RadioButton()
        self.segments_none_radio.Content = "None"
        self.segments_none_radio.GroupName = "SegmentsGroup"
        self.segments_none_radio.IsChecked = True
        self.segments_none_radio.Margin = Thickness(0, 0, 20, 5)
        self.segments_none_radio.Checked += self.on_text_changed
        segments_panel.Children.Add(self.segments_none_radio)
        
        self.segments_prefix_radio = RadioButton()
        self.segments_prefix_radio.Content = "As Prefix"
        self.segments_prefix_radio.GroupName = "SegmentsGroup"
        self.segments_prefix_radio.Margin = Thickness(0, 0, 20, 5)
        self.segments_prefix_radio.Checked += self.on_text_changed
        segments_panel.Children.Add(self.segments_prefix_radio)
        
        self.segments_suffix_radio = RadioButton()
        self.segments_suffix_radio.Content = "As Suffix"
        self.segments_suffix_radio.GroupName = "SegmentsGroup"
        self.segments_suffix_radio.Margin = Thickness(0, 0, 20, 5)
        self.segments_suffix_radio.Checked += self.on_text_changed
        segments_panel.Children.Add(self.segments_suffix_radio)
        
        stack.Children.Add(segments_panel)
        
        # Segments format
        segments_format_label = Label()
        segments_format_label.Content = "Segments Format:"
        segments_format_label.Margin = Thickness(20, 5, 0, 5)
        stack.Children.Add(segments_format_label)
        
        segments_format_panel = WrapPanel()
        segments_format_panel.Margin = Thickness(40, 0, 0, 10)
        
        self.segments_brackets_check = CheckBox()
        self.segments_brackets_check.Content = "Use brackets []"
        self.segments_brackets_check.Margin = Thickness(0, 0, 20, 0)
        self.segments_brackets_check.Checked += self.on_text_changed
        self.segments_brackets_check.Unchecked += self.on_text_changed
        segments_format_panel.Children.Add(self.segments_brackets_check)
        
        self.segments_parentheses_check = CheckBox()
        self.segments_parentheses_check.Content = "Use parentheses ()"
        self.segments_parentheses_check.IsChecked = True
        self.segments_parentheses_check.Margin = Thickness(0, 0, 20, 0)
        self.segments_parentheses_check.Checked += self.on_text_changed
        self.segments_parentheses_check.Unchecked += self.on_text_changed
        segments_format_panel.Children.Add(self.segments_parentheses_check)
        
        stack.Children.Add(segments_format_panel)
        
        # Separator
        sep_label = Label()
        sep_label.Content = "Separator between name and added info:"
        sep_label.FontWeight = Windows.FontWeights.Bold
        sep_label.Margin = Thickness(0, 10, 0, 5)
        stack.Children.Add(sep_label)
        
        sep_panel = StackPanel()
        sep_panel.Orientation = Orientation.Horizontal
        sep_panel.Margin = Thickness(20, 0, 0, 0)
        
        self.separator_textbox = TextBox()
        self.separator_textbox.Width = 100
        self.separator_textbox.Height = 25
        self.separator_textbox.Text = " "
        self.separator_textbox.TextChanged += self.on_text_changed
        sep_panel.Children.Add(self.separator_textbox)
        
        sep_help = Label()
        sep_help.Content = "(default: space)"
        sep_help.Foreground = Brushes.Gray
        sep_help.Margin = Thickness(10, 0, 0, 0)
        sep_help.VerticalAlignment = VerticalAlignment.Center
        sep_panel.Children.Add(sep_help)
        
        stack.Children.Add(sep_panel)
        
        scroll.Content = stack
        tab.Content = scroll
        self.tab_control.Items.Add(tab)
        
    def create_custom_position_tab(self):
        """Create Custom Position tab"""
        tab = TabItem()
        tab.Header = "Custom Position"
        
        stack = StackPanel()
        stack.Margin = Thickness(10)
        
        # Instruction
        instruction = Label()
        instruction.Content = "Insert custom text at any position in the item names:"
        instruction.FontWeight = Windows.FontWeights.Bold
        instruction.Margin = Thickness(0, 0, 0, 10)
        stack.Children.Add(instruction)
        
        # Text to insert
        text_label = Label()
        text_label.Content = "Text to insert:"
        stack.Children.Add(text_label)
        
        self.custom_textbox = TextBox()
        self.custom_textbox.Height = 25
        self.custom_textbox.Margin = Thickness(0, 0, 0, 15)
        self.custom_textbox.TextChanged += self.on_text_changed
        stack.Children.Add(self.custom_textbox)
        
        # Insert position
        position_label = Label()
        position_label.Content = "Insert at position:"
        position_label.FontWeight = Windows.FontWeights.Bold
        stack.Children.Add(position_label)
        
        # Radio buttons for position
        self.pos_start_radio = RadioButton()
        self.pos_start_radio.Content = "At start (prefix)"
        self.pos_start_radio.GroupName = "PositionGroup"
        self.pos_start_radio.IsChecked = True
        self.pos_start_radio.Margin = Thickness(0, 5, 0, 5)
        self.pos_start_radio.Checked += self.on_text_changed
        stack.Children.Add(self.pos_start_radio)
        
        self.pos_end_radio = RadioButton()
        self.pos_end_radio.Content = "At end (suffix)"
        self.pos_end_radio.GroupName = "PositionGroup"
        self.pos_end_radio.Margin = Thickness(0, 0, 0, 5)
        self.pos_end_radio.Checked += self.on_text_changed
        stack.Children.Add(self.pos_end_radio)
        
        # Custom position
        custom_pos_panel = StackPanel()
        custom_pos_panel.Orientation = Orientation.Horizontal
        custom_pos_panel.Margin = Thickness(0, 0, 0, 5)
        
        self.pos_custom_radio = RadioButton()
        self.pos_custom_radio.Content = "At specific position:"
        self.pos_custom_radio.GroupName = "PositionGroup"
        self.pos_custom_radio.VerticalAlignment = VerticalAlignment.Center
        self.pos_custom_radio.Checked += self.on_text_changed
        custom_pos_panel.Children.Add(self.pos_custom_radio)
        
        self.position_textbox = TextBox()
        self.position_textbox.Width = 60
        self.position_textbox.Height = 25
        self.position_textbox.Margin = Thickness(10, 0, 10, 0)
        self.position_textbox.Text = "0"
        self.position_textbox.TextChanged += self.on_text_changed
        custom_pos_panel.Children.Add(self.position_textbox)
        
        pos_help = Label()
        pos_help.Content = "(0=start, -1=end, or specific index)"
        pos_help.Foreground = Brushes.Gray
        pos_help.VerticalAlignment = VerticalAlignment.Center
        custom_pos_panel.Children.Add(pos_help)
        
        stack.Children.Add(custom_pos_panel)
        
        # After text option
        after_panel = StackPanel()
        after_panel.Orientation = Orientation.Horizontal
        after_panel.Margin = Thickness(0, 5, 0, 0)
        
        self.pos_after_radio = RadioButton()
        self.pos_after_radio.Content = "After text:"
        self.pos_after_radio.GroupName = "PositionGroup"
        self.pos_after_radio.VerticalAlignment = VerticalAlignment.Center
        self.pos_after_radio.Checked += self.on_text_changed
        after_panel.Children.Add(self.pos_after_radio)
        
        self.after_text_textbox = TextBox()
        self.after_text_textbox.Width = 150
        self.after_text_textbox.Height = 25
        self.after_text_textbox.Margin = Thickness(10, 0, 10, 0)
        self.after_text_textbox.TextChanged += self.on_text_changed
        after_panel.Children.Add(self.after_text_textbox)
        
        # After/Before checkbox
        self.insert_after_check = CheckBox()
        self.insert_after_check.Content = "After"
        self.insert_after_check.IsChecked = True
        self.insert_after_check.Margin = Thickness(0, 0, 10, 0)
        self.insert_after_check.Checked += self.on_text_changed
        self.insert_after_check.Unchecked += self.on_text_changed
        after_panel.Children.Add(self.insert_after_check)
        
        self.insert_before_check = CheckBox()
        self.insert_before_check.Content = "Before"
        self.insert_before_check.Checked += self.on_text_changed
        self.insert_before_check.Unchecked += self.on_text_changed
        after_panel.Children.Add(self.insert_before_check)
        
        stack.Children.Add(after_panel)
        
        tab.Content = stack
        self.tab_control.Items.Add(tab)
        
    def create_preview_section(self):
        """Create preview section"""
        group = GroupBox()
        group.Header = "Preview:"
        group.Margin = Thickness(0, 5, 0, 5)
        
        scroll = Windows.Controls.ScrollViewer()
        scroll.VerticalScrollBarVisibility = Windows.Controls.ScrollBarVisibility.Auto
        
        self.preview_textblock = TextBlock()
        self.preview_textblock.Margin = Thickness(5)
        self.preview_textblock.FontFamily = Windows.Media.FontFamily("Consolas")
        self.preview_textblock.Text = "No changes - enter text to see preview"
        
        scroll.Content = self.preview_textblock
        group.Content = scroll
        
        return group
        
    def create_buttons_panel(self):
        """Create buttons panel"""
        panel = StackPanel()
        panel.Orientation = Orientation.Horizontal
        panel.HorizontalAlignment = HorizontalAlignment.Right
        panel.VerticalAlignment = VerticalAlignment.Center
        
        # Apply Rename button
        btn_apply = Button()
        btn_apply.Content = "Apply Rename"
        btn_apply.Width = 120
        btn_apply.Height = 30
        btn_apply.Margin = Thickness(0, 0, 10, 0)
        btn_apply.Background = SolidColorBrush(Color.FromRgb(240, 204, 136))
        btn_apply.Click += self.on_apply
        panel.Children.Add(btn_apply)
        
        # Cancel button
        btn_cancel = Button()
        btn_cancel.Content = "Cancel"
        btn_cancel.Width = 100
        btn_cancel.Height = 30
        btn_cancel.Click += self.on_cancel
        panel.Children.Add(btn_cancel)
        
        return panel
        
    def on_text_changed(self, sender, e):
        """Handle text change to update preview"""
        self.update_preview()
        
    def get_type_info(self, item):
        """Extract type information - universal for all element types"""
        try:
            # Get actual element
            elem = item.Element if hasattr(item, 'Element') else item
            elem_type = elem.GetType().Name
            
            # FillPatternElement - get pattern type (Drafting/Model)
            if elem_type == "FillPatternElement":
                try:
                    from Autodesk.Revit.DB import FillPatternTarget
                    fill_pattern = elem.GetFillPattern()
                    if fill_pattern:
                        target = fill_pattern.Target
                        if target == FillPatternTarget.Drafting:
                            return "Drafting"
                        elif target == FillPatternTarget.Model:
                            return "Model"
                    return "Pattern"
                except:
                    return "Pattern"
            
            # TextNoteType - get font name
            elif elem_type == "TextNoteType":
                try:
                    from Autodesk.Revit.DB import BuiltInParameter
                    font_param = elem.get_Parameter(BuiltInParameter.TEXT_FONT)
                    if font_param and font_param.HasValue:
                        font_name = font_param.AsString()
                        if font_name:
                            return font_name
                except:
                    pass
                return "TextNote"
            
            # Material - get material class
            elif elem_type == "Material":
                try:
                    material_class = elem.MaterialClass
                    if material_class:
                        return material_class
                except:
                    pass
                return "Material"
            
            # LinePatternElement - return pattern type (System/Custom)
            elif elem_type == "LinePatternElement":
                try:
                    # Item might be wrapper (LinePatternItem) or direct element
                    # Try wrapper properties first
                    if hasattr(item, 'PatternType'):
                        pattern_type = item.PatternType
                        print("    DEBUG: Got PatternType from wrapper: {}".format(pattern_type))
                        return pattern_type  # "System" or "Custom"
                    
                    if hasattr(item, 'IsSystem'):
                        is_system = item.IsSystem
                        print("    DEBUG: Got IsSystem from wrapper: {}".format(is_system))
                        return "System" if is_system else "Custom"
                    
                    # Direct element - check if system pattern by name
                    elem_name = elem.Name if hasattr(elem, 'Name') else None
                    if elem_name:
                        system_names = ["Solid", "Dash", "Dot", "Dash dot", 
                                      "Dash dot dot", "Hidden", "Center", "Phantom"]
                        is_system = elem_name in system_names
                        print("    DEBUG: Checked element name '{}': System={}".format(elem_name, is_system))
                        return "System" if is_system else "Custom"
                except Exception as ex:
                    print("    DEBUG: Error getting LinePattern type: {}".format(str(ex)))
                    pass
                return "Line"
            
            # DimensionType - get dimension type
            elif elem_type == "DimensionType":
                try:
                    style_type = elem.StyleType
                    return str(style_type)
                except:
                    pass
                return "Dimension"
            
            # Default - use element type name
            return elem_type.replace("Element", "").replace("Type", "")
            
        except Exception as ex:
            print("Error getting type info: {}".format(str(ex)))
            return "Unknown"
        
    def get_size_info(self, item):
        """Extract size/scale information - universal for all element types"""
        try:
            # Get actual element
            elem = item.Element if hasattr(item, 'Element') else item
            elem_type = elem.GetType().Name
            
            # FillPatternElement - get scale or usage count
            if elem_type == "FillPatternElement":
                try:
                    # Try to get usage count if item has it
                    if hasattr(item, 'UsageCount'):
                        usage = item.UsageCount
                        if usage > 0:
                            return "{} use{}".format(usage, "s" if usage != 1 else "")
                    
                    # Fallback - just return element ID for uniqueness
                    return "ID:{}".format(elem.Id.IntegerValue)
                except:
                    return None
            
            # TextNoteType - get text size
            elif elem_type == "TextNoteType":
                try:
                    from Autodesk.Revit.DB import BuiltInParameter, UnitUtils
                    
                    size_param = elem.get_Parameter(BuiltInParameter.TEXT_SIZE)
                    if size_param and size_param.HasValue:
                        size_str = size_param.AsValueString()
                        if size_str:
                            return size_str
                        
                        size_double = size_param.AsDouble()
                        if size_double and size_double > 0:
                            try:
                                from Autodesk.Revit.DB import UnitTypeId
                                size_mm = UnitUtils.ConvertFromInternalUnits(size_double, UnitTypeId.Millimeters)
                                return "{:.2f}mm".format(size_mm)
                            except:
                                from Autodesk.Revit.DB import DisplayUnitType
                                size_mm = UnitUtils.ConvertFromInternalUnits(size_double, DisplayUnitType.DUT_MILLIMETERS)
                                return "{:.2f}mm".format(size_mm)
                except:
                    pass
                
                # Try SYMBOL_SIZE_PARAM
                try:
                    size_param = elem.get_Parameter(BuiltInParameter.SYMBOL_SIZE_PARAM)
                    if size_param and size_param.HasValue:
                        size_str = size_param.AsValueString()
                        if size_str:
                            return size_str
                except:
                    pass
            
            # Material - get usage count or appearance
            elif elem_type == "Material":
                try:
                    if hasattr(item, 'UsageCount'):
                        usage = item.UsageCount
                        if usage > 0:
                            return "{} use{}".format(usage, "s" if usage != 1 else "")
                except:
                    pass
                return None
            
            # LinePatternElement - get segment pattern or usage
            elif elem_type == "LinePatternElement":
                try:
                    # Item might be wrapper or direct element
                    # Try wrapper property first
                    if hasattr(item, 'SegmentPattern'):
                        segment_pattern = item.SegmentPattern
                        print("    DEBUG: Got SegmentPattern from wrapper: {}".format(segment_pattern))
                        if segment_pattern and segment_pattern != "Unknown":
                            return segment_pattern
                    
                    # Try to get pattern directly from element
                    try:
                        pattern = elem.GetLinePattern()
                        if pattern:
                            segments = pattern.GetSegments()
                            if segments:
                                segment_list = []
                                for seg in segments:
                                    seg_type = "Dash" if "Dash" in str(seg.Type) else "Dot" if "Dot" in str(seg.Type) else "Space"
                                    seg_length = seg.Length
                                    segment_list.append("{}({:.3f})".format(seg_type, seg_length))
                                
                                segment_pattern = ", ".join(segment_list)
                                print("    DEBUG: Built SegmentPattern from element: {}".format(segment_pattern))
                                return segment_pattern
                    except Exception as ex:
                        print("    DEBUG: Error getting pattern from element: {}".format(str(ex)))
                    
                    # Fallback to usage count
                    if hasattr(item, 'UsageCount'):
                        usage = item.UsageCount
                        if usage > 0:
                            return "{} use{}".format(usage, "s" if usage != 1 else "")
                except Exception as ex:
                    print("    DEBUG: Error in LinePattern get_size_info: {}".format(str(ex)))
                    pass
                return None
            
            # DimensionType - get usage or style
            elif elem_type == "DimensionType":
                try:
                    if hasattr(item, 'UsageCount'):
                        usage = item.UsageCount
                        if usage > 0:
                            return "{} use{}".format(usage, "s" if usage != 1 else "")
                except:
                    pass
                return None
            
            return None
            
        except Exception as ex:
            print("Error getting size info: {}".format(str(ex)))
            return None
        except Exception as ex:
            print("Error getting size info: {}".format(str(ex)))
            return None
        
    
    def get_segment_info(self, item):
        """Extract segment pattern information - for Line Patterns only"""
        try:
            # Get actual element
            elem = item.Element if hasattr(item, 'Element') else item
            elem_type = elem.GetType().Name
            
            # Only for LinePatternElement
            if elem_type != "LinePatternElement":
                return None
            
            # Try wrapper property first
            if hasattr(item, 'SegmentPattern'):
                segment_pattern = item.SegmentPattern
                print("    DEBUG (Segments): Got from wrapper: {}".format(segment_pattern))
                if segment_pattern and segment_pattern != "Unknown" and segment_pattern != "Solid":
                    return segment_pattern
            
            # Try to build from element directly
            try:
                pattern = elem.GetLinePattern()
                if pattern:
                    segments = pattern.GetSegments()
                    if segments and len(list(segments)) > 0:
                        segment_list = []
                        for seg in segments:
                            seg_type = "Dash" if "Dash" in str(seg.Type) else "Dot" if "Dot" in str(seg.Type) else "Space"
                            seg_length = seg.Length
                            segment_list.append("{}({:.3f})".format(seg_type, seg_length))
                        
                        if segment_list:
                            segment_pattern = ", ".join(segment_list)
                            print("    DEBUG (Segments): Built from element: {}".format(segment_pattern))
                            return segment_pattern
            except Exception as ex:
                print("    DEBUG (Segments): Error getting from element: {}".format(str(ex)))
            
            return None
            
        except Exception as ex:
            print("    DEBUG (Segments): Error: {}".format(str(ex)))
            return None
    
    def format_info(self, info, use_brackets, use_parentheses):
        """Format info with dashes or parentheses (Revit-safe)"""
        # Note: Brackets [] are invalid in Revit names, use dashes -- instead
        if use_brackets and use_parentheses:
            return "--({})--".format(info)
        elif use_brackets:
            return "--{}--".format(info)
        elif use_parentheses:
            return "({})".format(info)
        else:
            return info
        
    def update_preview(self):
        """Update the preview showing 3 examples of renamed items"""
        try:
            preview_lines = []
            
            # Show only first 3 items as examples
            preview_items = self.selected_items[:3]
            
            for idx, item in enumerate(preview_items, 1):
                # Get old name - universal approach
                old_name = None
                try:
                    # Try .Name first
                    if hasattr(item, 'Element'):
                        old_name = item.Element.Name
                    else:
                        old_name = item.Name
                except:
                    # Fallback to SYMBOL_NAME_PARAM
                    try:
                        elem = item.Element if hasattr(item, 'Element') else item
                        from Autodesk.Revit.DB import BuiltInParameter
                        name_param = elem.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                        if name_param:
                            old_name = name_param.AsString()
                    except:
                        pass
                
                if not old_name:
                    old_name = "Unknown"
                
                # Apply rename rules
                new_name = self.apply_rename_rules(item, old_name)
                
                # Format with example number
                if new_name != old_name:
                    preview_lines.append("Example {}:\n  Before: {}\n  After:  {}".format(
                        idx, old_name, new_name))
                else:
                    preview_lines.append("Example {}:\n  {}  (no change)".format(idx, old_name))
            
            # Show total count
            total_items = len(self.selected_items)
            if total_items > 3:
                preview_lines.append("\n... and {} more item{} will be renamed".format(
                    total_items - 3,
                    "s" if total_items - 3 > 1 else ""
                ))
            
            if preview_lines:
                self.preview_textblock.Text = "\n\n".join(preview_lines)
            else:
                self.preview_textblock.Text = "No changes - enter text to see preview"
                
        except Exception as ex:
            self.preview_textblock.Text = "Error generating preview: {}".format(str(ex))
            
    def apply_rename_rules(self, item, old_name):
        """Apply rename rules based on selected tab"""
        new_name = old_name
        
        selected_tab = self.tab_control.SelectedIndex
        
        if selected_tab == 0:  # Prefix/Suffix
            prefix = self.prefix_textbox.Text or ""
            suffix = self.suffix_textbox.Text or ""
            new_name = "{}{}{}".format(prefix, old_name, suffix)
            
        elif selected_tab == 1:  # Find/Replace
            find_text = self.find_textbox.Text
            replace_text = self.replace_textbox.Text or ""
            
            if find_text:
                case_sensitive = self.case_check.IsChecked == True
                whole_word = self.whole_word_check.IsChecked == True
                
                if whole_word:
                    if case_sensitive:
                        pattern = r'\b' + re.escape(find_text) + r'\b'
                        new_name = re.sub(pattern, replace_text, old_name)
                    else:
                        pattern = r'\b' + re.escape(find_text) + r'\b'
                        new_name = re.sub(pattern, replace_text, old_name, flags=re.IGNORECASE)
                else:
                    if case_sensitive:
                        new_name = old_name.replace(find_text, replace_text)
                    else:
                        pattern = re.compile(re.escape(find_text), re.IGNORECASE)
                        new_name = pattern.sub(replace_text, old_name)
                        
        elif selected_tab == 2:  # Type/Segments
            type_info = self.get_type_info(item)
            size_info = self.get_size_info(item)
            
            # Debug logging
            print("  Type/Segments mode:")
            print("    Type info: {}".format(type_info))
            print("    Size info: {}".format(size_info))
            print("    Type prefix radio: {}".format(self.type_prefix_radio.IsChecked))
            print("    Type suffix radio: {}".format(self.type_suffix_radio.IsChecked))
            print("    Size prefix radio: {}".format(self.size_prefix_radio.IsChecked))
            print("    Size suffix radio: {}".format(self.size_suffix_radio.IsChecked))
            
            if self.remove_name_check.IsChecked == True:
                base_name = ""
            else:
                base_name = old_name
            
            separator = self.separator_textbox.Text or " "
            
            parts = []
            
            if self.type_prefix_radio.IsChecked == True and type_info:
                formatted_type = self.format_info(type_info, 
                                                   self.type_brackets_check.IsChecked == True,
                                                   self.type_parentheses_check.IsChecked == True)
                parts.append(formatted_type)
                print("    Added type prefix: {}".format(formatted_type))
            
            if self.size_prefix_radio.IsChecked == True and size_info:
                formatted_size = self.format_info(size_info,
                                                   self.size_brackets_check.IsChecked == True,
                                                   self.size_parentheses_check.IsChecked == True)
                parts.append(formatted_size)
                print("    Added size prefix: {}".format(formatted_size))
            
            if base_name:
                parts.append(base_name)
                print("    Added base name: {}".format(base_name))
            
            if self.type_suffix_radio.IsChecked == True and type_info:
                formatted_type = self.format_info(type_info,
                                                   self.type_brackets_check.IsChecked == True,
                                                   self.type_parentheses_check.IsChecked == True)
                parts.append(formatted_type)
                print("    Added type suffix: {}".format(formatted_type))
            
            if self.size_suffix_radio.IsChecked == True and size_info:
                formatted_size = self.format_info(size_info,
                                                   self.size_brackets_check.IsChecked == True,
                                                   self.size_parentheses_check.IsChecked == True)
                parts.append(formatted_size)
                print("    Added size suffix: {}".format(formatted_size))
            
            # Get segment pattern info (for Line Patterns)
            segment_info = self.get_segment_info(item)
            
            if self.segments_prefix_radio.IsChecked == True and segment_info:
                formatted_segments = self.format_info(segment_info,
                                                      self.segments_brackets_check.IsChecked == True,
                                                      self.segments_parentheses_check.IsChecked == True)
                parts.insert(0, formatted_segments)  # Insert at beginning
                print("    Added segments prefix: {}".format(formatted_segments))
            
            if self.segments_suffix_radio.IsChecked == True and segment_info:
                formatted_segments = self.format_info(segment_info,
                                                      self.segments_brackets_check.IsChecked == True,
                                                      self.segments_parentheses_check.IsChecked == True)
                parts.append(formatted_segments)
                print("    Added segments suffix: {}".format(formatted_segments))
            
            print("    Parts: {}".format(parts))
            
            if parts:
                new_name = separator.join(parts)
                print("    New name: {}".format(new_name))
            else:
                print("    No parts - keeping old name")
                        
        elif selected_tab == 3:  # Custom Position
            custom_text = self.custom_textbox.Text or ""
            
            if custom_text:
                if self.pos_start_radio.IsChecked == True:
                    new_name = custom_text + old_name
                    
                elif self.pos_end_radio.IsChecked == True:
                    new_name = old_name + custom_text
                    
                elif self.pos_custom_radio.IsChecked == True:
                    try:
                        position = int(self.position_textbox.Text or "0")
                        if position < 0:
                            position = len(old_name) + position + 1
                        position = max(0, min(position, len(old_name)))
                        new_name = old_name[:position] + custom_text + old_name[position:]
                    except:
                        new_name = old_name + custom_text
                        
                elif self.pos_after_radio.IsChecked == True:
                    after_text = self.after_text_textbox.Text
                    if after_text and after_text in old_name:
                        if self.insert_after_check.IsChecked == True:
                            parts = old_name.split(after_text, 1)
                            new_name = parts[0] + after_text + custom_text + parts[1]
                        elif self.insert_before_check.IsChecked == True:
                            parts = old_name.split(after_text, 1)
                            new_name = parts[0] + custom_text + after_text + parts[1]
                    else:
                        new_name = old_name + custom_text
        
        return new_name
        
    def on_apply(self, sender, e):
        """Handle apply button click"""
        try:
            selected_tab = self.tab_control.SelectedIndex
            
            # Validate input based on tab
            if selected_tab == 0:
                if not self.prefix_textbox.Text and not self.suffix_textbox.Text:
                    MessageBox.Show(
                        "Please enter at least a prefix or suffix!",
                        "Input Required",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning
                    )
                    return
                    
            elif selected_tab == 1:
                if not self.find_textbox.Text:
                    MessageBox.Show(
                        "Please enter text to find!",
                        "Input Required",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning
                    )
                    return
                    
            elif selected_tab == 2:
                has_type = (self.type_prefix_radio.IsChecked == True or 
                           self.type_suffix_radio.IsChecked == True)
                has_size = (self.size_prefix_radio.IsChecked == True or 
                           self.size_suffix_radio.IsChecked == True)
                has_segments = (self.segments_prefix_radio.IsChecked == True or
                               self.segments_suffix_radio.IsChecked == True)
                
                if not has_type and not has_size and not has_segments and self.remove_name_check.IsChecked != True:
                    MessageBox.Show(
                        "Please select at least one option:\n" +
                        "- Add Type (as Prefix or Suffix)\n" +
                        "- Add Size (as Prefix or Suffix)\n" +
                        "- Add Segments (as Prefix or Suffix - Line Patterns only)\n" +
                        "- Or enable 'Remove Current Name'",
                        "Input Required",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning
                    )
                    return
                    
            elif selected_tab == 3:
                if not self.custom_textbox.Text:
                    MessageBox.Show(
                        "Please enter text to insert!",
                        "Input Required",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning
                    )
                    return
            
            # Apply renaming
            self.apply_batch_rename()
            
        except Exception as ex:
            print("ERROR in on_apply: {}".format(str(ex)))
            MessageBox.Show(
                "An error occurred: {}".format(str(ex)),
                "Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error
            )
            
    def on_cancel(self, sender, e):
        """Handle cancel button click"""
        self.result = None
        self.Close()
        
    def apply_batch_rename(self):
        """Apply batch rename to all selected items"""
        print("\n" + "="*60)
        print("BATCH RENAME")
        print("="*60)
        print("Total items: {}".format(len(self.selected_items)))
        print("-"*60)
        
        success_count = 0
        skip_count = 0
        error_count = 0
        
        from Autodesk.Revit.DB import Transaction, BuiltInParameter
        
        try:
            t = Transaction(self.doc, "Batch Rename")
            t.Start()
            
            for item in self.selected_items:
                # Get old name - universal approach for all element types
                old_name = None
                try:
                    # Try direct .Name property first (FillPattern, Material, etc.)
                    if hasattr(item, 'Element'):
                        # Item is a wrapper (FillPatternItem, TextNoteTypeItem, etc.)
                        old_name = item.Element.Name
                    else:
                        # Item is direct element
                        old_name = item.Name
                except:
                    # Fallback to SYMBOL_NAME_PARAM (TextNoteType, DimensionType, etc.)
                    try:
                        elem = item.Element if hasattr(item, 'Element') else item
                        name_param = elem.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                        if name_param:
                            old_name = name_param.AsString()
                    except:
                        pass
                
                if not old_name:
                    print("\nSkipped: Could not get element name")
                    skip_count += 1
                    continue
                
                new_name = self.apply_rename_rules(item, old_name)
                
                print("\nProcessing: '{}' -> '{}'".format(old_name, new_name))
                
                # Sanitize new name
                new_name_sanitized = sanitize_revit_name(new_name)
                
                if new_name != new_name_sanitized:
                    print("  Name sanitized: '{}' -> '{}'".format(new_name, new_name_sanitized))
                    new_name = new_name_sanitized
                
                # Skip if no change
                if new_name == old_name:
                    print("  Skipped: No change in name")
                    skip_count += 1
                    continue
                
                # Check for conflicts
                if self.check_name_conflict(new_name, item):
                    print("  Skipped: Name conflict")
                    skip_count += 1
                    continue
                
                # Try to rename - universal approach
                try:
                    print("  Renaming element...")
                    
                    # Get actual element
                    elem = item.Element if hasattr(item, 'Element') else item
                    
                    # Try direct .Name assignment first (FillPattern, Material, etc.)
                    try:
                        elem.Name = new_name
                        print("  Success!")
                        success_count += 1
                    except:
                        # Fallback to SYMBOL_NAME_PARAM (TextNoteType, etc.)
                        try:
                            name_param = elem.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                            if name_param and not name_param.IsReadOnly:
                                name_param.Set(new_name)
                                print("  Success via parameter!")
                                success_count += 1
                            else:
                                raise Exception("Cannot rename - read-only or system type")
                        except Exception as inner_ex:
                            raise inner_ex
                        
                except Exception as ex:
                    error_msg = str(ex)
                    print("  Error renaming: {}".format(error_msg))
                    
                    # Check if it's a read-only/system type issue
                    if "read-only" in error_msg.lower() or "cannot" in error_msg.lower():
                        print("  -> This is a system/read-only type")
                    
                    error_count += 1
            
            t.Commit()
            print("\n" + "="*60)
            print("Transaction committed: {} success, {} skipped, {} errors".format(
                success_count, skip_count, error_count))
            print("="*60 + "\n")
            
        except Exception as ex:
            print("\nERROR: Transaction failed: {}".format(str(ex)))
            if t.HasStarted():
                t.RollBack()
            error_count = len(self.selected_items)
            success_count = 0
        
        # Show results
        self.show_results(success_count, skip_count, error_count)
        
        # Auto-refresh parent window if available
        if self.parent:
            try:
                print("\nAuto-refreshing parent window...")
                # Try common refresh methods
                if hasattr(self.parent, 'load_items'):
                    self.parent.load_items()
                elif hasattr(self.parent, 'load_text_types'):
                    self.parent.load_text_types()
                
                if hasattr(self.parent, 'calculate_usage'):
                    self.parent.calculate_usage()
                
                if hasattr(self.parent, 'update_stats'):
                    self.parent.update_stats()
                
                print("Parent window refreshed successfully!")
            except Exception as ex:
                print("Warning: Could not refresh parent window: {}".format(str(ex)))
        
        # Close dialog
        self.result = True
        self.Close()
        
    def check_name_conflict(self, new_name, item):
        """Check if new name conflicts - universal for all element types"""
        try:
            # Get item ID
            try:
                if hasattr(item, 'Element'):
                    item_id = item.Element.Id
                else:
                    item_id = item.Id
            except:
                item_id = None
            
            # Get element class dynamically
            elem = item.Element if hasattr(item, 'Element') else item
            element_class = elem.GetType()
            
            # Sanitize new name for comparison
            sanitized_new = sanitize_revit_name(new_name)
            
            # Get all elements of same type
            from Autodesk.Revit.DB import FilteredElementCollector
            collector = FilteredElementCollector(self.doc).OfClass(element_class)
            
            for other_elem in collector:
                # Skip self
                if item_id and other_elem.Id == item_id:
                    continue
                
                try:
                    # Get name - try .Name first, then SYMBOL_NAME_PARAM
                    other_name = None
                    try:
                        other_name = other_elem.Name
                    except:
                        try:
                            name_param = other_elem.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                            if name_param:
                                other_name = name_param.AsString()
                        except:
                            pass
                    
                    if other_name:
                        sanitized_other = sanitize_revit_name(other_name)
                        if sanitized_other == sanitized_new:
                            print("  Name conflict: '{}' already exists".format(sanitized_new))
                            return True
                except:
                    continue
            
            return False
            
        except Exception as ex:
            print("ERROR in check_name_conflict: {}".format(str(ex)))
            return False
        
    def show_results(self, success, skipped, errors):
        """Show results message"""
        message = "Batch Rename Results:\n\n"
        message += "Successfully renamed: {}\n".format(success)
        message += "Skipped (no change/conflict): {}\n".format(skipped)
        message += "Errors: {}\n".format(errors)
        message += "\nTotal processed: {}".format(success + skipped + errors)
        
        if errors > 0:
            message += "\n\nCheck Output window for error details."
        
        icon = MessageBoxImage.Information
        if errors > 0:
            icon = MessageBoxImage.Warning
        
        MessageBox.Show(message, "Batch Rename Complete", MessageBoxButton.OK, icon)