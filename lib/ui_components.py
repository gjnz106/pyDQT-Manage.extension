# -*- coding: utf-8 -*-
"""
UI Components Module for DQT Manager Tools
Reusable WPF UI components

Copyright (c) 2025 Copyright by Dang Quoc Truong - DQT
All rights reserved.
"""

import System
from System.Windows import Thickness
from System.Windows.Controls import Button, Label, Border, StackPanel
from System.Windows.Media import SolidColorBrush, Brushes
from System.Windows import HorizontalAlignment, VerticalAlignment, FontWeights

from config import Colors, Settings


# ============================================================================
# BUTTON FACTORY
# ============================================================================

def create_button(text, width, color, height=30):
    """Create a styled button
    
    Args:
        text: Button text
        width: Button width
        color: Button background color (System.Windows.Media.Color)
        height: Button height (default 30)
        
    Returns:
        Button: Configured button
    """
    btn = Button()
    btn.Content = text
    btn.Width = width
    btn.Height = height
    btn.Margin = Thickness(5, 0, 5, 0)
    btn.Background = SolidColorBrush(color)
    btn.Foreground = Brushes.White
    btn.BorderThickness = Thickness(0)
    btn.FontWeight = FontWeights.Bold
    return btn


# ============================================================================
# HEADER COMPONENT
# ============================================================================

def create_header(title, subtitle, show_copyright=True, help_handler=None):
    """Create standardized header

    Args:
        title: Main title text
        subtitle: Subtitle text
        show_copyright: Show copyright line (default True)
        help_handler: Optional Click event handler. When given, a "? Help"
            button is added to the top-right of the header (matches the
            Family Manager v2.0 header layout).

    Returns:
        Border: Header border with content
    """
    import System.Windows.Controls as Controls

    border = Border()
    border.Background = SolidColorBrush(Colors.HEADER_BACKGROUND)
    border.BorderBrush = SolidColorBrush(Colors.HEADER_BORDER)
    border.BorderThickness = Thickness(0, 0, 0, 2)

    stack = StackPanel()
    stack.VerticalAlignment = VerticalAlignment.Center
    stack.HorizontalAlignment = HorizontalAlignment.Left
    stack.Margin = Thickness(20, 0, 20, 0)

    # Title
    title_label = Label()
    title_label.Content = title
    title_label.FontSize = 20
    title_label.FontWeight = FontWeights.Bold
    title_label.Foreground = SolidColorBrush(Colors.HEADER_TEXT)
    stack.Children.Add(title_label)

    # Subtitle
    subtitle_label = Label()
    subtitle_label.Content = subtitle
    subtitle_label.FontSize = 12
    subtitle_label.Foreground = SolidColorBrush(Colors.HEADER_SUBTITLE)
    subtitle_label.Margin = Thickness(0, -5, 0, 0)
    stack.Children.Add(subtitle_label)

    # Copyright
    if show_copyright:
        copyright_label = Label()
        copyright_label.Content = u"\u00A9 2025 " + Settings.AUTHOR
        copyright_label.FontSize = 9
        copyright_label.Foreground = SolidColorBrush(Colors.HEADER_SUBTITLE)
        copyright_label.Margin = Thickness(0, -3, 0, 0)
        stack.Children.Add(copyright_label)

    if help_handler is not None:
        header_grid = Controls.Grid()
        header_grid.Children.Add(stack)

        help_btn = Button()
        help_btn.Content = "? Help"
        help_btn.Padding = Thickness(10, 4, 10, 4)
        help_btn.Margin = Thickness(0, 0, 20, 0)
        help_btn.HorizontalAlignment = HorizontalAlignment.Right
        help_btn.VerticalAlignment = VerticalAlignment.Center
        help_btn.Background = Brushes.White
        help_btn.BorderBrush = SolidColorBrush(Colors.HEADER_BORDER)
        help_btn.Click += help_handler
        header_grid.Children.Add(help_btn)

        border.Child = header_grid
    else:
        border.Child = stack

    return border


