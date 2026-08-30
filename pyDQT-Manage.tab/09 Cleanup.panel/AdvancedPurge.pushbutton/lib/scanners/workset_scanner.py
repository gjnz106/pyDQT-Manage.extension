# -*- coding: utf-8 -*-
"""
Workset Scanner
Scans for elements on specific worksets

Copyright © 2025 Dang Quoc Truong (DQT)
"""

__author__ = "Dang Quoc Truong (DQT)"

try:
    from base_scanner import BaseAdvancedScanner
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    from base_scanner import BaseAdvancedScanner

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInParameter

# Import compatibility helper
try:
    from revit_utils import _eid_int
except:
    # Fallback if revit_utils not available
    def _eid_int(element_id):
        """Get ElementId integer value - works for Revit 2024-2027"""
        if element_id is None:
            return -1
        try:
            # Revit 2026+ uses .Value
            if hasattr(element_id, 'Value'):
                return element_id.Value
        except:
            pass
        try:
            # Revit 2024/2025 uses .IntegerValue
            if hasattr(element_id, 'IntegerValue'):
                return element_id.IntegerValue
        except:
            pass
        return -1


class WorksetScanner(BaseAdvancedScanner):
    """Scanner for elements on specific worksets"""
    
    def scan(self, category):
        """
        Scan for elements on the workset specified by category
        
        Args:
            category: AdvancedPurgeCategory with workset_id attribute
            
        Returns:
            List of item dictionaries
        """
        items = []
        
        # Check if document is workshared
        if not self.doc.IsWorkshared:
            return items
        
        # Get workset_id from category (set during dynamic category creation)
        if not hasattr(category, 'workset_id'):
            return items
        
        target_workset_id = category.workset_id
        
        try:
            # Collect all elements on this workset
            collector = FilteredElementCollector(self.doc)
            all_elements = collector.WhereElementIsNotElementType().ToElements()
            
            for elem in all_elements:
                # Check if element is on target workset
                elem_workset_param = elem.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
                
                if elem_workset_param and elem_workset_param.AsInteger() == _eid_int(target_workset_id):
                    # Element is on target workset
                    if self.can_delete(elem):
                        item_dict = self.create_item_dict(
                            elem,
                            category_name=category.name
                        )
                        items.append(item_dict)
            
        except Exception as e:
            workset_name = getattr(category, 'workset_name', 'Unknown')
            print("Error scanning workset '{}': {}".format(workset_name, str(e)))
        
        return items