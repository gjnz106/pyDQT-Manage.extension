# -*- coding: utf-8 -*-
"""
IFC-SG Manual Assignment Tool
Assigns IFC Export parameters according to Singapore BIM standards
"""

__title__ = "Manual Assign\nIFC Class"
__author__ = "Dang Quoc Truong - DQT"
__doc__ = """Manual assignment of IFC Export classes with advanced UI.
Allows filtering, searching, and bulk editing of IFC assignments."""

import clr
clr.AddReference("System")
for _asm in ("System.Data", "System.Data.Common"):
    try:
        clr.AddReference(_asm)
    except Exception:
        pass
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System
from System.IO import MemoryStream
from System.Text import Encoding
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.Data import DataTable
from System.Windows import MessageBox as WPFMessageBox
from System.Windows import MessageBoxButton, MessageBoxResult, MessageBoxImage
from System.Windows.Controls import DataGridEditingUnit
from System.Windows.Markup import XamlReader
from System.Windows.Forms import SaveFileDialog, DialogResult as WFDialogResult

from pyrevit import DB, forms, script

# ---------------------------------------------------------------------------
# The window is WPF and uses the shared DQT gold palette (#FEF8E7 body,
# #F0CC88 header, #D4B87A borders, #5D4E37 text) so this tool looks the same
# as Family Manager v2.0 and the rest of the IFC-SG panel. The colours are
# declared in the XAML below; only the footer line is needed in code.
# ---------------------------------------------------------------------------
DQT_FOOTER_TEXT = "Dang Quoc Truong - DQT (c) 2026"


def _load_xaml(xaml_str):
    """Parse a XAML string into a live WPF object tree."""
    return XamlReader.Load(MemoryStream(Encoding.UTF8.GetBytes(xaml_str)))


def _strip_desc(text):
    """'IfcWall.PARAPET [Parapet Wall]' -> 'IfcWall.PARAPET'."""
    return str(text).split(" [")[0]

# Get the current document
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


def _eid_int(eid):
    """Get integer value of ElementId. Revit 2024+: .Value, older: .IntegerValue"""
    try:
        return eid.Value
    except:
        try:
            return eid.IntegerValue
        except:
            return 0


class _SilentFailures(DB.IFailuresPreprocessor):
    """Swallow warnings so the IFC assignment transaction is not interrupted."""
    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue

