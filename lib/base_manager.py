# -*- coding: utf-8 -*-
"""
Base Manager Module for DQT Manager Tools
Base class for all manager tools with shared functionality

Copyright (c) 2025 Copyright by Dang Quoc Truong (DQT)
All rights reserved.

Usage:
    from base_manager import BaseManagerWindow, BaseItem
    
    class TextNoteTypeItem(BaseItem):
        # Implement tool-specific item
        pass
    
    class TextNoteTypeManager(BaseManagerWindow):
        def __init__(self):
            config = {
                'title': 'Text Note Type Manager',
                'element_type': DB.TextNoteType,
                # ... other config
            }
            super().__init__(config)
"""

import clr
clr.AddReference('System')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System.Windows import Window, Thickness, WindowStartupLocation
from System.Windows.Controls import (DataGrid, DataGridTextColumn, DataGridCheckBoxColumn,
                                     DataGridSelectionMode, DataGridLength, Label)
from System.Windows.Media import SolidColorBrush, Brushes
from System.Windows import HorizontalAlignment, VerticalAlignment
from System.Collections.ObjectModel import ObservableCollection
from System.Windows.Data import Binding
import System

from Autodesk.Revit.DB import Transaction, FilteredElementCollector

from config import Colors, Settings, ButtonConfig
from ui_components import (create_button, create_header, create_footer,
                               create_search_box, create_select_all_checkbox,
                               create_toolbar, show_info, show_warning,
                               show_error, ask_yes_no)
from revit_utils import (get_element_name, set_element_name,
                             sanitize_name, check_name_conflict,
                             duplicate_element, delete_element,
                             calculate_usage, calculate_usage_percentage,
                             safe_transaction)


# ============================================================================
# BASE ITEM CLASS - Simple Python class (NO INotifyPropertyChanged)
# ============================================================================

class BaseItem(object):
    """Base class for item wrappers
    
    Each tool should extend this class and add tool-specific properties.
    Note: Does NOT implement INotifyPropertyChanged to avoid IronPython crashes.
    WPF binding still works, but won't auto-update (we refresh manually).
    """
    
    def __init__(self, element):
        self._element = element
        self._is_selected = False
        
        # Get common properties
        self._name = get_element_name(element)
        self._id = element.Id.IntegerValue
        self._usage_count = 0
        self._usage_percentage = 0.0
    
    @property
    def Element(self):
        return self._element
    
    @property
    def Id(self):
        return self._id
    
    @property
    def Name(self):
        return self._name
    
    @property
    def UsageCount(self):
        return self._usage_count
    
    @UsageCount.setter
    def UsageCount(self, value):
        self._usage_count = value
    
    @property
    def UsagePercentage(self):
        return self._usage_percentage
    
    @UsagePercentage.setter
    def UsagePercentage(self, value):
        self._usage_percentage = value
    
    @property
    def IsSelected(self):
        return self._is_selected
    
    @IsSelected.setter
    def IsSelected(self, value):
        self._is_selected = value


# ============================================================================
# BASE MANAGER WINDOW
# ============================================================================