# ============================================================================
# STAT CARD ROW (Family Manager v2.0 style)
# ============================================================================

def create_stat_card(label, color):
    """Create a single bordered stat card (white box, colored label + value)

    Args:
        label: Card label text (e.g. "TOTAL")
        color: System.Windows.Media.Color for the label/value text

    Returns:
        tuple: (Border, Label) - the card and its value label to update later
    """
    border = Border()
    border.Background = Brushes.White
    border.BorderBrush = SolidColorBrush(Colors.HEADER_BORDER)
    border.BorderThickness = Thickness(1)
    border.Padding = Thickness(8, 4, 8, 4)
    border.Margin = Thickness(4, 0, 4, 0)

    stack = StackPanel()

    label_text = Label()
    label_text.Content = label
    label_text.FontSize = 9
    label_text.Padding = Thickness(0)
    label_text.Foreground = SolidColorBrush(color)
    stack.Children.Add(label_text)

    value_label = Label()
    value_label.Content = "0"
    value_label.FontSize = 18
    value_label.Padding = Thickness(0)
    value_label.FontWeight = FontWeights.Bold
    value_label.Foreground = SolidColorBrush(color)
    stack.Children.Add(value_label)

    border.Child = stack
    return border, value_label


def create_stats_row(cards):
    """Create a horizontal row of stat cards, evenly spaced

    Args:
        cards: list of (label, color) tuples, in display order

    Returns:
        tuple: (Border, list[Label]) - the row and the cards' value labels,
            in the same order as `cards`, so callers can update them later.
    """
    import System.Windows.Controls as Controls

    outer = Border()
    outer.Background = Brushes.White
    outer.Padding = Thickness(16, 6, 16, 6)

    row = Controls.Grid()
    value_labels = []

    for i, (label, color) in enumerate(cards):
        row.ColumnDefinitions.Add(Controls.ColumnDefinition())
        card, value_label = create_stat_card(label, color)
        Controls.Grid.SetColumn(card, i)
        row.Children.Add(card)
        value_labels.append(value_label)

    outer.Child = row
    return outer, value_labels


# ============================================================================
# FOOTER COMPONENT
# ============================================================================

def create_footer():
    """Create standardized footer with copyright only

    The Total/Selected counts used to live here as plain text; they now
    live in the stat-card row under the header (see create_stats_row),
    matching the Family Manager v2.0 layout, so the footer is copyright-only.

    Returns:
        Border: Footer border with content
    """
    border = Border()
    border.Background = SolidColorBrush(Colors.FOOTER_BACKGROUND)
    border.BorderBrush = SolidColorBrush(Colors.FOOTER_BORDER)
    border.BorderThickness = Thickness(0, 2, 0, 0)
    border.Padding = Thickness(10)

    main_stack = StackPanel()
    main_stack.VerticalAlignment = VerticalAlignment.Center

    # Copyright row
    copyright_stack = StackPanel()
    copyright_stack.Orientation = System.Windows.Controls.Orientation.Horizontal
    copyright_stack.HorizontalAlignment = HorizontalAlignment.Center
    copyright_stack.Margin = Thickness(0, 3, 0, 0)
    
    copyright_label = Label()
    copyright_label.Content = Settings.COPYRIGHT_TEXT
    copyright_label.FontSize = 10
    copyright_label.FontWeight = FontWeights.Bold
    copyright_label.Foreground = SolidColorBrush(Colors.FOOTER_COPYRIGHT)
    copyright_stack.Children.Add(copyright_label)
    
    main_stack.Children.Add(copyright_stack)
    
    border.Child = main_stack
    return border


# ============================================================================
# SEARCH BOX COMPONENT
# ============================================================================