# IFC-SG Mapping Dictionary (Comprehensive based on CX Pilot Mapping)
IFC_SG_MAPPING = {
    "Walls": [
        {"entity": "IfcWall", "subtype": "", "desc": "Standard Wall"},
        {"entity": "IfcWall", "subtype": "PARAPET", "desc": "Parapet Wall"},
        {"entity": "IfcWall", "subtype": "RETAININGWALL", "desc": "Retaining Wall"},
        {"entity": "IfcWall", "subtype": "*BOUNDARYWALL", "desc": "Boundary Wall"},
        {"entity": "IfcWall", "subtype": "*REFUSECHUTE", "desc": "Refuse Chute"},
    ],
    "Curtain Walls": [
        {"entity": "IfcCurtainWall", "subtype": "", "desc": "Curtain Wall System"},
    ],
    "Floors": [
        {"entity": "IfcSlab", "subtype": "", "desc": "Standard Slab/Floor"},
        {"entity": "IfcSlab", "subtype": "*ACCESSIBLEROUTE", "desc": "Accessible Route"},
        {"entity": "IfcCovering", "subtype": "FLOORING", "desc": "Floor Covering"},
        {"entity": "IfcCivilElement", "subtype": "*ACCESSIBLEROUTE", "desc": "Civil - Accessible Route"},
        {"entity": "IfcCivilElement", "subtype": "*FOOTPATH", "desc": "Footpath"},
        {"entity": "IfcCivilElement", "subtype": "*DRIVEWAY", "desc": "Driveway"},
        {"entity": "IfcCivilElement", "subtype": "*CARRIAGEWAY", "desc": "Carriageway"},
        {"entity": "IfcCivilElement", "subtype": "*ROADKERB", "desc": "Road Kerb"},
    ],
    "Roofs": [
        {"entity": "IfcRoof", "subtype": "", "desc": "Standard Roof"},
        {"entity": "IfcSlab", "subtype": "ROOF", "desc": "Roof Slab"},
        {"entity": "IfcCovering", "subtype": "ROOFING", "desc": "Roof Covering"},
        {"entity": "IfcCovering", "subtype": "*SOFFIT", "desc": "Soffit"},
    ],
    "Ceilings": [
        {"entity": "IfcCovering", "subtype": "CEILING", "desc": "Ceiling"},
    ],
    "Doors": [
        {"entity": "IfcDoor", "subtype": "", "desc": "Standard Door"},
        {"entity": "IfcDoor", "subtype": "*BLASTDOOR", "desc": "Blast Door"},
        {"entity": "IfcDoor", "subtype": "*ROLLERSHUTTER", "desc": "Roller Shutter"},
        {"entity": "IfcDoor", "subtype": "*OPENING", "desc": "Door Opening"},
        {"entity": "IfcDoor", "subtype": "*ACCESSHATCH", "desc": "Access Hatch"},
        {"entity": "IfcDoor", "subtype": "*RECYCLABLESCHUTEACCESSPANEL", "desc": "Recyclable Chute Access Panel"},
        {"entity": "IfcDoor", "subtype": "*RECYCLABLESCHUTEHOPPER", "desc": "Recyclable Chute Hopper"},
        {"entity": "IfcDoor", "subtype": "*REFUSECHUTEACCESSPANEL", "desc": "Refuse Chute Access Panel"},
        {"entity": "IfcDoor", "subtype": "*REFUSECHUTEHOPPER", "desc": "Refuse Chute Hopper"},
    ],
    "Windows": [
        {"entity": "IfcWindow", "subtype": "", "desc": "Standard Window"},
        {"entity": "IfcWindow", "subtype": "WINDOW", "desc": "Window"},
        {"entity": "IfcWindow", "subtype": "SKYLIGHT", "desc": "Skylight"},
        {"entity": "IfcWindow", "subtype": "LOUVRE", "desc": "Louvre Window"},
        {"entity": "IfcWindow", "subtype": "*OPENING", "desc": "Window Opening"},
        {"entity": "IfcWindow", "subtype": "*BAYWINDOW", "desc": "Bay Window"},
        {"entity": "IfcWindow", "subtype": "*VENTILATIONSLEEVE", "desc": "Ventilation Sleeve"},
    ],
    "Columns": [
        {"entity": "IfcColumn", "subtype": "", "desc": "Column"},
    ],
    "Structural Columns": [
        {"entity": "IfcColumn", "subtype": "", "desc": "Structural Column"},
    ],
    "Structural Framing": [
        {"entity": "IfcBeam", "subtype": "", "desc": "Beam"},
    ],
    "Structural Foundations": [
        {"entity": "IfcFooting", "subtype": "", "desc": "Footing"},
        {"entity": "IfcPile", "subtype": "", "desc": "Pile"},
    ],
    "Stairs": [
        {"entity": "IfcStair", "subtype": "", "desc": "Stair"},
        {"entity": "IfcStairFlight", "subtype": "", "desc": "Stair Flight"},
    ],
    "Ramps": [
        {"entity": "IfcRamp", "subtype": "*ACCESSIBLEROUTE", "desc": "Accessible Ramp"},
        {"entity": "IfcRamp", "subtype": "*CURVEDRAMP", "desc": "Curved Ramp"},
        {"entity": "IfcRamp", "subtype": "*FLAREDKERBRAMP", "desc": "Flared Kerb Ramp"},
        {"entity": "IfcRamp", "subtype": "STRAIGHT_RUN_RAMP", "desc": "Straight Run Ramp"},
    ],
    "Railings": [
        {"entity": "IfcRailing", "subtype": "GUARDRAIL", "desc": "Guard Rail"},
        {"entity": "IfcRailing", "subtype": "*BOLLARD", "desc": "Bollard"},
    ],
    "Rooms": [
        {"entity": "IfcSpace", "subtype": "", "desc": "Space/Room"},
        {"entity": "IfcSpace", "subtype": "SPACE", "desc": "Standard Space"},
    ],
    "Areas": [
        {"entity": "IfcSpace", "subtype": "SPACE", "desc": "Area Space"},
        {"entity": "IfcSpace", "subtype": "*ACCESSIBLEROUTE", "desc": "Accessible Route Space"},
        {"entity": "IfcSpace", "subtype": "*ACCESSWAY", "desc": "Access Way"},
        {"entity": "IfcSpace", "subtype": "*PARKINGACCESSWAY", "desc": "Parking Access Way"},
        {"entity": "IfcSpace", "subtype": "*FIREENGINEACCESSROAD", "desc": "Fire Engine Access Road"},
        {"entity": "IfcSpace", "subtype": "*FIREENGINEACCESSWAY", "desc": "Fire Engine Access Way"},
        {"entity": "IfcSpace", "subtype": "*VEHICULARSERVICEROAD", "desc": "Vehicular Service Road"},
        {"entity": "IfcSpace", "subtype": "*AREA_CONNECTIVITY", "desc": "Area Connectivity"},
        {"entity": "IfcSpace", "subtype": "*AREA_GFA", "desc": "GFA Area"},
        {"entity": "IfcSpace", "subtype": "*AREA_LANDSCAPE", "desc": "Landscape Area"},
        {"entity": "IfcSpace", "subtype": "*AREA_STRATA", "desc": "Strata Area"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*DRIVEWAY", "desc": "Driveway Proxy"},
    ],
    "Furniture": [
        {"entity": "IfcFurniture", "subtype": "", "desc": "Standard Furniture"},
        {"entity": "IfcFurniture", "subtype": "CHAIR", "desc": "Chair"},
        {"entity": "IfcFurniture", "subtype": "*BENCH", "desc": "Bench"},
        {"entity": "IfcFurniture", "subtype": "*CHANGINGBED", "desc": "Changing Bed"},
        {"entity": "IfcFurniture", "subtype": "*CHILDPROTECTIONSEAT", "desc": "Child Protection Seat"},
        {"entity": "IfcFurniture", "subtype": "*DIAPERCHANGINGTABLE", "desc": "Diaper Changing Table"},
        {"entity": "IfcFurniture", "subtype": "*PLANTERBOX", "desc": "Planter Box"},
        {"entity": "IfcFurniture", "subtype": "*RACK", "desc": "Rack"},
    ],
    "Generic Models": [
        {"entity": "IfcBuildingElementProxy", "subtype": "", "desc": "Generic Proxy"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*ACCESSIBLEROUTE", "desc": "Accessible Route Proxy"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*BOREHOLE", "desc": "Borehole"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*TACTILETILE", "desc": "Tactile Tile"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*PORTABLEFIREEXTINGUISHER", "desc": "Portable Fire Extinguisher"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*CARLOT", "desc": "Car Lot"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*MOTOR-CYCLELOT", "desc": "Motorcycle Lot"},
        {"entity": "IfcBuildingElementProxy", "subtype": "*SIGNAGE_EXIT", "desc": "Exit Signage"},
        {"entity": "IfcCivilElement", "subtype": "*CULVERT", "desc": "Culvert"},
        {"entity": "IfcCivilElement", "subtype": "*ENTRANCECULVERT", "desc": "Entrance Culvert"},
        {"entity": "IfcCivilElement", "subtype": "*CROSSCULVERT", "desc": "Cross Culvert"},
        {"entity": "IfcCovering", "subtype": "CLADDING", "desc": "Cladding"},
        {"entity": "IfcCovering", "subtype": "*FIRECURTAIN", "desc": "Fire Curtain"},
    ],
    "Lighting Fixtures": [
        {"entity": "IfcLightFixture", "subtype": "", "desc": "Light Fixture"},
        {"entity": "IfcLightFixture", "subtype": "SECURITYLIGHTING", "desc": "Security Lighting"},
    ],
    "Plumbing Fixtures": [
        {"entity": "IfcSanitaryTerminal", "subtype": "BATH", "desc": "Bath"},
        {"entity": "IfcSanitaryTerminal", "subtype": "BIDET", "desc": "Bidet"},
        {"entity": "IfcSanitaryTerminal", "subtype": "SHOWER", "desc": "Shower"},
        {"entity": "IfcSanitaryTerminal", "subtype": "URINAL", "desc": "Urinal"},
        {"entity": "IfcSanitaryTerminal", "subtype": "WASHHANDBASIN", "desc": "Wash Hand Basin"},
        {"entity": "IfcSanitaryTerminal", "subtype": "*WATERCLOSET", "desc": "Water Closet"},
        {"entity": "IfcDistributionChamberElement", "subtype": "INSPECTIONCHAMBER", "desc": "Inspection Chamber"},
        {"entity": "IfcDistributionChamberElement", "subtype": "MANHOLE", "desc": "Manhole"},
        {"entity": "IfcDistributionChamberElement", "subtype": "SUMP", "desc": "Sump"},
        {"entity": "IfcFireSuppressionTerminal", "subtype": "BREECHINGINLET", "desc": "Breeching Inlet"},
        {"entity": "IfcFireSuppressionTerminal", "subtype": "FIREHYDRANT", "desc": "Fire Hydrant"},
    ],
    "Mechanical Equipment": [
        {"entity": "IfcPump", "subtype": "", "desc": "Pump"},
        {"entity": "IfcPump", "subtype": "SUMPPUMP", "desc": "Sump Pump"},
        {"entity": "IfcTank", "subtype": "STORAGE", "desc": "Storage Tank"},
        {"entity": "IfcTank", "subtype": "VESSEL", "desc": "Vessel"},
        {"entity": "IfcFireSuppressionTerminal", "subtype": "HOSEREEL", "desc": "Hose Reel"},
        {"entity": "IfcTransportElement", "subtype": "ESCALATOR", "desc": "Escalator"},
    ],
    "Specialty Equipment": [
        {"entity": "IfcTransportElement", "subtype": "*LIFT", "desc": "Lift/Elevator"},
        {"entity": "IfcTransportElement", "subtype": "*CARLIFT", "desc": "Car Lift"},
    ],
    "Pipes": [
        {"entity": "IfcPipeSegment", "subtype": "RIGIDSEGMENT", "desc": "Rigid Pipe Segment"},
        {"entity": "IfcPipeSegment", "subtype": "GUTTER", "desc": "Gutter"},
        {"entity": "IfcPipeSegment", "subtype": "SPOOL", "desc": "Pipe Spool"},
    ],
    "Pipe Fittings": [
        {"entity": "IfcPipeFitting", "subtype": "", "desc": "Pipe Fitting"},
        {"entity": "IfcPipeFitting", "subtype": "BEND", "desc": "Bend"},
        {"entity": "IfcPipeFitting", "subtype": "JUNCTION", "desc": "Junction"},
    ],
    "Pipe Accessories": [
        {"entity": "IfcValve", "subtype": "ISOLATING", "desc": "Isolating Valve"},
        {"entity": "IfcValve", "subtype": "CHECK", "desc": "Check Valve"},
        {"entity": "IfcFlowMeter", "subtype": "WATERMETER", "desc": "Water Meter"},
    ],
    "Ducts": [
        {"entity": "IfcDuctSegment", "subtype": "", "desc": "Duct Segment"},
    ],
    "Duct Fittings": [
        {"entity": "IfcDuctFitting", "subtype": "", "desc": "Duct Fitting"},
    ],
    "Duct Accessories": [
        {"entity": "IfcDamper", "subtype": "FIREDAMPER", "desc": "Fire Damper"},
        {"entity": "IfcDamper", "subtype": "FIRESMOKEDAMPER", "desc": "Fire Smoke Damper"},
        {"entity": "IfcDamper", "subtype": "SMOKEDAMPER", "desc": "Smoke Damper"},
    ],
    "Topography": [
        {"entity": "IfcGeographicElement", "subtype": "TERRAIN", "desc": "Terrain"},
        {"entity": "IfcGeographicElement", "subtype": "*EXISTINGEARTHWORKS", "desc": "Existing Earthworks"},
        {"entity": "IfcGeographicElement", "subtype": "*PROPOSEDEARTHWORKS", "desc": "Proposed Earthworks"},
    ],
    "Planting": [
        {"entity": "IfcGeographicElement", "subtype": "*LANDSCAPE_TREE", "desc": "Tree"},
        {"entity": "IfcGeographicElement", "subtype": "*LANDSCAPE_PALM", "desc": "Palm"},
        {"entity": "IfcGeographicElement", "subtype": "*LANDSCAPE_SHRUBS", "desc": "Shrubs"},
    ],
}


class ElementData:
    """Class to hold element data for the grid"""
    def __init__(self, element, category, name, current_ifc):
        self.element = element
        self.element_id = element.Id
        self.category = category
        self.name = name
        self.current_ifc = current_ifc
        self.new_ifc = current_ifc  # Will be modified by user
        # What the "New IFC Export As" dropdown shows for this row, e.g.
        # "IfcWall.PARAPET [Parapet Wall]". Kept separately from new_ifc so a
        # filter rebuild can restore the exact dropdown selection.
        self.new_display = None
        self.is_selected = True


# =====================================================================
# Main window XAML - same DQT layout as Family Manager v2.0:
#   gold header + "? Help" / stat cards / white content / action bar / footer
# =====================================================================
MAIN_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="IFC-SG Manual Assign v2.0 - DQT"
        Width="1350" Height="850" MinWidth="1100" MinHeight="640"
        WindowStartupLocation="CenterScreen" Background="#FEF8E7">
  <Window.Resources>
    <Style x:Key="BtnPrimary" TargetType="Button">
      <Setter Property="Background" Value="#F0CC88"/><Setter Property="Foreground" Value="#5D4E37"/>
      <Setter Property="FontWeight" Value="SemiBold"/><Setter Property="Padding" Value="14,8"/>
      <Setter Property="BorderBrush" Value="#D4B87A"/><Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Cursor" Value="Hand"/><Setter Property="FontSize" Value="11"/>
    </Style>
    <Style x:Key="BtnSecondary" TargetType="Button">
      <Setter Property="Background" Value="White"/><Setter Property="Foreground" Value="#5D4E37"/>
      <Setter Property="Padding" Value="10,7"/><Setter Property="BorderBrush" Value="#D4B87A"/>
      <Setter Property="BorderThickness" Value="1"/><Setter Property="Cursor" Value="Hand"/>
      <Setter Property="FontSize" Value="11"/>
    </Style>
    <Style TargetType="DataGridColumnHeader">
      <Setter Property="Background" Value="#F0CC88"/><Setter Property="Foreground" Value="#333"/>
      <Setter Property="FontWeight" Value="SemiBold"/><Setter Property="FontSize" Value="12"/>
      <Setter Property="Padding" Value="8,6"/><Setter Property="BorderBrush" Value="#D4B87A"/>
      <Setter Property="BorderThickness" Value="0,0,1,1"/>
    </Style>
  </Window.Resources>

  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>   <!-- header -->
      <RowDefinition Height="Auto"/>   <!-- stat cards -->
      <RowDefinition Height="Auto"/>   <!-- filters -->
      <RowDefinition Height="Auto"/>   <!-- bulk assign -->
      <RowDefinition Height="*"/>      <!-- grid -->
      <RowDefinition Height="Auto"/>   <!-- action bar -->
      <RowDefinition Height="Auto"/>   <!-- footer -->
    </Grid.RowDefinitions>

    <!-- ============ Header ============ -->
    <Border Grid.Row="0" Background="#F0CC88" CornerRadius="5" Padding="12,8" Margin="0,0,0,10">
      <Grid>
        <StackPanel>
          <TextBlock Text="IFC-SG Manual Assign v2.0" FontSize="17" FontWeight="Bold"/>
          <TextBlock Text="by Dang Quoc Truong (DQT)" FontSize="10" Foreground="#5D4E37"/>
          <TextBlock x:Name="txtSummary" FontSize="11" Foreground="#5D4E37" Margin="0,2,0,0"
                     Text="Assign the IFC export class element by element"/>
        </StackPanel>
        <Button x:Name="btnHelp" Content="? Help" Padding="10,4" Background="White"
                HorizontalAlignment="Right" VerticalAlignment="Center" Cursor="Hand"/>
      </Grid>
    </Border>

    <!-- ============ Stat cards ============ -->
    <Grid Grid.Row="1" Margin="0,0,0,8">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/><ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Border Grid.Column="0" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,5" Margin="0,0,4,0">
        <StackPanel><TextBlock Text="ELEMENTS SHOWN" FontSize="9" Foreground="#666"/>
          <TextBlock x:Name="txtTotal" Text="0" FontSize="20" FontWeight="Bold" Foreground="#2196F3"/></StackPanel></Border>
      <Border Grid.Column="1" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,5" Margin="4,0">
        <StackPanel><TextBlock Text="ASSIGNED" FontSize="9" Foreground="#666"/>
          <TextBlock x:Name="txtAssigned" Text="0" FontSize="20" FontWeight="Bold" Foreground="#4CAF50"/></StackPanel></Border>
      <Border Grid.Column="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,5" Margin="4,0">
        <StackPanel><TextBlock Text="NOT ASSIGNED" FontSize="9" Foreground="#666"/>
          <TextBlock x:Name="txtNotAssigned" Text="0" FontSize="20" FontWeight="Bold" Foreground="#F44336"/></StackPanel></Border>
      <Border Grid.Column="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
              CornerRadius="4" Padding="10,5" Margin="4,0,0,0">
        <StackPanel><TextBlock Text="TICKED FOR CHANGE" FontSize="9" Foreground="#666"/>
          <TextBlock x:Name="txtSelected" Text="0" FontSize="20" FontWeight="Bold" Foreground="#9C27B0"/></StackPanel></Border>
    </Grid>

    <!-- ============ Filters ============ -->
    <Border Grid.Row="2" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
            CornerRadius="4" Padding="10,6" Margin="0,0,0,6">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/><ColumnDefinition Width="220"/>
          <ColumnDefinition Width="Auto"/><ColumnDefinition Width="200"/>
          <ColumnDefinition Width="Auto"/><ColumnDefinition Width="200"/>
          <ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <TextBlock Text="Search (name / ID):" FontSize="11" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox Grid.Column="1" x:Name="txtSearch" FontSize="11" Height="26" VerticalContentAlignment="Center"/>
        <TextBlock Grid.Column="2" Text="Category:" FontSize="11" VerticalAlignment="Center" Margin="12,0,6,0"/>
        <ComboBox Grid.Column="3" x:Name="cmbCategory" FontSize="11" Height="26"/>
        <TextBlock Grid.Column="4" Text="Current IFC:" FontSize="11" VerticalAlignment="Center" Margin="12,0,6,0"/>
        <ComboBox Grid.Column="5" x:Name="cmbIFC" FontSize="11" Height="26"/>
        <Button Grid.Column="7" x:Name="btnClearFilters" Content="Clear Filters"
                Style="{StaticResource BtnSecondary}" Width="100" Margin="8,0,0,0"/>
      </Grid>
    </Border>

    <!-- ============ Bulk assign ============ -->
    <Border Grid.Row="3" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
            CornerRadius="4" Padding="10,6" Margin="0,0,0,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/><ColumnDefinition Width="320"/>
          <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Text="Bulk assign to ticked rows:" FontSize="11" FontWeight="SemiBold"
                   VerticalAlignment="Center" Margin="0,0,8,0"/>
        <ComboBox Grid.Column="1" x:Name="cmbBulk" FontSize="11" Height="26"/>
        <Button Grid.Column="2" x:Name="btnBulkApply" Content="Apply to Ticked"
                Style="{StaticResource BtnPrimary}" Width="120" Margin="8,0,0,0"/>
        <Rectangle Grid.Column="3" Width="1" Fill="#D4B87A" Margin="14,2,14,2"/>
        <Button Grid.Column="4" x:Name="btnSelectAll" Content="Tick All"
                Style="{StaticResource BtnSecondary}" Width="90"/>
        <Button Grid.Column="5" x:Name="btnDeselectAll" Content="Untick All"
                Style="{StaticResource BtnSecondary}" Width="90" Margin="8,0,0,0"/>
        <TextBlock Grid.Column="6" x:Name="txtStatus" FontSize="11" Foreground="#5D4E37"
                   VerticalAlignment="Center" TextTrimming="CharacterEllipsis" Margin="14,0,0,0"/>
      </Grid>
    </Border>

    <!-- ============ Element grid ============ -->
    <DataGrid Grid.Row="4" x:Name="dgElements" AutoGenerateColumns="False"
              CanUserAddRows="False" CanUserDeleteRows="False" CanUserReorderColumns="False"
              CanUserSortColumns="True" HeadersVisibility="Column"
              GridLinesVisibility="Horizontal" AlternatingRowBackground="#FAF6ED"
              RowBackground="White" BorderBrush="#D4B87A" BorderThickness="1"
              FontSize="12" SelectionMode="Extended" SelectionUnit="FullRow"
              VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"
              VirtualizingStackPanel.VirtualizationMode="Standard">
      <DataGrid.Columns>
        <DataGridTemplateColumn Header="Tick" Width="52" SortMemberPath="sel">
          <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
              <CheckBox IsChecked="{Binding sel, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                        HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </DataTemplate>
          </DataGridTemplateColumn.CellTemplate>
        </DataGridTemplateColumn>
        <DataGridTextColumn Header="Element ID" Binding="{Binding eid}" Width="95" IsReadOnly="True"/>
        <DataGridTextColumn Header="Category" Binding="{Binding category}" Width="140" IsReadOnly="True"/>
        <DataGridTextColumn Header="Element Name / Type" Binding="{Binding name}" Width="*" IsReadOnly="True"/>
        <DataGridTextColumn Header="Current IFC Export As" Binding="{Binding current_ifc}" Width="185" IsReadOnly="True"/>
        <DataGridTemplateColumn Header="New IFC Export As" Width="300" SortMemberPath="new_ifc">
          <DataGridTemplateColumn.CellTemplate>
            <DataTemplate>
              <ComboBox ItemsSource="{Binding opts}"
                        SelectedItem="{Binding new_ifc, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                        FontSize="11" Height="24" Margin="1" Background="White"/>
            </DataTemplate>
          </DataGridTemplateColumn.CellTemplate>
        </DataGridTemplateColumn>
      </DataGrid.Columns>
    </DataGrid>

    <!-- ============ Action bar ============ -->
    <Border Grid.Row="5" Background="White" BorderBrush="#D4B87A" BorderThickness="1"
            CornerRadius="4" Padding="8" Margin="0,10,0,0">
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Center">
        <Button x:Name="btnApply" Content="Apply Changes to Revit"
                Style="{StaticResource BtnPrimary}" Width="180"/>
        <Rectangle Width="1" Fill="#D4B87A" Margin="12,2,12,2"/>
        <Button x:Name="btnRefresh" Content="Reload from Revit"
                Style="{StaticResource BtnSecondary}" Width="140"/>
        <Rectangle Width="1" Fill="#D4B87A" Margin="12,2,12,2"/>
        <Button x:Name="btnExport" Content="Export Report (CSV)"
                Style="{StaticResource BtnSecondary}" Width="150"/>
      </StackPanel>
    </Border>

    <!-- ============ Footer ============ -->
    <Grid Grid.Row="6" Margin="0,8,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBlock x:Name="txtHint" FontSize="10" Foreground="#888" VerticalAlignment="Center"
                 TextTrimming="CharacterEllipsis"
                 Text="Tick the rows you want to change, pick a class in 'New IFC Export As', then Apply Changes to Revit."/>
      <TextBlock Grid.Column="1" x:Name="txtCopyright" FontSize="9" Foreground="#999"
                 VerticalAlignment="Center" Margin="12,0,12,0"/>
      <Button Grid.Column="2" x:Name="btnClose" Content="Close"
              Style="{StaticResource BtnSecondary}" Width="80"/>
    </Grid>
  </Grid>
</Window>"""


HELP_TEXT = (
    "IFC-SG Manual Assign\n\n"
    "Assigns the IFC export class element by element, for the elements in the "
    "active view. Use it to fix the handful of elements Auto Assign could not "
    "map, or to override a mapped value.\n\n"
    "STAT CARDS\n"
    "  ELEMENTS SHOWN    - elements passing the current filters\n"
    "  ASSIGNED          - of those, how many already carry an IFC class\n"
    "  NOT ASSIGNED      - of those, how many are still empty\n"
    "  TICKED FOR CHANGE - rows the Apply / bulk buttons will act on\n\n"
    "WORKFLOW\n"
    "  1. Narrow the list with Search, Category and Current IFC\n"
    "  2. Tick the rows you want to change (Tick All / Untick All help)\n"
    "  3. Set the class per row in 'New IFC Export As', or pick one class\n"
    "     and press 'Apply to Ticked' to set it on every ticked row\n"
    "  4. Apply Changes to Revit writes the 'Export to IFC As' parameter\n\n"
    "DROPDOWN VALUES\n"
    "  (Keep Current) - leave this element untouched (the default)\n"
    "  (Clear)        - blank the parameter\n"
    "  everything else comes from the IFC-SG mapping for that category\n\n"
    "NOTES\n"
    "  Filtering never loses your ticks or your dropdown choices - they are\n"
    "  kept per element until you close the window.\n"
    "  Reload from Revit re-reads the current values and resets the choices.\n"
    "  Export Report writes the visible rows to CSV."
)


def _cell_text(row, column):
    """DataRow value as a plain string ('' for null / DBNull)."""
    value = row[column]
    if value is None or value == System.DBNull.Value:
        return ""
    return str(value)


def _cell_bool(row, column):
    """DataRow value as a bool (False for null / DBNull)."""
    value = row[column]
    if value is None or value == System.DBNull.Value:
        return False
    return bool(value)


class ManualAssignWindow(object):
    """WPF window for manual IFC class assignment (DQT gold theme)."""

    def __init__(self, elements_data):
        self.elements_data = elements_data
        self.filtered_data = list(elements_data)
        self._suspend = False          # blocks DataTable events during bulk work
        self._updating = False         # blocks filter events while resetting them
        self._opts_cache = {}          # category -> ObservableCollection[str]

        self.win = _load_xaml(MAIN_XAML)
        for name in ("dgElements", "txtSearch", "cmbCategory", "cmbIFC", "cmbBulk",
                     "btnClearFilters", "btnBulkApply", "btnSelectAll", "btnDeselectAll",
                     "btnApply", "btnRefresh", "btnExport", "btnClose", "btnHelp",
                     "txtTotal", "txtAssigned", "txtNotAssigned", "txtSelected",
                     "txtSummary", "txtStatus", "txtCopyright"):
            setattr(self, name, self.win.FindName(name))

        self.txtCopyright.Text = DQT_FOOTER_TEXT
        self.txtSummary.Text = "{} elements collected from the active view".format(
            len(elements_data))

        self._build_table()
        self._populate_filters()
        self._populate_bulk_combo()
        self._bind_events()
        self._reload_rows()

    # =================================================================
    # Setup
    # =================================================================
    def _build_table(self):
        """Create the DataTable the grid binds to.

        A DataTable is used rather than binding straight to the Python
        objects: it is a plain CLR source, so the checkbox and the per-row
        dropdown bind and write back without any custom notification code.
        """
        self.dt = DataTable()
        self.dt.Columns.Add("sel", clr.GetClrType(System.Boolean))
        self.dt.Columns.Add("eid", clr.GetClrType(System.String))
        self.dt.Columns.Add("category", clr.GetClrType(System.String))
        self.dt.Columns.Add("name", clr.GetClrType(System.String))
        self.dt.Columns.Add("current_ifc", clr.GetClrType(System.String))
        self.dt.Columns.Add("new_ifc", clr.GetClrType(System.String))
        self.dt.Columns.Add("opts", clr.GetClrType(System.Object))
        self.dt.RowChanged += self._on_row_changed
        self.dgElements.ItemsSource = self.dt.DefaultView

    def _populate_filters(self):
        self.cmbCategory.Items.Add("All Categories")
        for cat in sorted(set(e.category for e in self.elements_data)):
            self.cmbCategory.Items.Add(cat)
        self.cmbCategory.SelectedIndex = 0

        self.cmbIFC.Items.Add("All IFC Types")
        self.cmbIFC.Items.Add("(Not Assigned)")
        for ifc in sorted(set(e.current_ifc for e in self.elements_data if e.current_ifc)):
            self.cmbIFC.Items.Add(ifc)
        self.cmbIFC.SelectedIndex = 0

    def _populate_bulk_combo(self):
        self.cmbBulk.Items.Add("-- Select IFC Class --")
        all_options = set()
        for category in IFC_SG_MAPPING:
            for mapping in IFC_SG_MAPPING[category]:
                entity = mapping["entity"]
                subtype = mapping["subtype"]
                if subtype:
                    all_options.add("{}.{}".format(entity, subtype))
                else:
                    all_options.add(entity)
        for option in sorted(all_options):
            self.cmbBulk.Items.Add(option)
        self.cmbBulk.SelectedIndex = 0

    def _bind_events(self):
        self.btnHelp.Click += self._guard(self._on_help)
        self.txtSearch.TextChanged += self._guard(self._on_filter_changed)
        self.cmbCategory.SelectionChanged += self._guard(self._on_filter_changed)
        self.cmbIFC.SelectionChanged += self._guard(self._on_filter_changed)
        self.btnClearFilters.Click += self._guard(self._on_clear_filters)
        self.btnBulkApply.Click += self._guard(self._on_bulk_apply)
        self.btnSelectAll.Click += self._guard(self._on_tick_all)
        self.btnDeselectAll.Click += self._guard(self._on_untick_all)
        self.btnApply.Click += self._guard(self._on_apply_changes)
        self.btnRefresh.Click += self._guard(self._on_refresh)
        self.btnExport.Click += self._guard(self._on_export_report)
        self.btnClose.Click += self._guard(self._on_close)

    def _guard(self, handler):
        """Wrap a handler so one failure shows a message instead of killing
        the window (same pattern as the Subtype Definer)."""
        def wrapper(sender, args):
            try:
                handler(sender, args)
            except Exception as ex:
                WPFMessageBox.Show(
                    "Something went wrong:\n\n{}".format(ex),
                    "Manual Assign", MessageBoxButton.OK, MessageBoxImage.Warning)
        return wrapper

    # =================================================================
    # Grid data
    # =================================================================
    def _options_for(self, category):
        """Dropdown values for a category, shared by every row of it."""
        opts = self._opts_cache.get(category)
        if opts is not None:
            return opts

        opts = ObservableCollection[System.String]()
        opts.Add("(Keep Current)")
        opts.Add("(Clear)")
        for mapping in IFC_SG_MAPPING.get(category, []):
            entity = mapping["entity"]
            subtype = mapping["subtype"]
            desc = mapping["desc"]
            option = "{}.{}".format(entity, subtype) if subtype else entity
            opts.Add("{} [{}]".format(option, desc) if desc else option)
        opts.Add("IfcBuildingElementProxy")
        opts.Add("IfcElement")

        self._opts_cache[category] = opts
        return opts

    def _ensure_option(self, opts, value):
        """Make sure `value` is selectable, so the binding can select it.

        Setting a value the ComboBox does not have would make it fall back to
        no selection and write that emptiness back into the table.
        """
        for item in opts:
            if item == value:
                return value
        opts.Add(value)
        return value

    def _reload_rows(self):
        """Rebuild the grid rows from self.filtered_data."""
        self._suspend = True
        try:
            self.dt.Rows.Clear()
            for ed in self.filtered_data:
                opts = self._options_for(ed.category)
                display = ed.new_display or "(Keep Current)"
                self._ensure_option(opts, display)

                row = self.dt.NewRow()
                row["sel"] = ed.is_selected
                row["eid"] = str(_eid_int(ed.element_id))
                row["category"] = ed.category
                row["name"] = ed.name
                row["current_ifc"] = ed.current_ifc or "(Not Assigned)"
                row["new_ifc"] = display
                row["opts"] = opts
                self.dt.Rows.Add(row)
        finally:
            self._suspend = False
        self._update_stats()

    def _commit_grid(self):
        """Push any half-finished cell edit into the table before reading it."""
        try:
            self.dgElements.CommitEdit(DataGridEditingUnit.Row, True)
        except Exception:
            pass

    def _sync_from_table(self):
        """Copy tick state and dropdown choice back onto the ElementData.

        Rows are added in filtered_data order and only ever cleared as a
        whole, so row i always belongs to filtered_data[i].
        """
        count = min(self.dt.Rows.Count, len(self.filtered_data))
        for i in range(count):
            row = self.dt.Rows[i]
            ed = self.filtered_data[i]
            ed.is_selected = _cell_bool(row, "sel")
            display = _cell_text(row, "new_ifc")
            if display:
                ed.new_display = display
                ed.new_ifc = _strip_desc(display)

    def _on_row_changed(self, sender, args):
        if self._suspend:
            return
        self._sync_from_table()
        self._update_stats()

    def _update_stats(self):
        total = len(self.filtered_data)
        assigned = sum(1 for e in self.filtered_data if e.current_ifc)
        ticked = 0
        for i in range(self.dt.Rows.Count):
            if _cell_bool(self.dt.Rows[i], "sel"):
                ticked += 1
        self.txtTotal.Text = str(total)
        self.txtAssigned.Text = str(assigned)
        self.txtNotAssigned.Text = str(total - assigned)
        self.txtSelected.Text = str(ticked)

    def _ticked_rows(self):
        rows = []
        count = min(self.dt.Rows.Count, len(self.filtered_data))
        for i in range(count):
            row = self.dt.Rows[i]
            if _cell_bool(row, "sel"):
                rows.append((row, self.filtered_data[i]))
        return rows

    # =================================================================
    # Filters
    # =================================================================
    def _on_filter_changed(self, sender, args):
        if self._updating:
            return
        self._apply_filters()

    def _apply_filters(self):
        self._commit_grid()
        self._sync_from_table()          # keep ticks/choices of the rows leaving

        search = (self.txtSearch.Text or "").lower()
        category = self.cmbCategory.SelectedItem
        ifc = self.cmbIFC.SelectedItem

        self.filtered_data = []
        for ed in self.elements_data:
            if search:
                if (search not in (ed.name or "").lower()
                        and search not in str(_eid_int(ed.element_id))):
                    continue
            if category and category != "All Categories" and ed.category != category:
                continue
            if ifc == "(Not Assigned)":
                if ed.current_ifc:
                    continue
            elif ifc and ifc != "All IFC Types" and ed.current_ifc != ifc:
                continue
            self.filtered_data.append(ed)

        self._reload_rows()
        self.txtStatus.Text = "{} of {} elements shown".format(
            len(self.filtered_data), len(self.elements_data))

    def _on_clear_filters(self, sender, args):
        self._updating = True
        try:
            self.txtSearch.Text = ""
            self.cmbCategory.SelectedIndex = 0
            self.cmbIFC.SelectedIndex = 0
        finally:
            self._updating = False
        self._apply_filters()
        self.txtStatus.Text = "Filters cleared."

    # =================================================================
    # Ticking / bulk assignment
    # =================================================================
    def _set_all_ticks(self, state):
        self._commit_grid()
        self._suspend = True
        try:
            for i in range(self.dt.Rows.Count):
                self.dt.Rows[i]["sel"] = state
        finally:
            self._suspend = False
        self._sync_from_table()
        self._update_stats()

    def _on_tick_all(self, sender, args):
        self._set_all_ticks(True)
        self.txtStatus.Text = "Ticked {} rows.".format(self.dt.Rows.Count)

    def _on_untick_all(self, sender, args):
        self._set_all_ticks(False)
        self.txtStatus.Text = "All rows unticked."

    def _on_bulk_apply(self, sender, args):
        selected = self.cmbBulk.SelectedItem
        if not selected or str(selected) == "-- Select IFC Class --":
            WPFMessageBox.Show("Pick an IFC class in the dropdown first.",
                               "Bulk assign", MessageBoxButton.OK,
                               MessageBoxImage.Warning)
            return

        ifc_value = _strip_desc(selected)
        self._commit_grid()
        rows = self._ticked_rows()
        if not rows:
            WPFMessageBox.Show(
                "No rows are ticked. Tick the rows you want to change first.",
                "Bulk assign", MessageBoxButton.OK, MessageBoxImage.Warning)
            return

        self._suspend = True
        try:
            for row, ed in rows:
                opts = self._options_for(ed.category)
                # Prefer the mapping's own wording ("IfcWall [Standard Wall]")
                # so the row reads the same as one assigned by hand.
                display = None
                for item in opts:
                    if _strip_desc(item) == ifc_value:
                        display = item
                        break
                if display is None:
                    display = self._ensure_option(opts, ifc_value)
                row["new_ifc"] = display
                ed.new_display = display
                ed.new_ifc = ifc_value
        finally:
            self._suspend = False

        self._update_stats()
        self.txtStatus.Text = "'{}' set on {} ticked rows.".format(ifc_value, len(rows))

    # =================================================================
    # Apply / refresh / export
    # =================================================================
    def _collect_changes(self):
        """Ticked rows whose chosen class differs from the current one."""
        changes = []
        for row, ed in self._ticked_rows():
            display = _cell_text(row, "new_ifc")
            if not display or display == "(Keep Current)":
                continue
            ifc_value = "" if display == "(Clear)" else _strip_desc(display)
            if ifc_value != (ed.current_ifc or ""):
                changes.append((ed, ifc_value))
        return changes

    def _on_apply_changes(self, sender, args):
        self._commit_grid()
        changes = self._collect_changes()

        if not changes:
            WPFMessageBox.Show(
                "Nothing to apply.\n\nTicked rows are either set to "
                "'(Keep Current)' or already carry the chosen class.",
                "Manual Assign", MessageBoxButton.OK, MessageBoxImage.Information)
            return

        answer = WPFMessageBox.Show(
            "Apply the IFC class to {} element(s)?\n\n"
            "This writes the 'Export to IFC As' parameter.".format(len(changes)),
            "Confirm changes", MessageBoxButton.YesNo, MessageBoxImage.Question)
        if answer != MessageBoxResult.Yes:
            return

        success = 0
        errors = []
        # The Revit API transaction is used directly: pyrevit's wrapper takes
        # (name, doc), so the old (doc, name) call could never start.
        txn = DB.Transaction(doc, "DQT - Manual IFC Assignment")
        txn.Start()
        try:
            try:
                opts = txn.GetFailureHandlingOptions()
                opts.SetFailuresPreprocessor(_SilentFailures())
                opts.SetClearAfterRollback(True)
                txn.SetFailureHandlingOptions(opts)
            except Exception:
                pass

            for ed, ifc_value in changes:
                try:
                    element = ed.element
                    param = element.LookupParameter("Export to IFC As")
                    if param is None:
                        param = element.LookupParameter("IfcExportAs")
                    if param is None:
                        param = element.get_Parameter(
                            DB.BuiltInParameter.IFC_EXPORT_ELEMENT_AS)

                    if param and not param.IsReadOnly:
                        param.Set(ifc_value if ifc_value else "")
                        success += 1
                    else:
                        errors.append("Element {} - parameter missing or read-only".format(
                            _eid_int(element.Id)))
                except Exception as ex:
                    errors.append("Element {} - {}".format(_eid_int(ed.element_id), ex))

            txn.Commit()
        except Exception:
            if txn.HasStarted():
                txn.RollBack()
            raise

        message = "Assignment complete.\n\nAssigned: {}\nFailed: {}".format(
            success, len(errors))
        if errors:
            message += "\n\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                message += "\n... and {} more".format(len(errors) - 10)

        WPFMessageBox.Show(
            message, "Results", MessageBoxButton.OK,
            MessageBoxImage.Information if not errors else MessageBoxImage.Warning)

        self.txtStatus.Text = "Applied to {} element(s).".format(success)
        self._refresh_current_ifc()

    def _refresh_current_ifc(self):
        """Re-read the parameter from Revit and reset the pending choices."""
        for ed in self.elements_data:
            ed.current_ifc = GetCurrentIFCExport(ed.element)
            ed.new_ifc = ed.current_ifc
            ed.new_display = None
        self._reload_rows()

    def _on_refresh(self, sender, args):
        self._refresh_current_ifc()
        self.txtStatus.Text = "Reloaded current values from Revit."

    def _on_export_report(self, sender, args):
        dialog = SaveFileDialog()
        dialog.Filter = "CSV Files (*.csv)|*.csv|Text Files (*.txt)|*.txt"
        dialog.FileName = "IFC_Assignment_Report.csv"
        if dialog.ShowDialog() != WFDialogResult.OK:
            return

        self._commit_grid()
        filepath = dialog.FileName
        try:
            with open(filepath, "w") as handle:
                handle.write("Ticked,Element ID,Category,Element Name,Current IFC,New IFC\n")
                count = min(self.dt.Rows.Count, len(self.filtered_data))
                for i in range(count):
                    row = self.dt.Rows[i]
                    values = [_cell_text(row, column).replace(",", ";")
                              for column in ("sel", "eid", "category", "name",
                                             "current_ifc", "new_ifc")]
                    handle.write(",".join(values) + "\n")
            WPFMessageBox.Show("Report saved to:\n{}".format(filepath),
                               "Export complete", MessageBoxButton.OK,
                               MessageBoxImage.Information)
            self.txtStatus.Text = "Report exported."
        except Exception as ex:
            WPFMessageBox.Show("Could not write the report:\n\n{}".format(ex),
                               "Export failed", MessageBoxButton.OK,
                               MessageBoxImage.Error)

    def _on_help(self, sender, args):
        WPFMessageBox.Show(HELP_TEXT, "Manual Assign - Help",
                           MessageBoxButton.OK, MessageBoxImage.Information)

    def _on_close(self, sender, args):
        self.win.Close()

    def show(self):
        self.win.ShowDialog()


def GetCurrentIFCExport(element):
    """Get current IFC Export As parameter value"""
    try:
        # Try Revit 2024+ parameter name first
        param = element.LookupParameter("Export to IFC As")
        
        if param is None:
            # Try Revit 2019-2023 parameter name
            param = element.LookupParameter("IfcExportAs")
        
        if param is None:
            # Fallback to built-in parameter (always works)
            param = element.get_Parameter(DB.BuiltInParameter.IFC_EXPORT_ELEMENT_AS)
        
        if param and param.HasValue:
            return param.AsString()
    except:
        pass
    
    return None


def GetElementName(element):
    """Get element name or type name"""
    try:
        # Try to get element name
        name_param = element.get_Parameter(DB.BuiltInParameter.ELEM_NAME_PARAM)
        if name_param and name_param.HasValue:
            name = name_param.AsString()
            if name:
                return name
        
        # Try to get type name
        elem_type_id = element.GetTypeId()
        if elem_type_id != DB.ElementId.InvalidElementId:
            elem_type = doc.GetElement(elem_type_id)
            if elem_type:
                type_name = elem_type.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                if type_name and type_name.HasValue:
                    return type_name.AsString()
        
        # Fallback to family and type
        if hasattr(element, 'Name'):
            return element.Name
            
    except:
        pass
    
    return "Unnamed Element"


def CollectElements():
    """Collect all relevant elements from the document"""
    output = script.get_output()
    output.print_md("## Collecting Elements from Active View...")
    
    # Categories to include
    categories_to_include = [
        DB.BuiltInCategory.OST_Walls,
        DB.BuiltInCategory.OST_Floors,
        DB.BuiltInCategory.OST_Roofs,
        DB.BuiltInCategory.OST_Ceilings,
        DB.BuiltInCategory.OST_Doors,
        DB.BuiltInCategory.OST_Windows,
        DB.BuiltInCategory.OST_Columns,
        DB.BuiltInCategory.OST_StructuralColumns,
        DB.BuiltInCategory.OST_StructuralFraming,
        DB.BuiltInCategory.OST_StructuralFoundation,
        DB.BuiltInCategory.OST_Stairs,
        DB.BuiltInCategory.OST_Ramps,
        DB.BuiltInCategory.OST_Railings,
        DB.BuiltInCategory.OST_Rooms,
        DB.BuiltInCategory.OST_Areas,
        DB.BuiltInCategory.OST_GenericModel,
        DB.BuiltInCategory.OST_Furniture,
        DB.BuiltInCategory.OST_LightingFixtures,
        DB.BuiltInCategory.OST_PlumbingFixtures,
        DB.BuiltInCategory.OST_MechanicalEquipment,
        DB.BuiltInCategory.OST_SpecialityEquipment,
        DB.BuiltInCategory.OST_PipeCurves,
        DB.BuiltInCategory.OST_PipeFitting,
        DB.BuiltInCategory.OST_PipeAccessory,
        DB.BuiltInCategory.OST_DuctCurves,
        DB.BuiltInCategory.OST_DuctFitting,
        DB.BuiltInCategory.OST_DuctAccessory,
        DB.BuiltInCategory.OST_Topography,
        DB.BuiltInCategory.OST_Planting,
        DB.BuiltInCategory.OST_CurtainWallPanels,
    ]
    
    # Create multi-category filter
    cat_filters = [DB.ElementCategoryFilter(cat) for cat in categories_to_include]
    multi_filter = DB.LogicalOrFilter(List[DB.ElementFilter](cat_filters))
    
    # Collect elements
    collector = DB.FilteredElementCollector(doc, doc.ActiveView.Id)
    elements = collector.WherePasses(multi_filter).WhereElementIsNotElementType().ToElements()
    
    output.print_md("Found **{}** elements in active view".format(len(elements)))
    
    # Create ElementData objects
    elements_data = []
    
    for elem in elements:
        try:
            category = elem.Category.Name if elem.Category else "Unknown"
            name = GetElementName(elem)
            current_ifc = GetCurrentIFCExport(elem)
            
            elem_data = ElementData(elem, category, name, current_ifc)
            elements_data.append(elem_data)
        except:
            continue
    
    output.print_md("Prepared **{}** elements for assignment".format(len(elements_data)))
    
    return elements_data


# Main execution
if __name__ == '__main__':
    output = script.get_output()
    
    output.print_md("# IFC-SG Manual Assignment Tool")
    output.print_md("---")
    
    # Collect elements
    elements_data = CollectElements()
    
    if len(elements_data) == 0:
        forms.alert("No elements found in active view. Please open a view with elements and try again.",
                   exitscript=True)
    
    # Show statistics
    output.print_md("## Statistics")
    categories = {}
    assigned = 0
    not_assigned = 0
    
    for elem_data in elements_data:
        # Count by category
        if elem_data.category not in categories:
            categories[elem_data.category] = 0
        categories[elem_data.category] += 1
        
        # Count assigned/not assigned
        if elem_data.current_ifc:
            assigned += 1
        else:
            not_assigned += 1
    
    output.print_md("- **Total Elements:** {}".format(len(elements_data)))
    output.print_md("- **Currently Assigned:** {}".format(assigned))
    output.print_md("- **Not Assigned:** {}".format(not_assigned))
    output.print_md("")
    output.print_md("### By Category:")
    for cat in sorted(categories.keys()):
        output.print_md("- {}: **{}**".format(cat, categories[cat]))
    
    output.print_md("---")
    output.print_md("Opening assignment interface...")
    
    # Show form
    ManualAssignWindow(elements_data).show()
    
    output.print_md("## Complete!")
    output.print_md("Tool execution finished.")