class BaseManagerWindow(Window):
    """Base window for all manager tools
    
    Configuration dict should contain:
        - title: Window title
        - subtitle: Window subtitle
        - element_type: Revit element class (e.g., DB.TextNoteType)
        - instance_type: Revit instance class for usage calc (e.g., DB.TextNote)
        - item_class: Item wrapper class
        - has_batch_rename: Enable batch rename button (default True)
        - has_edit_properties: Enable edit properties button (default False)
        - has_duplicate: Enable duplicate button (default True)
        - has_delete: Enable delete button (default True)
        - extra_columns: List of extra column definitions
        - edit_config: Configuration for edit properties dialog
    """
    
    def __init__(self, doc, config):
        self.doc = doc
        self.config = config
        
        # Window properties
        self.Title = config.get('title', 'Manager') + " - By DQT"
        self.Width = config.get('width', Settings.DEFAULT_WIDTH)
        self.Height = config.get('height', Settings.DEFAULT_HEIGHT)
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.Background = SolidColorBrush(Colors.DIALOG_BACKGROUND)
        
        # Data collections - USE object TYPE to avoid IronPython crash!
        self.all_items = ObservableCollection[object]()
        self.filtered_items = ObservableCollection[object]()
        
        # Create UI
        self.create_ui()
        
        # Load data
        self.load_items()
        self.calculate_usage()
        self.update_stats()
    
    def create_ui(self):
        """Create the user interface"""
        main_grid = System.Windows.Controls.Grid()
        
        # Define rows
        main_grid.RowDefinitions.Add(System.Windows.Controls.RowDefinition())
        main_grid.RowDefinitions.Add(System.Windows.Controls.RowDefinition())
        main_grid.RowDefinitions.Add(System.Windows.Controls.RowDefinition())
        main_grid.RowDefinitions.Add(System.Windows.Controls.RowDefinition())
        
        main_grid.RowDefinitions[0].Height = System.Windows.GridLength(70)
        main_grid.RowDefinitions[1].Height = System.Windows.GridLength(50)
        main_grid.RowDefinitions[2].Height = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
        main_grid.RowDefinitions[3].Height = System.Windows.GridLength(60)
        
        # Header
        header = self.create_header_section()
        System.Windows.Controls.Grid.SetRow(header, 0)
        main_grid.Children.Add(header)
        
        # Toolbar
        toolbar = self.create_toolbar_section()
        System.Windows.Controls.Grid.SetRow(toolbar, 1)
        main_grid.Children.Add(toolbar)
        
        # Content
        content = self.create_content_section()
        System.Windows.Controls.Grid.SetRow(content, 2)
        main_grid.Children.Add(content)
        
        # Footer
        footer = self.create_footer_section()
        System.Windows.Controls.Grid.SetRow(footer, 3)
        main_grid.Children.Add(footer)
        
        self.Content = main_grid
    
    def create_header_section(self):
        """Create header section"""
        return create_header(
            self.config.get('title', 'Manager'),
            self.config.get('subtitle', 'Manage elements'),
            show_copyright=True
        )
    
    def create_toolbar_section(self):
        """Create toolbar section with search and buttons"""
        # Create search box
        self.search_box = create_search_box(self.on_search_changed)
        
        # Create buttons based on config
        buttons = []
        
        # Batch Rename button
        if self.config.get('has_batch_rename', Settings.DEFAULT_HAS_BATCH_RENAME):
            btn = create_button(
                ButtonConfig.BATCH_RENAME['text'],
                ButtonConfig.BATCH_RENAME['width'],
                ButtonConfig.BATCH_RENAME['color']
            )
            btn.Click += self.on_batch_rename_click
            buttons.append(btn)
        
        # Edit Properties button
        if self.config.get('has_edit_properties', Settings.DEFAULT_HAS_EDIT_PROPERTIES):
            btn = create_button(
                ButtonConfig.EDIT_PROPERTIES['text'],
                ButtonConfig.EDIT_PROPERTIES['width'],
                ButtonConfig.EDIT_PROPERTIES['color']
            )
            btn.Click += self.on_edit_properties_click
            buttons.append(btn)
        
        # Rename button
        btn_rename = create_button(
            ButtonConfig.RENAME['text'],
            ButtonConfig.RENAME['width'],
            ButtonConfig.RENAME['color']
        )
        btn_rename.Click += self.on_rename_click
        buttons.append(btn_rename)
        
        # Duplicate button
        if self.config.get('has_duplicate', Settings.DEFAULT_HAS_DUPLICATE):
            btn = create_button(
                ButtonConfig.DUPLICATE['text'],
                ButtonConfig.DUPLICATE['width'],
                ButtonConfig.DUPLICATE['color']
            )
            btn.Click += self.on_duplicate_click
            buttons.append(btn)
        
        # Delete button
        if self.config.get('has_delete', Settings.DEFAULT_HAS_DELETE):
            btn = create_button(
                ButtonConfig.DELETE['text'],
                ButtonConfig.DELETE['width'],
                ButtonConfig.DELETE['color']
            )
            btn.Click += self.on_delete_click
            buttons.append(btn)
        
        # Refresh button
        btn_refresh = create_button(
            ButtonConfig.REFRESH['text'],
            ButtonConfig.REFRESH['width'],
            ButtonConfig.REFRESH['color']
        )
        btn_refresh.Click += self.on_refresh_click
        buttons.append(btn_refresh)
        
        # Close button
        btn_close = create_button(
            ButtonConfig.CLOSE['text'],
            ButtonConfig.CLOSE['width'],
            ButtonConfig.CLOSE['color']
        )
        btn_close.Click += self.on_close_click
        buttons.append(btn_close)
        
        return create_toolbar(self.search_box, buttons)
    
    def create_content_section(self):
        """Create content section with DataGrid"""
        from System.Windows.Controls import Border, Grid as WPFGrid, RowDefinition
        
        border = Border()
        border.Background = Brushes.White
        border.Margin = Thickness(10)
        border.BorderBrush = SolidColorBrush(Colors.GRID_BORDER)
        border.BorderThickness = Thickness(1)
        
        grid = WPFGrid()
        grid.RowDefinitions.Add(RowDefinition())
        grid.RowDefinitions.Add(RowDefinition())
        grid.RowDefinitions[0].Height = System.Windows.GridLength(1, System.Windows.GridUnitType.Auto)
        grid.RowDefinitions[1].Height = System.Windows.GridLength(1, System.Windows.GridUnitType.Star)
        
        # Select All checkbox
        select_all_border, self.select_all_checkbox = create_select_all_checkbox(
            self.on_select_all,
            self.on_unselect_all
        )
        System.Windows.Controls.Grid.SetRow(select_all_border, 0)
        grid.Children.Add(select_all_border)
        
        # DataGrid
        self.data_grid = self.create_datagrid()
        System.Windows.Controls.Grid.SetRow(self.data_grid, 1)
        grid.Children.Add(self.data_grid)
        
        border.Child = grid
        return border
    
    def create_datagrid(self):
        """Create and configure DataGrid"""
        data_grid = DataGrid()
        data_grid.AutoGenerateColumns = False
        data_grid.CanUserAddRows = False
        data_grid.CanUserDeleteRows = False
        data_grid.IsReadOnly = True  # For multi-select to work properly
        data_grid.SelectionMode = DataGridSelectionMode.Extended
        data_grid.SelectionUnit = System.Windows.Controls.DataGridSelectionUnit.FullRow
        data_grid.HeadersVisibility = System.Windows.Controls.DataGridHeadersVisibility.Column
        data_grid.AlternatingRowBackground = SolidColorBrush(Colors.GRID_ALTERNATING)
        data_grid.GridLinesVisibility = System.Windows.Controls.DataGridGridLinesVisibility.Horizontal
        data_grid.HorizontalGridLinesBrush = SolidColorBrush(Colors.GRID_BORDER)
        data_grid.CanUserSortColumns = Settings.ENABLE_SORTING
        data_grid.CanUserReorderColumns = False
        data_grid.CanUserResizeColumns = True
        
        # Selection changed event - sync row selection with checkboxes
        data_grid.SelectionChanged += self.on_datagrid_selection_changed
        
        # Add standard columns
        self.add_standard_columns(data_grid)
        
        # Add extra columns if configured
        extra_columns = self.config.get('extra_columns', [])
        for col_config in extra_columns:
            self.add_extra_column(data_grid, col_config)
        
        data_grid.ItemsSource = self.filtered_items
        
        return data_grid
    
    def add_standard_columns(self, grid):
        """Add standard columns (Select, Name, Usage, Usage %, ID)"""
        from System.Windows.Data import BindingMode
        
        # Select column - NOTE: IsReadOnly must be False for checkbox to work
        col_select = DataGridCheckBoxColumn()
        col_select.Header = "Select"
        col_select.Width = DataGridLength(60)
        
        # Create binding with TwoWay mode
        binding = Binding("IsSelected")
        binding.Mode = BindingMode.TwoWay
        binding.UpdateSourceTrigger = System.Windows.Data.UpdateSourceTrigger.PropertyChanged
        col_select.Binding = binding
        
        col_select.CanUserSort = False
        col_select.IsReadOnly = False  # CRITICAL: Must be False for checkbox!
        grid.Columns.Add(col_select)
        
        # Name column
        col_name = DataGridTextColumn()
        col_name.Header = "Name"
        col_name.Width = DataGridLength(300)
        col_name.Binding = Binding("Name")
        col_name.IsReadOnly = True
        col_name.CanUserSort = True
        col_name.SortMemberPath = "Name"
        grid.Columns.Add(col_name)
        
        # Usage Count column
        col_usage = DataGridTextColumn()
        col_usage.Header = "Usage"
        col_usage.Width = DataGridLength(80)
        col_usage.Binding = Binding("UsageCount")
        col_usage.IsReadOnly = True
        col_usage.CanUserSort = True
        col_usage.SortMemberPath = "UsageCount"
        grid.Columns.Add(col_usage)
        
        # Usage Percentage column
        col_percent = DataGridTextColumn()
        col_percent.Header = "Usage %"
        col_percent.Width = DataGridLength(80)
        col_percent.Binding = Binding("UsagePercentage")
        col_percent.IsReadOnly = True
        col_percent.CanUserSort = True
        col_percent.SortMemberPath = "UsagePercentage"
        grid.Columns.Add(col_percent)
        
        # ID column
        col_id = DataGridTextColumn()
        col_id.Header = "ID"
        col_id.Width = DataGridLength(100)
        col_id.Binding = Binding("Id")
        col_id.IsReadOnly = True
        col_id.CanUserSort = True
        col_id.SortMemberPath = "Id"
        grid.Columns.Add(col_id)
    
    def add_extra_column(self, grid, col_config):
        """Add extra column based on configuration
        
        col_config should contain:
            - name: Column header name
            - binding: Property name to bind
            - width: Column width (default 100)
            - sortable: Enable sorting (default True)
        """
        col = DataGridTextColumn()
        col.Header = col_config.get('name', 'Extra')
        col.Width = DataGridLength(col_config.get('width', 100))
        col.Binding = Binding(col_config.get('binding', 'Extra'))
        col.IsReadOnly = True
        
        if col_config.get('sortable', True):
            col.CanUserSort = True
            col.SortMemberPath = col_config.get('binding', 'Extra')
        else:
            col.CanUserSort = False
        
        grid.Columns.Add(col)
    
    def create_footer_section(self):
        """Create footer section"""
        self.total_label = Label()
        self.selected_label = Label()
        return create_footer(self.total_label, self.selected_label)
    
    # ========================================================================
    # DATA LOADING
    # ========================================================================
    
    def load_items(self):
        """Load items from Revit document"""
        self.all_items.Clear()
        
        element_type = self.config['element_type']
        item_class = self.config['item_class']
        
        try:
            collector = FilteredElementCollector(self.doc).OfClass(element_type)
            
            for element in collector:
                if element:
                    try:
                        item = item_class(element)
                        self.all_items.Add(item)
                    except Exception as ex:
                        print("Error creating item: {}".format(str(ex)))
                        continue
        except Exception as ex:
            print("Error loading items: {}".format(str(ex)))
        
        self.apply_filter()
    
    def calculate_usage(self):
        """Calculate usage for all items"""
        instance_type = self.config.get('instance_type')
        if not instance_type:
            return  # No usage calculation for this tool
        
        try:
            # Collect all instances
            instances = FilteredElementCollector(self.doc).OfClass(instance_type).ToElements()
            
            usage_dict = {}
            for inst in instances:
                try:
                    type_id = inst.GetTypeId()
                    if type_id in usage_dict:
                        usage_dict[type_id] += 1
                    else:
                        usage_dict[type_id] = 1
                except:
                    continue
            
            total_count = len(instances)
            
            # Update items
            for item in self.all_items:
                element_id = item.Element.Id
                count = usage_dict.get(element_id, 0)
                item.UsageCount = count
                item.UsagePercentage = calculate_usage_percentage(count, total_count)
        except Exception as ex:
            print("Error calculating usage: {}".format(str(ex)))
    
    def apply_filter(self):
        """Apply search filter"""
        self.filtered_items.Clear()
        search_text = ""
        
        try:
            if self.search_box and self.search_box.Text:
                search_text = self.search_box.Text.lower()
        except:
            pass
        
        for item in self.all_items:
            try:
                if not search_text or search_text in item.Name.lower():
                    self.filtered_items.Add(item)
            except:
                continue
    
    def get_selected_items(self):
        """Get selected items from DataGrid selection"""
        selected = []
        try:
            # Get from DataGrid's SelectedItems
            for item in self.data_grid.SelectedItems:
                if item and item not in selected:
                    selected.append(item)
        except:
            pass
        
        # Also check IsSelected property as fallback
        if not selected:
            for item in self.all_items:
                try:
                    if item.IsSelected:
                        selected.append(item)
                except:
                    continue
        
        return selected
    
    def update_stats(self):
        """Update statistics"""
        try:
            total = len(self.filtered_items)
            selected = len(self.get_selected_items())
            
            self.total_label.Content = "Total: {}".format(total)
            self.selected_label.Content = "Selected: {}".format(selected)
        except Exception as ex:
            print("Error updating stats: {}".format(str(ex)))
    
    # ========================================================================
    # EVENT HANDLERS
    # ========================================================================
    
    def on_datagrid_selection_changed(self, sender, args):
        """Sync DataGrid selection with IsSelected property"""
        try:
            # Update IsSelected based on DataGrid selection
            for item in self.filtered_items:
                try:
                    is_selected = item in self.data_grid.SelectedItems
                    item.IsSelected = is_selected
                except:
                    continue
            self.update_stats()
        except Exception as ex:
            print("Error in selection changed: {}".format(str(ex)))
    
    def on_search_changed(self, sender, args):
        """Handle search text changed"""
        self.apply_filter()
        self.update_stats()
    
    def on_select_all(self, sender, args):
        """Select all items"""
        try:
            self.data_grid.SelectAll()
            for item in self.filtered_items:
                item.IsSelected = True
            self.update_stats()
        except Exception as ex:
            print("Error selecting all: {}".format(str(ex)))
    
    def on_unselect_all(self, sender, args):
        """Unselect all items"""
        try:
            self.data_grid.UnselectAll()
            for item in self.filtered_items:
                item.IsSelected = False
            self.update_stats()
        except Exception as ex:
            print("Error unselecting all: {}".format(str(ex)))
    
    # ========================================================================
    # BUTTON HANDLERS - TO BE IMPLEMENTED BY SUBCLASS OR USE DEFAULT
    # ========================================================================
    
    def on_batch_rename_click(self, sender, args):
        """Handle batch rename - override if needed"""
        try:
            from batch_rename_dialog import BatchRenameDialog
        except ImportError:
            show_error("Batch Rename Dialog not available. Please ensure batch_rename_dialog.py is in the lib folder.")
            return
        
        selected = self.get_selected_items()
        if not selected:
            show_warning("Please select at least one item!")
            return
        
        try:
            # Pass items (not elements) to dialog
            dialog = BatchRenameDialog(self.doc, selected, self)
            dialog.ShowDialog()
        except Exception as ex:
            show_error("Error opening Batch Rename Dialog: {}".format(str(ex)))
    
    def on_edit_properties_click(self, sender, args):
        """Handle edit properties - override if needed"""
        try:
            from edit_properties_dialog import EditPropertiesDialog
        except ImportError:
            show_error("Edit Properties Dialog not available.")
            return
        
        selected = self.get_selected_items()
        if not selected:
            show_warning("Please select at least one item!")
            return
        
        try:
            elements = [item.Element for item in selected]
            edit_config = self.config.get('edit_config', {})
            dialog = EditPropertiesDialog(self.doc, elements, edit_config, self)
            dialog.ShowDialog()
        except Exception as ex:
            show_error("Error opening Edit Properties Dialog: {}".format(str(ex)))
    
    def on_rename_click(self, sender, args):
        """Handle rename single item"""
        from pyrevit import forms
        
        selected = self.get_selected_items()
        if not selected:
            show_warning("Please select one item to rename!")
            return
        
        if len(selected) > 1:
            show_warning("Please select only one item to rename!")
            return
        
        item = selected[0]
        new_name = forms.ask_for_string(
            default=item.Name,
            prompt="Enter new name:",
            title="Rename"
        )
        
        if not new_name or new_name == item.Name:
            return
        
        new_name = sanitize_name(new_name)
        
        # Check conflict
        if check_name_conflict(self.doc, self.config['element_type'], new_name, item.Element.Id):
            show_warning("An item with name '{}' already exists!".format(new_name))
            return
        
        # Rename
        t = Transaction(self.doc, "Rename")
        t.Start()
        
        try:
            if set_element_name(item.Element, new_name):
                t.Commit()
                show_info("Item renamed successfully!")
                self.load_items()
                self.calculate_usage()
                self.update_stats()
            else:
                t.RollBack()
                show_error("Failed to rename item. It may be a system type.")
        except Exception as ex:
            t.RollBack()
            show_error("Error renaming: {}".format(str(ex)))
    
    def on_duplicate_click(self, sender, args):
        """Handle duplicate items"""
        selected = self.get_selected_items()
        if not selected:
            show_warning("Please select at least one item to duplicate!")
            return
        
        t = Transaction(self.doc, "Duplicate")
        t.Start()
        
        try:
            success_count = 0
            for item in selected:
                new_id = duplicate_element(item.Element)
                from Autodesk.Revit.DB import ElementId
                if new_id != ElementId.InvalidElementId:
                    success_count += 1
            
            t.Commit()
            show_info("Successfully duplicated {} item(s)!".format(success_count))
            
            self.load_items()
            self.calculate_usage()
            self.update_stats()
        except Exception as ex:
            t.RollBack()
            show_error("Error duplicating: {}".format(str(ex)))
    
    def on_delete_click(self, sender, args):
        """Handle delete items"""
        selected = self.get_selected_items()
        if not selected:
            show_warning("Please select at least one item to delete!")
            return
        
        # Check usage
        in_use = [item for item in selected if item.UsageCount > 0]
        if in_use:
            msg = "The following items are in use:\n\n"
            for item in in_use[:5]:
                msg += "- {} ({} instances)\n".format(item.Name, item.UsageCount)
            if len(in_use) > 5:
                msg += "... and {} more\n".format(len(in_use) - 5)
            msg += "\nAre you sure you want to delete them?"
            
            if not ask_yes_no(msg):
                return
        else:
            if not ask_yes_no("Are you sure you want to delete {} item(s)?".format(len(selected))):
                return
        
        t = Transaction(self.doc, "Delete")
        t.Start()
        
        try:
            success_count = 0
            error_count = 0
            
            for item in selected:
                if delete_element(self.doc, item.Element.Id):
                    success_count += 1
                else:
                    error_count += 1
            
            t.Commit()
            
            msg = "Deleted: {}\n".format(success_count)
            if error_count > 0:
                msg += "Failed: {}".format(error_count)
            
            show_info(msg)
            
            self.load_items()
            self.calculate_usage()
            self.update_stats()
        except Exception as ex:
            t.RollBack()
            show_error("Error deleting: {}".format(str(ex)))
    
    def on_refresh_click(self, sender, args):
        """Handle refresh"""
        self.load_items()
        self.calculate_usage()
        self.update_stats()
        show_info("Data refreshed!")
    
    def on_close_click(self, sender, args):
        """Handle close"""
        self.Close()