def create_search_box(text_changed_handler):
    """Create standardized search textbox
    
    Args:
        text_changed_handler: Event handler for TextChanged event
        
    Returns:
        TextBox: Configured search box
    """
    from System.Windows.Controls import TextBox
    
    search_box = TextBox()
    search_box.Height = 30
    search_box.VerticalContentAlignment = VerticalAlignment.Center
    search_box.Padding = Thickness(5)
    search_box.FontSize = 13
    search_box.TextChanged += text_changed_handler
    
    return search_box


# ============================================================================
# SELECT ALL CHECKBOX
# ============================================================================

def create_select_all_checkbox(checked_handler, unchecked_handler):
    """Create Select All checkbox with border
    
    Args:
        checked_handler: Event handler for Checked event
        unchecked_handler: Event handler for Unchecked event
        
    Returns:
        Border: Border containing checkbox
    """
    from System.Windows.Controls import CheckBox
    
    border = Border()
    border.Background = SolidColorBrush(Colors.GRID_HEADER_BG)
    border.BorderBrush = SolidColorBrush(Colors.GRID_BORDER)
    border.BorderThickness = Thickness(0, 0, 0, 1)
    border.Padding = Thickness(10)
    
    checkbox = CheckBox()
    checkbox.Content = "Select All (Tip: Hold Shift to select multiple rows)"
    checkbox.FontWeight = FontWeights.Bold
    checkbox.Checked += checked_handler
    checkbox.Unchecked += unchecked_handler
    
    border.Child = checkbox
    return border, checkbox


# ============================================================================
# TOOLBAR COMPONENT
# ============================================================================

def create_toolbar(search_box, buttons):
    """Create standardized toolbar with search and buttons
    
    Args:
        search_box: TextBox for search
        buttons: List of Button objects
        
    Returns:
        Border: Toolbar border with content
    """
    import System.Windows.Controls as Controls
    
    border = Border()
    border.Background = Brushes.White
    border.BorderBrush = SolidColorBrush(Colors.GRID_BORDER)
    border.BorderThickness = Thickness(0, 0, 0, 1)
    
    toolbar_grid = Controls.Grid()
    toolbar_grid.Margin = Thickness(10, 0, 10, 0)
    
    toolbar_grid.ColumnDefinitions.Add(Controls.ColumnDefinition())
    toolbar_grid.ColumnDefinitions.Add(Controls.ColumnDefinition())
    toolbar_grid.ColumnDefinitions[0].Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
    toolbar_grid.ColumnDefinitions[1].Width = System.Windows.GridLength(1, System.Windows.GridUnitType.Auto)
    
    # Search box
    Controls.Grid.SetColumn(search_box, 0)
    toolbar_grid.Children.Add(search_box)
    
    # Button panel
    button_panel = StackPanel()
    button_panel.Orientation = Controls.Orientation.Horizontal
    button_panel.Margin = Thickness(10, 0, 0, 0)
    Controls.Grid.SetColumn(button_panel, 1)
    
    for btn in buttons:
        button_panel.Children.Add(btn)
    
    toolbar_grid.Children.Add(button_panel)
    border.Child = toolbar_grid
    
    return border


# ============================================================================
# DIALOG HELPERS
# ============================================================================

def show_info(message, title="Information"):
    """Show information message box
    
    Args:
        message: Message text
        title: Dialog title
    """
    from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage
    MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information)


def show_warning(message, title="Warning"):
    """Show warning message box
    
    Args:
        message: Message text
        title: Dialog title
    """
    from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage
    MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Warning)


def show_error(message, title="Error"):
    """Show error message box
    
    Args:
        message: Message text
        title: Dialog title
    """
    from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage
    MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Error)


def ask_yes_no(message, title="Confirm"):
    """Show yes/no confirmation dialog
    
    Args:
        message: Message text
        title: Dialog title
        
    Returns:
        bool: True if Yes clicked, False otherwise
    """
    from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult
    result = MessageBox.Show(message, title, MessageBoxButton.YesNo, MessageBoxImage.Question)
    return result == MessageBoxResult.Yes