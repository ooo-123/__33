from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QComboBox, QLineEdit, QPushButton, QFrame, 
                             QButtonGroup, QGroupBox, QSizePolicy, QSpacerItem, QMessageBox,
                             QDesktopWidget, QCheckBox)
from PyQt5.QtCore import QThread, pyqtSignal

from pglive.kwargs import Axis
from pglive.sources.data_connector import DataConnector
from pglive.sources.live_axis import LiveAxis
from pglive.sources.live_plot import LiveLinePlot
from pglive.sources.live_plot_widget import LivePlotWidget
from collections import deque 
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont, QIcon
from datetime import datetime
import numpy as np
import pyqtgraph as pg
#---- GUI ----

import sys
import time
import argparse
import fx # Custom module for Bloomberg data
try:
    from pricefeed_with_failover import PriceFeedWithFailover
    websocket_sim_available = True
except ImportError:
    try:
        from simulation.pricefeed_sim import PriceFeedSim
        # Create a wrapper to use old PriceFeedSim with failover name
        PriceFeedWithFailover = PriceFeedSim
        websocket_sim_available = True
    except ImportError:
        websocket_sim_available = False
        print("⚠️  WebSocket simulator not available. Install with: pip install websockets")
from threading import Thread
from debug_monitor import init_debug_monitor, get_debug_monitor
from pip_value_calculator import PipValueCalculator

try:
    from voice.voice_announcer_v3 import VoiceAnnouncerV3
    voice_available = True
except ImportError:
    voice_available = False
    print("⚠️  Voice announcer not available. Install pygame if you want voice features.")

from trade_calculator import TradeCalculatorWidget


class MyApp(QWidget):
    def format_order_size(self, size):
        """Format order size for display (e.g., 1000 -> 1k, 1000000 -> 1M)"""
        if size >= 1_000_000_000:  # Billions
            formatted = f"{size/1_000_000_000:.1f}B"
            # Remove trailing .0
            if formatted.endswith('.0B'):
                return formatted[:-3] + 'B'
            return formatted
        elif size >= 1_000_000:  # Millions
            formatted = f"{size/1_000_000:.1f}M"
            # Remove trailing .0
            if formatted.endswith('.0M'):
                return formatted[:-3] + 'M'
            return formatted
        elif size >= 1_000:  # Thousands
            formatted = f"{size/1_000:.1f}k"
            # Remove trailing .0
            if formatted.endswith('.0k'):
                return formatted[:-3] + 'k'
            return formatted
        else:
            return str(int(size))
    
    def parse_order_size(self, text):
        """Parse formatted order size text to numeric value"""
        text = text.strip().upper()
        if not text:
            return 0
        
        try:
            # Handle suffixes
            if text.endswith('K'):
                return float(text[:-1]) * 1_000
            elif text.endswith('M'):
                return float(text[:-1]) * 1_000_000
            elif text.endswith('B'):
                return float(text[:-1]) * 1_000_000_000
            else:
                # Try to parse as regular number
                return float(text)
        except ValueError:
            return 0
    
    def __init__(self, args=None):
        super().__init__()
        self.args = args or argparse.Namespace()
        
        # Initialize debug monitor
        self.debug_monitor = get_debug_monitor()
        
        # Debug printing flag - set to False to disable UI action prints if they slow down the application
        self.debug_ui_actions = True
        
        # Voice announcer initialization
        if voice_available:
            voice_speed = getattr(self.args, 'voice_speed', 1.5)
            self.voice_announcer = VoiceAnnouncerV3(speed_multiplier=voice_speed)
            self.voice_enabled = False
        else:
            self.voice_announcer = None
            self.voice_enabled = False
        
        # Trade calculator initialization
        self.trade_calculator = None  # Will be created lazily when first shown
        self.trade_calc_visible = False
        
        # Currency to flag emoji mapping
        self.currency_flags = {
            'USD': '🇺🇸',
            'EUR': '🇪🇺',
            'GBP': '🇬🇧',
            'JPY': '🇯🇵',
            'AUD': '🇦🇺',
            'NZD': '🇳🇿',
            'CAD': '🇨🇦',
            'CHF': '🇨🇭',
            'SGD': '🇸🇬',
            'NOK': '🇳🇴',
            'SEK': '🇸🇪',
            'CNH': '🇨🇳',
            'HKD': '🇭🇰',
            'PLN': '🇵🇱',
            'DKK': '🇩🇰'
        }

        # Modern window setup and styling
        self.apply_modern_styling()
        
        # Main layout - structured with controls on top, graph at bottom
        self.layout = QGridLayout(self)
        # Set column stretch factors for controls area
        self.layout.setColumnStretch(0, 1)  # Left control column
        self.layout.setColumnStretch(1, 1)  # Control column
        self.layout.setColumnStretch(2, 1)  # Center control column 
        self.layout.setColumnStretch(3, 1)  # Main control column
        self.layout.setColumnStretch(4, 1)  # Control column
        self.layout.setColumnStretch(5, 1)  # Control column
        self.layout.setColumnStretch(6, 1)  # Right control column
        
        # Keep layout spacing compact
        self.layout.setHorizontalSpacing(5)
        self.layout.setVerticalSpacing(2)

        self.setWindowIcon(QIcon(r'Resources\fxicon.png'))

        # Window dimensions for different graph states
        self.window_width_with_graph = 800   # Standard width - graph is now at bottom
        self.window_height_with_graph = 830  # Increased height to accommodate cross help text below bid/offer labels
        self.window_width_without_graph = 680  # Standard width when graph is hidden  
        self.window_height_without_graph = 630  # Increased height for cross help text

        self.inverse_bool_active = False
        self.graph_visible = False  # Start with graph hidden by default
        
        # Timestamp display in top left
        self.timestamp_label = QLabel("--:--:--", self)
        self.timestamp_label.setFont(QFont('Arial', 11, QFont.Bold))
        self.timestamp_label.setStyleSheet("""
            QLabel {
                color: #e8e8e8;
                background-color: #2b2b2b;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        self.last_update_timestamp = None
        
        # Data source indicator
        self.data_source_frame = QFrame(self)
        self.data_source_frame.setFrameStyle(QFrame.Box)
        self.data_source_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #444444;
                border-radius: 6px;
                background-color: #2b2b2b;
                padding: 2px;
            }
        """)
        
        self.data_source_layout = QHBoxLayout(self.data_source_frame)
        self.data_source_layout.setContentsMargins(8, 4, 8, 4)
        self.data_source_layout.setSpacing(8)
        
        # Status icon and label
        self.data_source_icon = QLabel("●", self)
        self.data_source_icon.setFont(QFont('Arial', 14, QFont.Bold))
        
        # Removed heartbeat indicator - using only colored circles for status
        
        self.data_source_label = QLabel("Data:", self)
        self.data_source_label.setFont(QFont('Arial', 9, QFont.Bold))
        self.data_source_label.setStyleSheet("color: #b0b0b0;")
        
        self.data_source_status = QLabel("", self)
        self.data_source_status.setFont(QFont('Arial', 9))
        
        # Data source selector dropdown
        self.source_selector_label = QLabel("Switch:", self)
        self.source_selector_label.setFont(QFont('Arial', 9))
        self.source_selector_label.setStyleSheet("color: #b0b0b0;")
        
        self.source_selector = QComboBox(self)
        self.source_selector.setFixedWidth(100)
        self.source_selector.setFont(QFont('Arial', 9))
        self.source_selector.addItems(["Bloomberg", "WebSocket", "Simulation"])
        self.source_selector.setCurrentText("Bloomberg")  # Default to Bloomberg
        self.source_selector.setEnabled(True)  # Ensure dropdown is always enabled
        self.source_selector.currentTextChanged.connect(self.switch_data_source)
        self.source_selector.setStyleSheet("""
            QComboBox {
                background-color: #2b2b2b;
                color: #e8e8e8;
                border: 1px solid #444;
                padding: 2px 4px;
                border-radius: 4px;
            }
            QComboBox:hover {
                border-color: #666;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #e8e8e8;
                margin-right: 4px;
            }
        """)
        
        # Reconnect button (for retrying current source)
        self.reconnect_button = QPushButton("Reconnect", self)
        self.reconnect_button.setFixedWidth(80)
        self.reconnect_button.setFont(QFont('Arial', 9))
        self.reconnect_button.clicked.connect(self.reconnect_current_source)
        self.reconnect_button.setVisible(False)  # Hidden initially
        self.reconnect_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #e8e8e8;
                border: 1px solid #555;
                padding: 3px 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4a4a5a;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #2a2a3a;
            }
        """)
        
        # Add widgets to layout
        self.data_source_layout.addWidget(self.data_source_icon)
        self.data_source_layout.addWidget(self.data_source_label)
        self.data_source_layout.addWidget(self.data_source_status)
        self.data_source_layout.addStretch()
        self.data_source_layout.addWidget(self.source_selector_label)
        self.data_source_layout.addWidget(self.source_selector)
        self.data_source_layout.addWidget(self.reconnect_button)
        self.graph_expanded = False  # Start in compact mode by default

        self.setGeometry(100, 100, self.window_width_without_graph, self.window_height_without_graph)
        self.setWindowTitle('SPOT Pricer & Alpha signals')
        # changing the background color to white
        # self.setStyleSheet("background-color: Black;")
        
        # Initialize with graph hidden
        self.graph_visible = False

        #=============================== GRAPHING ===============================
        # Create one curve per dataset with professional styling
        bid_plot = LiveLinePlot(pen=pg.mkPen(color='#4a90e2', width=2.5, style=Qt.SolidLine))
        offer_plot = LiveLinePlot(pen=pg.mkPen(color='#ff9f40', width=2.5, style=Qt.SolidLine))

        # Create one curve per dataset
        my_bid_plot = LiveLinePlot(pen=pg.mkPen(color='#ff5252', width=2, style=Qt.DashLine))
        my_offer_plot = LiveLinePlot(pen=pg.mkPen(color='#4CAF50', width=2, style=Qt.DashLine))

        self.deque_live_chart_max = 100

        # Data connectors for each plot with dequeue of 100 points
        self.bid_connector = DataConnector(bid_plot, max_points=self.deque_live_chart_max)
        self.offer_connector = DataConnector(offer_plot, max_points=self.deque_live_chart_max)
        # Data connectors for each plot with dequeue of 100 points
        self.my_bid_connector = DataConnector(my_bid_plot, max_points=self.deque_live_chart_max)
        self.my_offer_connector = DataConnector(my_offer_plot, max_points=self.deque_live_chart_max)
        self.rsi_connector = DataConnector(my_offer_plot, max_points=self.deque_live_chart_max)

        # self.current_ccy_deque = deque(maxlen=self.deque_live_chart_max)

        # Setup bottom axis with TIME tick format
        # You can use Axis.DATETIME to show date as well
        bottom_axis = LiveAxis("bottom", **{Axis.TICK_FORMAT: Axis.TIME})

        # Create plot itself - positioned on left side
        self.chart_view = LivePlotWidget(title="", axisItems={'bottom': bottom_axis})
        
        # Professional dark theme styling for the graph
        self.chart_view.setBackground('#1e1e1e')
        self.chart_view.getPlotItem().getAxis('left').setPen(pg.mkPen('#666666', width=1))
        self.chart_view.getPlotItem().getAxis('bottom').setPen(pg.mkPen('#666666', width=1))
        self.chart_view.getPlotItem().getAxis('left').setTextPen('#999999')
        self.chart_view.getPlotItem().getAxis('bottom').setTextPen('#999999')
        self.chart_view.showGrid(x=True, y=True, alpha=0.2)
        
        # Size the chart appropriately for bottom positioning - full width, moderate height
        self.chart_view.setMinimumSize(400, 200)  # Full width at bottom, moderate height
        self.chart_view.setMaximumSize(2000, 300)  # Allow full width expansion, limit height
        
        # Show grid
        self.chart_view.showGrid(x=True, y=True, alpha=0.3)
        # Set labels with professional styling
        self.chart_view.setLabel('bottom', 'Time', units="s", **{'color': '#999999', 'font-size': '10pt'})
        self.chart_view.setLabel('left', 'Price', **{'color': '#999999', 'font-size': '10pt'})
        
        # Make axis labels and title more readable
        axis_font = QFont('Arial', 9)
        self.chart_view.getAxis('bottom').setStyle(tickFont=axis_font)
        self.chart_view.getAxis('left').setStyle(tickFont=axis_font)
        
        # Add a title with the currency pair
        self.chart_view.setTitle('', color='#ffffff', size='12pt')

        # Add all curves
        self.chart_view.addItem(bid_plot)
        self.chart_view.addItem(offer_plot)
        self.chart_view.addItem(my_bid_plot)
        self.chart_view.addItem(my_offer_plot)
        
        

       
        

        #=============================== GRAPHING ===============================
       
        

        # Create pricing instance
        self.pricing_obj = fx.pricing()
        # Create an instance of the bloomberg bbg class
        self.bb_obj = fx.bbg(self.pricing_obj)
        # Create pip value calculator instance
        self.pip_calculator = PipValueCalculator()
        self.order_size = self.bb_obj.order_size

        
        
        # Combo box
        self.combo_ccy = QComboBox(self)
        # Use dark theme styling from apply_modern_styling()
        combo_box_ccy_list = self.pricing_obj.ccys
        combo_box_ccy_list.append('CROSS')
        self.combo_ccy.addItems(combo_box_ccy_list)
        # self.combo_ccy.move(150, 10)
        self.combo_ccy.currentIndexChanged.connect(self.update_label)

        # Spread matrix label
        self.spread_matrix_label = QLabel(self)
        self.spread_matrix_label.setText("Spread Matrix:")
        self.spread_matrix_label.setStyleSheet("""
            QLabel {
                color: #e8e8e8;
                font-weight: bold;
                font-size: 12px;
            }
        """)

        # Combo box - Matrix Choice
        self.combo_choose_spread_matrix = QComboBox(self)
        # Use dark theme styling from apply_modern_styling()
        self.combo_choose_spread_matrix.addItems(self.pricing_obj.spread_matrix_choices)
        self.combo_choose_spread_matrix.currentIndexChanged.connect(self.update_current_spread_matrix)
        
        # Apply initial styling
        self.combo_choose_spread_matrix.setStyleSheet("""
            QComboBox {
                background-color: #2b2b2b;
                color: #e8e8e8;
                border: 1px solid #555;
                padding: 4px;
                border-radius: 4px;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #777;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #e8e8e8;
                margin-right: 5px;
            }
        """)

        self.prior_text_ccy_typing_input = ''

        # Add a label for flags above the currency combo box
        self.flags_label = QLabel("Flags: 🇦🇺 🇺🇸", self)  # Default is AUDUSD
        self.flags_label.setFont(QFont('Arial', 10, QFont.Bold))
        self.flags_label.setStyleSheet("color: #ffd700; font-weight: bold;")

        self.lhs_help = QLabel(self)
        self.lhs_help.setText("Bid LHS Yours Give, Customer sells, Sell higherr ↑")
        self.lhs_help.setFont(QFont('Arial', 9))
        self.lhs_help.setStyleSheet("color: #e8e8e8;")

        self.rhs_help = QLabel(self)
        self.rhs_help.setText("Offer RHS Mine Take Paying you, Customer Buys, Buy back Lower  ↓ ")
        self.rhs_help.setFont(QFont('Arial', 9))
        self.rhs_help.setStyleSheet("color: #e8e8e8;")

        self.cross_help_amount_lhs = QLabel(self)
        self.cross_help_amount_lhs.setText("")
        self.cross_help_amount_lhs.setFont(QFont('Arial', 9, QFont.Bold))
        self.cross_help_amount_lhs.setStyleSheet("""
            QLabel {
                color: #51cf66;
                background-color: rgba(81, 207, 102, 0.15);
                border: 1px solid rgba(81, 207, 102, 0.3);
                border-radius: 3px;
                padding: 3px 6px;
            }
        """)
        self.cross_help_amount_lhs.setMinimumHeight(25)
        self.cross_help_amount_lhs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cross_help_amount_lhs.setWordWrap(False)
        self.cross_help_amount_lhs.setAlignment(Qt.AlignCenter)
        self.cross_help_amount_lhs.setVisible(False)  # Initially hidden

        self.cross_help_amount_rhs = QLabel(self)
        self.cross_help_amount_rhs.setText("")
        self.cross_help_amount_rhs.setFont(QFont('Arial', 9, QFont.Bold))
        self.cross_help_amount_rhs.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                background-color: rgba(255, 107, 107, 0.15);
                border: 1px solid rgba(255, 107, 107, 0.3);
                border-radius: 3px;
                padding: 3px 6px;
            }
        """)
        self.cross_help_amount_rhs.setMinimumHeight(25)
        self.cross_help_amount_rhs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cross_help_amount_rhs.setWordWrap(False)
        self.cross_help_amount_rhs.setAlignment(Qt.AlignCenter)
        self.cross_help_amount_rhs.setVisible(False)  # Initially hidden
       

        # Order size input
        self.order_size_input = QLineEdit(self)
        # Use dark theme styling from apply_modern_styling()
        self.order_size_input.setText(self.format_order_size(self.bb_obj.order_size))
        self.order_size_input.textChanged.connect(self.update_order_size)

        self.order_size_input.mousePressEvent = self.clickLine_amount

        # CCY txt writing input
        self.ccy_typing_input = QLineEdit(self)
        # Use dark theme styling from apply_modern_styling()
        self.ccy_typing_input.setFixedWidth(100)  # Wider to show full currency pairs like AUDUSD
        self.ccy_typing_input.setText(str(""))
        self.ccy_typing_input.setPlaceholderText("Type CCY")
        self.ccy_typing_input.textChanged.connect(self.typing_ccy_change)
        self.ccy_typing_input.mousePressEvent = self.clickLine
        self.ccy_typing_input.setFont(QFont('Arial', 11))
        self.ccy_typing_input.setToolTip("Type 6-letter currency pair (e.g., EURUSD, GBPJPY)")
        
        # Style the input field for better visibility
        self.ccy_typing_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #4a4a4a;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
                font-weight: bold;
            }
            QLineEdit:focus {
                border: 2px solid #0d6efd;
                background-color: #333333;
            }
            QLineEdit::placeholder {
                color: #808080;
            }
        """)

        # Create compact vertical container for high/low display
        self.high_low_container = QFrame(self)
        self.high_low_container.setFrameStyle(QFrame.Box)
        self.high_low_container.setMaximumHeight(48)  # Slightly taller for readability
        self.high_low_container.setMaximumWidth(320)  # Limit width to match content
        self.high_low_container.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 3px;
                padding: 2px;
            }
        """)
        
        # Main horizontal layout with 3 columns
        self.high_low_layout = QHBoxLayout(self.high_low_container)
        self.high_low_layout.setSpacing(0)
        self.high_low_layout.setContentsMargins(0, 0, 0, 0)
        
        # LEFT COLUMN: Vertically stacked HIGH and LOW
        self.hl_vertical_section = QFrame()
        self.hl_vertical_section.setStyleSheet("""
            QFrame {
                background-color: #0a0a0a;
                border: none;
                border-right: 1px solid #2a2a2a;
            }
        """)
        self.hl_vertical_section.setFixedWidth(160)  # Fixed width for consistent layout
        hl_vertical_layout = QVBoxLayout(self.hl_vertical_section)
        hl_vertical_layout.setSpacing(0)
        hl_vertical_layout.setContentsMargins(0, 1, 0, 1)
        
        # HIGH row with grid layout for better alignment
        self.high_widget = QWidget()
        self.high_widget.setStyleSheet("background: transparent;")
        high_layout = QGridLayout(self.high_widget)
        high_layout.setSpacing(2)
        high_layout.setContentsMargins(2, 1, 2, 1)
        
        # H label in dedicated column
        self.high_label = QLabel("H")
        self.high_label.setFont(QFont('Arial', 10, QFont.Bold))
        self.high_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.high_label.setFixedWidth(15)
        self.high_label.setAlignment(Qt.AlignCenter)
        
        # Price value
        self.high_value_label = QLabel("-.----")
        self.high_value_label.setFont(QFont('Courier', 9, QFont.Bold))
        self.high_value_label.setStyleSheet("color: #ffffff;")
        self.high_value_label.setFixedWidth(55)
        
        # Distance label
        self.high_distance_label = QLabel("--p --%")
        self.high_distance_label.setFont(QFont('Arial', 8))
        self.high_distance_label.setStyleSheet("color: #999999;")
        
        high_layout.addWidget(self.high_label, 0, 0)
        high_layout.addWidget(self.high_value_label, 0, 1)
        high_layout.addWidget(self.high_distance_label, 0, 2)
        high_layout.setColumnStretch(2, 1)  # Let distance label expand
        
        # LOW row with grid layout for better alignment
        self.low_widget = QWidget()
        self.low_widget.setStyleSheet("background: transparent;")
        low_layout = QGridLayout(self.low_widget)
        low_layout.setSpacing(2)
        low_layout.setContentsMargins(2, 1, 2, 1)
        
        # L label in dedicated column
        self.low_label = QLabel("L")
        self.low_label.setFont(QFont('Arial', 10, QFont.Bold))
        self.low_label.setStyleSheet("color: #FF6B6B; font-weight: bold;")
        self.low_label.setFixedWidth(15)
        self.low_label.setAlignment(Qt.AlignCenter)
        
        # Price value
        self.low_value_label = QLabel("-.----")
        self.low_value_label.setFont(QFont('Courier', 9, QFont.Bold))
        self.low_value_label.setStyleSheet("color: #ffffff;")
        self.low_value_label.setFixedWidth(55)
        
        # Distance label
        self.low_distance_label = QLabel("--p --%")
        self.low_distance_label.setFont(QFont('Arial', 8))
        self.low_distance_label.setStyleSheet("color: #999999;")
        
        low_layout.addWidget(self.low_label, 0, 0)
        low_layout.addWidget(self.low_value_label, 0, 1)
        low_layout.addWidget(self.low_distance_label, 0, 2)
        low_layout.setColumnStretch(2, 1)  # Let distance label expand
        
        hl_vertical_layout.addWidget(self.high_widget)
        hl_vertical_layout.addWidget(self.low_widget)
        
        # MIDDLE COLUMN: H-L Range
        self.range_section = QFrame()
        self.range_section.setStyleSheet("""
            QFrame {
                background-color: #0a0a0a;
                border: none;
                border-right: 1px solid #2a2a2a;
            }
        """)
        self.range_section.setFixedWidth(80)  # Fixed width
        range_layout = QVBoxLayout(self.range_section)
        range_layout.setSpacing(0)
        range_layout.setContentsMargins(2, 2, 2, 2)
        
        self.range_title_label = QLabel("H-L Range")
        self.range_title_label.setFont(QFont('Arial', 7))
        self.range_title_label.setStyleSheet("color: #888888;")
        self.range_title_label.setAlignment(Qt.AlignCenter)
        
        self.range_label = QLabel("--")
        self.range_label.setFont(QFont('Arial', 9, QFont.Bold))
        self.range_label.setStyleSheet("color: #cccccc;")
        self.range_label.setAlignment(Qt.AlignCenter)
        
        range_layout.addWidget(self.range_title_label)
        range_layout.addWidget(self.range_label)
        
        # RIGHT COLUMN: Trading Bias
        self.bias_section = QFrame()
        self.bias_section.setStyleSheet("""
            QFrame {
                background-color: #0a0a0a;
                border: none;
            }
        """)
        self.bias_section.setFixedWidth(70)  # Fixed width
        bias_layout = QVBoxLayout(self.bias_section)
        bias_layout.setSpacing(0)
        bias_layout.setContentsMargins(2, 8, 2, 8)
        
        self.bias_label = QLabel("")
        self.bias_label.setFont(QFont('Arial', 9, QFont.Bold))
        self.bias_label.setStyleSheet("color: #ffaa00;")
        self.bias_label.setAlignment(Qt.AlignCenter)
        
        bias_layout.addWidget(self.bias_label)
        
        # Add all sections to main layout
        self.high_low_layout.addWidget(self.hl_vertical_section)
        self.high_low_layout.addWidget(self.range_section)
        self.high_low_layout.addWidget(self.bias_section)
        self.high_low_layout.addStretch()  # Push everything to the left 

         # BIDS
        self.pre_hedge_tittle = QLabel(self)
        self.pre_hedge_tittle.setText("Pre_Hedge: ")
       

        # BIDS
        self.bid_tittle = QLabel(self)
        # self.bid_tittle.setGeometry(20, 30, 50, 50)
        # self.bid_tittle.setAlignment(Qt.AlignCenter)
        self.bid_tittle.setText("Bid: ")

        self.bid_label = QLabel(self)
        self.bid_label.setAlignment(Qt.AlignCenter)
        self.bid_label.setFont(QFont('Arial', 14, QFont.Bold))
        self.bid_label.setProperty('class', 'bid-label')
        self.bid_label.setMinimumWidth(190)  # Increased for 6 decimals on JPY-base
        self.bid_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 6px;
                padding: 10px;
                color: #ffffff;
            }
        """)

   

        self.bid_pips_label= QLabel(self)
        # self.bid_pips_label.setGeometry(50, 120, 120, 50)
        # self.bid_pips_label.setAlignment(Qt.AlignCenter)
        self.bid_pips_label.setFont(QFont('Arial', 12))

        self.button_lhs_skew = QPushButton('Skew LHS', self)
        self.button_lhs_skew.setToolTip('This is an example button')
        self.button_lhs_skew.clicked.connect(self.lhs_skew)

        self.button_rhs_skew = QPushButton('Skew RHS', self)
        self.button_rhs_skew.setToolTip('This is an example button')
        self.button_rhs_skew.clicked.connect(self.rhs_skew)

        self.button_widen = QPushButton('◀ Widen ▶', self)
        self.button_widen.clicked.connect(self.widen)
        self.button_widen.setFont(QFont('Arial', 10, QFont.Bold))
        self.button_widen.setStyleSheet("""
            QPushButton {
                background-color: #3a2a2a;
                border: 2px solid #FF6B6B;
                border-radius: 8px;
                padding: 6px;
                color: #FF9999;
                font-weight: bold;
                min-width: 120px;
                max-height: 30px;
            }
            QPushButton:hover {
                background-color: #4a2a2a;
                border: 2px solid #FF4444;
                color: #FFAAAA;
            }
            QPushButton:pressed {
                background-color: #5a2a2a;
            }
        """)

        self.button_tighten = QPushButton('▶ Tighten ◀', self)
        self.button_tighten.clicked.connect(self.tighten)
        self.button_tighten.setFont(QFont('Arial', 10, QFont.Bold))
        self.button_tighten.setStyleSheet("""
            QPushButton {
                background-color: #2a3a2a;
                border: 2px solid #4CAF50;
                border-radius: 8px;
                padding: 6px;
                color: #99FF99;
                font-weight: bold;
                min-width: 120px;
                max-height: 30px;
            }
            QPushButton:hover {
                background-color: #2a4a2a;
                border: 2px solid #51CF66;
                color: #AAFFAA;
            }
            QPushButton:pressed {
                background-color: #2a5a2a;
            }
        """)

        # self.ccy_cross = QLineEdit(self)
        # self.ccy_cross.setText(str(''))
        # self.ccy_cross.textChanged.connect(self.get_cross_spread)

        # Mid

        

        self.mid_pips_label = QLabel(self)
       
        self.mid_pips_label.setFont(QFont('Arial', 12))



        #Offers

        self.offer_tittle = QLabel(self)
       
        self.offer_tittle.setText("Offer: ")

        self.offer_label = QLabel(self)
        self.offer_label.setAlignment(Qt.AlignCenter)
        self.offer_label.setFont(QFont('Arial', 14, QFont.Bold))
        self.offer_label.setProperty('class', 'offer-label')
        self.offer_label.setMinimumWidth(190)  # Increased for 6 decimals on JPY-base
        self.offer_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 6px;
                padding: 10px;
                color: #ffffff;
            }
        """)

      

        self.offer_pips_label = QLabel(self)
        
        self.offer_pips_label.setFont(QFont('Arial', 12))

       

        self.spread_label = QLabel(self)
        self.spread_label.setAlignment(Qt.AlignCenter)
        self.spread_label.setFont(QFont('Arial', 12))
        # Width will be set dynamically - compact for regular pairs, wider for crosses
        self.spread_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 4px;
                padding: 6px;
                color: #ffffff;
            }
        """)
        self.previous_spread = 0  # Track spread changes

        # LHS Skew badge pill - shows under bid price when LHS skew is active
        self.lhs_skew_badge = QLabel(self)
        self.lhs_skew_badge.setAlignment(Qt.AlignCenter)
        self.lhs_skew_badge.setText("")
        self.lhs_skew_badge.setFont(QFont('Arial', 8, QFont.Bold))
        self.lhs_skew_badge.setVisible(False)  # Hidden by default
        self.lhs_skew_badge.setFixedSize(70, 18)  # Larger pill size to fit "skew" text
        self.lhs_skew_badge.setStyleSheet("""
            QLabel {
                background-color: #4a4a4a;
                border-radius: 9px;
                padding: 2px 4px;
                color: #ffffff;
            }
        """)
        
        # RHS Skew badge pill - shows under offer price when RHS skew is active
        self.rhs_skew_badge = QLabel(self)
        self.rhs_skew_badge.setAlignment(Qt.AlignCenter)
        self.rhs_skew_badge.setText("")
        self.rhs_skew_badge.setFont(QFont('Arial', 8, QFont.Bold))
        self.rhs_skew_badge.setVisible(False)  # Hidden by default
        self.rhs_skew_badge.setFixedSize(70, 18)  # Larger pill size to fit "skew" text
        self.rhs_skew_badge.setStyleSheet("""
            QLabel {
                background-color: #4a4a4a;
                border-radius: 9px;
                padding: 2px 4px;
                color: #ffffff;
            }
        """)
        
        # Manual spread badge pill - only shows when modified
        self.manual_spread_badge = QLabel(self)
        self.manual_spread_badge.setAlignment(Qt.AlignCenter)
        self.manual_spread_badge.setText("")
        self.manual_spread_badge.setFont(QFont('Arial', 8, QFont.Bold))
        self.manual_spread_badge.setVisible(False)  # Hidden by default
        self.manual_spread_badge.setFixedSize(50, 18)  # Small pill size
        self.manual_spread_badge.setStyleSheet("""
            QLabel {
                background-color: #4a4a4a;
                border-radius: 9px;
                padding: 2px 4px;
                color: #ffffff;
            }
        """)


        # Pip value label - compact display in top-left
        self.pip_value_label = QLabel(self)
        self.pip_value_label.setAlignment(Qt.AlignCenter)
        self.pip_value_label.setFont(QFont('Arial', 8))
        self.pip_value_label.setText("")
        self.pip_value_label.setToolTip("Pip value per 1M base currency in USD (scaled for current order size)")
        self.pip_value_label.setStyleSheet("""
            QLabel {
                background-color: rgba(42, 58, 74, 0.7);
                border-radius: 3px;
                padding: 2px 6px;
                color: #a0a0a0;
                border: 1px solid rgba(58, 74, 90, 0.5);
                font-size: 11px;
            }
        """)
        
        #Reverse
        self.reverse_label = QLabel(self)
       
        self.reverse_label.setFont(QFont('Arial', 8))
        self.reverse_label.setText(f"Reverse Amount: {self.pricing_obj.ccy[-3:]}:")

        # Reverse currency price & amount
        self.reverse_size_input = QLineEdit(self)
        # Use dark theme styling from apply_modern_styling()
        self.reverse_size_input.setText(str(self.pricing_obj.reverse_size_input))
        self.reverse_size_input.textChanged.connect(self.reverse_order_size_method)

        # Reverse currency price & amount
        self.reverse_size_output_label = QLabel(self)

        self.reverse_size_output_label.setText(str(self.pricing_obj.reverse_size_output))
        

        self.button_inverse = QPushButton('Inverse prices', self)
        self.button_inverse.setToolTip('Switch the price to the non base ccy')
        self.button_inverse.clicked.connect(self.inverse)
        
        
        
        
        # ========= Layout =========
        # Layout is now organized with graph on left side and controls on right
        # Column 0: Graph
        # Columns 2-8: Controls and inputs
        
        # Create a horizontal layout for timestamp and pip value
        top_left_layout = QHBoxLayout()
        top_left_layout.setSpacing(8)
        top_left_layout.addWidget(self.timestamp_label)
        top_left_layout.addWidget(self.pip_value_label)
        top_left_layout.addStretch()
        
        top_left_widget = QWidget()
        top_left_widget.setLayout(top_left_layout)
        self.layout.addWidget(top_left_widget, 0, 0, 1, 2)
        
        # Add data source indicator at the top left of control columns
        self.layout.addWidget(self.data_source_frame, 0, 2, 1, 3)

        # Add the flags label directly above the currency combo box
        self.layout.addWidget(self.flags_label, 1, 3, 1, 1)

        # Shift all control elements down by 1 row and to the right to make room for the graph on the left
        self.layout.addWidget(self.combo_ccy, 2, 3, 1, 1)
        self.layout.addWidget(self.ccy_typing_input, 2, 4, 1, 1)  # Currency input field

        # Pre hedge amnt
        self.layout.addWidget(self.pre_hedge_tittle, 8, 5, 1, 1)
        
        # Spread matrix selection - create horizontal layout
        spread_matrix_layout = QHBoxLayout()
        spread_matrix_layout.setSpacing(6)
        spread_matrix_layout.addWidget(self.spread_matrix_label)
        spread_matrix_layout.addWidget(self.combo_choose_spread_matrix)
        
        spread_matrix_widget = QWidget()
        spread_matrix_widget.setLayout(spread_matrix_layout)
        self.layout.addWidget(spread_matrix_widget, 0, 5, 1, 2)

        
        self.layout.addWidget(self.lhs_help, 1, 0, 1, 3)
        self.layout.addWidget(self.rhs_help, 1, 4, 1, 3)
        
        # CROSS CCY Amounts - moved below bid/offer labels for better visibility
        self.layout.addWidget(self.cross_help_amount_lhs, 2, 0, 1, 3)
        self.layout.addWidget(self.cross_help_amount_rhs, 2, 4, 1, 3)

        self.layout.addWidget(self.order_size_input, 4, 3, 1, 1)

        self.layout.addWidget(self.spread_label, 5, 3, 1, 1)
        # Move mid_pips_label to avoid overlap
        self.layout.addWidget(self.mid_pips_label, 4, 4, 1, 1)

        self.layout.addWidget(self.button_lhs_skew, 4, 0, 1, 1)
        self.layout.addWidget(self.button_rhs_skew, 4, 6, 1, 1)

        self.layout.addWidget(self.bid_tittle, 3, 0, 1, 1)
        self.layout.addWidget(self.bid_label, 3, 1, 1, 1)
        self.layout.addWidget(self.bid_pips_label, 5, 1, 1, 1)
        
        # Add LHS skew badge below bid price (left side)
        self.layout.addWidget(self.lhs_skew_badge, 6, 1, 1, 1)

        self.layout.addWidget(self.offer_tittle, 3, 6, 1, 1)
        self.layout.addWidget(self.offer_label, 3, 5, 1, 1)
        self.layout.addWidget(self.offer_pips_label, 5, 6, 1, 1)
        
        # Add RHS skew badge below offer price (right side)
        self.layout.addWidget(self.rhs_skew_badge, 6, 6, 1, 1)
        
        # Add manual spread badge to the right of tighten button
        self.layout.addWidget(self.manual_spread_badge, 7, 4, 1, 1)
        
        # High/Low session display - positioned above Reverse Amount
        self.layout.addWidget(self.high_low_container, 8, 1, 1, 3)   # Container spanning 3 columns to match content
        
        # Reverse amount row moved down by 1
        self.layout.addWidget(self.reverse_label, 9, 1, 1, 1)
        self.layout.addWidget(self.reverse_size_input, 9, 3, 1, 1)
        self.layout.addWidget(self.reverse_size_output_label, 9, 4, 1, 1)
        self.layout.addWidget(self.button_inverse, 9, 5, 1, 1)
        
        # Widen/Tighten buttons - vertically stacked below spread pips
        self.layout.addWidget(self.button_widen, 6, 3, 1, 1)     # Widen button
        self.layout.addWidget(self.button_tighten, 7, 3, 1, 1)   # Tighten button below

        # Executablee prices 2-5 to 30+
        # self.layout.addWidget(self.inverse_bid_offer_2_5_label, 5, 3, 1, 1)
        # self.layout.addWidget(self.inverse_bid_offer_5_10_label, 6, 3, 1, 1)
        # self.layout.addWidget(self.inverse_bid_offer_10_20_label, 7, 3, 1, 1)
        # self.layout.addWidget(self.inverse_bid_offer_20_30_label, 8, 3, 1, 1)
   
        


        # Add currency buttons - ensure they all fit
        self.currency_buttons_layout = QHBoxLayout()  # Use HBoxLayout for better control
        self.currency_buttons_layout.setSpacing(3)  # Small spacing between buttons
        self.currency_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.currency_buttons = {}
        currencies = ["AUD", "EUR", "GBP", "CAD", "JPY", "NZD", "CHF", "CNH", "SGD"]
        
        # Create currency section label
        self.currency_section_label = QLabel("CCY:", self)
        self.currency_section_label.setFont(QFont('Arial', 11, QFont.Bold))
        self.currency_section_label.setFixedWidth(45)
        self.currency_section_label.setStyleSheet("color: #e8e8e8;")
        self.layout.addWidget(self.currency_section_label, 9, 0, 1, 1)
        
        # Create currency buttons with appropriate sizing
        for ccy in currencies:
            button = QPushButton(ccy, self)
            button.setFixedHeight(32)  # Slightly taller for better visibility
            button.setFixedWidth(52)   # Slightly wider to fit text
            button.setFont(QFont('Arial', 9))  # Slightly bigger font, not bold
            button.setProperty('class', 'currency-btn')
            
            # Map short names to full pairs
            ccy_map = {
                'AUD': 'AUDUSD', 'EUR': 'EURUSD', 'GBP': 'GBPUSD',
                'CAD': 'USDCAD', 'JPY': 'USDJPY', 'NZD': 'NZDUSD',
                'CHF': 'USDCHF', 'CNH': 'USDCNH', 'SGD': 'USDSGD'
            }
            button.clicked.connect(lambda checked, c=ccy_map.get(ccy, ccy): self.select_currency(c))
            self.currency_buttons[ccy] = button
            self.currency_buttons_layout.addWidget(button)
        
        # Add stretch to prevent buttons from expanding
        self.currency_buttons_layout.addStretch()
        
        # Add the currency buttons layout to span multiple columns
        currency_widget = QWidget()
        currency_widget.setLayout(self.currency_buttons_layout)
        self.layout.addWidget(currency_widget, 10, 1, 1, 6)
        
        # Add size buttons - ensure they all fit
        self.size_buttons_layout = QHBoxLayout()  # Use HBoxLayout
        self.size_buttons_layout.setSpacing(3)  # Small spacing
        self.size_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.size_buttons = {}
        sizes = [10, 25, 50, 75, 100, 150, 200, 250]
        
        # Create size section label
        self.size_section_label = QLabel("Size:", self)
        self.size_section_label.setFont(QFont('Arial', 11, QFont.Bold))
        self.size_section_label.setFixedWidth(45)
        self.size_section_label.setStyleSheet("color: #e8e8e8;")
        self.layout.addWidget(self.size_section_label, 11, 0, 1, 1)
        
        # Create size buttons
        for size in sizes:
            button = QPushButton(str(size), self)
            button.setFixedHeight(32)  # Match currency button height
            button.setFixedWidth(52)   # Match currency button width
            button.setFont(QFont('Arial', 9))  # Match currency button font
            button.setProperty('class', 'size-btn')
            button.clicked.connect(lambda checked, s=size: self.select_size(s))
            self.size_buttons[size] = button
            self.size_buttons_layout.addWidget(button)
        
        # Add stretch
        self.size_buttons_layout.addStretch()
        
        # Add the size buttons layout
        size_widget = QWidget()
        size_widget.setLayout(self.size_buttons_layout)
        self.layout.addWidget(size_widget, 11, 1, 1, 6)
        
        # Create collapsible config section
        self.config_visible = False
        self.config_toggle_button = QPushButton("▶ Config", self)
        self.config_toggle_button.setFixedHeight(25)
        self.config_toggle_button.setFixedWidth(100)
        self.config_toggle_button.setFont(QFont('Arial', 9, QFont.Bold))
        self.config_toggle_button.clicked.connect(self.toggle_config_section)
        self.layout.addWidget(self.config_toggle_button, 14, 0, 1, 1)
        
        # Create config widget container (initially hidden)
        self.config_widget = QWidget()
        self.config_layout = QHBoxLayout(self.config_widget)
        self.config_layout.setContentsMargins(0, 0, 0, 0)
        self.config_layout.setSpacing(10)
        
        # Current DP display
        self.current_dp_label = QLabel("Current DP:", self)
        self.current_dp_label.setFont(QFont('Arial', 9))
        self.config_layout.addWidget(self.current_dp_label)
        
        self.current_dp_value = QLabel("4", self)
        self.current_dp_value.setFont(QFont('Arial', 9, QFont.Bold))
        self.current_dp_value.setStyleSheet("color: #51cf66;")
        self.config_layout.addWidget(self.current_dp_value)
        
        # Separator
        separator = QLabel("|", self)
        separator.setStyleSheet("color: #555555;")
        self.config_layout.addWidget(separator)
        
        # Decimal places override input
        self.dp_override_label = QLabel("Override:", self)
        self.dp_override_label.setFont(QFont('Arial', 9))
        self.config_layout.addWidget(self.dp_override_label)
        
        self.dp_override_input = QLineEdit(self)
        self.dp_override_input.setPlaceholderText("e.g. 3")
        self.dp_override_input.setFixedWidth(50)
        self.dp_override_input.textChanged.connect(self.update_decimal_override)
        self.config_layout.addWidget(self.dp_override_input)
        
        # Reset button
        self.reset_dp_button = QPushButton("Reset", self)
        self.reset_dp_button.setFixedHeight(25)
        self.reset_dp_button.setFixedWidth(60)
        self.reset_dp_button.setFont(QFont('Arial', 9))
        self.reset_dp_button.clicked.connect(self.reset_decimal_places)
        self.config_layout.addWidget(self.reset_dp_button)
        
        # Separator
        separator2 = QLabel("|", self)
        separator2.setStyleSheet("color: #555555;")
        self.config_layout.addWidget(separator2)
        
        # Toggle standard decimal places button
        self.toggle_standard_dp_button = QPushButton("Standard DP: ON", self)
        self.toggle_standard_dp_button.setCheckable(True)
        self.toggle_standard_dp_button.setChecked(True)
        self.toggle_standard_dp_button.setFixedHeight(25)
        self.toggle_standard_dp_button.setFixedWidth(120)
        self.toggle_standard_dp_button.setFont(QFont('Arial', 9))
        self.toggle_standard_dp_button.clicked.connect(self.toggle_standard_decimal_places)
        self.config_layout.addWidget(self.toggle_standard_dp_button)
        
        # Add stretch to push everything to the left
        self.config_layout.addStretch()
        
        # Add config widget to layout (initially hidden)
        self.layout.addWidget(self.config_widget, 14, 1, 1, 6)
        self.config_widget.setVisible(False)
        
        # Add toggle graph buttons to show/hide and expand/collapse the left-side graph panel
        self.toggle_graph_button = QPushButton("Show Graph", self)
        self.toggle_graph_button.clicked.connect(self.toggle_graph_visibility)
        self.toggle_graph_button.setFixedHeight(30)
        self.toggle_graph_button.setFixedWidth(100)
        self.toggle_graph_button.setFont(QFont('Arial', 10))
        self.toggle_graph_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #e8e8e8;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #4a4a5a;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #2a2a3a;
            }
        """)
        
        # Add expand/collapse graph button - starts in compact mode
        self.expand_graph_button = QPushButton("Expand", self)
        self.expand_graph_button.clicked.connect(self.toggle_graph_expansion)
        self.expand_graph_button.setFixedHeight(30)
        self.expand_graph_button.setFixedWidth(80)
        self.expand_graph_button.setFont(QFont('Arial', 10))
        self.expand_graph_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #e8e8e8;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #4a4a5a;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #2a2a3a;
            }
        """)
        
        # Voice toggle button
        self.voice_toggle_button = QPushButton("🔊 Voice", self)
        self.voice_toggle_button.clicked.connect(self.toggle_voice_announcements)
        self.voice_toggle_button.setFixedHeight(30)
        self.voice_toggle_button.setFixedWidth(90)
        self.voice_toggle_button.setFont(QFont('Arial', 10))
        
        # Apply voice button styling
        self.voice_toggle_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #e8e8e8;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover:enabled {
                background-color: #4a4a5a;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #2a2a3a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666;
                border-color: #444;
            }
        """)
        
        # Set initial voice button state
        if not voice_available:
            self.voice_toggle_button.setEnabled(False)
            self.voice_toggle_button.setText("🔇 No Voice")
        
        # Trade Calculator button
        self.trade_calc_button = QPushButton("📊 Trade Calc", self)
        self.trade_calc_button.clicked.connect(self.toggle_trade_calculator)
        self.trade_calc_button.setFixedHeight(30)
        self.trade_calc_button.setFixedWidth(110)
        self.trade_calc_button.setFont(QFont('Arial', 10))
        self.trade_calc_button.setToolTip("Open trade calculator to compute weighted average prices")
        
        # Apply trade calc button styling
        self.trade_calc_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #e8e8e8;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #4a4a5a;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #2a2a3a;
            }
        """)
        
        # Chart Analysis button
        self.chart_analysis_button = QPushButton("📈 Chart Analysis", self)
        self.chart_analysis_button.clicked.connect(self.open_chart_analysis)
        self.chart_analysis_button.setFixedHeight(30)
        self.chart_analysis_button.setFixedWidth(120)
        self.chart_analysis_button.setFont(QFont('Arial', 10))
        self.chart_analysis_button.setToolTip("Open advanced chart analysis with drawing tools")
        
        # Apply chart analysis button styling
        self.chart_analysis_button.setStyleSheet("""
            QPushButton {
                background-color: #3a4a5a;
                color: #e8e8e8;
                border: 1px solid #4a90e2;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #4a5a6a;
                border-color: #6ab0ff;
            }
            QPushButton:pressed {
                background-color: #2a3a4a;
            }
        """)
        
        # Create a horizontal layout for the graph control buttons
        graph_buttons_layout = QHBoxLayout()
        graph_buttons_layout.setSpacing(8)
        graph_buttons_layout.addWidget(self.toggle_graph_button)
        graph_buttons_layout.addWidget(self.expand_graph_button)
        graph_buttons_layout.addWidget(self.voice_toggle_button)
        graph_buttons_layout.addWidget(self.trade_calc_button)
        graph_buttons_layout.addWidget(self.chart_analysis_button)
        
        # Market Bias indicator button (clickable)
        self.market_bias_indicator = QPushButton("Market: --")
        self.market_bias_indicator.clicked.connect(self.refresh_market_bias)
        self.market_bias_indicator.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
                background-color: #3a3a3a;
                color: #888;
                border: 1px solid #555;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border: 1px solid #666;
                cursor: pointer;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        self.market_bias_indicator.setFixedHeight(30)
        self.market_bias_indicator.setMinimumWidth(180)  # Much wider to show full text
        self.market_bias_indicator.setToolTip("Click to refresh market bias for all pairs")
        graph_buttons_layout.addWidget(self.market_bias_indicator)
        
        # Super Trend indicator button (clickable)
        self.super_trend_indicator = QPushButton("Trend: --")
        self.super_trend_indicator.clicked.connect(self.refresh_super_trend)
        self.super_trend_indicator.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
                background-color: #3a3a3a;
                color: #888;
                border: 1px solid #555;
                margin-left: 5px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border: 1px solid #666;
                cursor: pointer;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        self.super_trend_indicator.setFixedHeight(30)
        self.super_trend_indicator.setMinimumWidth(150)  # Much wider to show full text
        self.super_trend_indicator.setToolTip("Click to refresh Super Trend for all pairs")
        graph_buttons_layout.addWidget(self.super_trend_indicator)
        
        # Auto-update checkbox
        self.auto_update_checkbox = QCheckBox("Auto-update")
        self.auto_update_checkbox.setChecked(False)
        self.auto_update_checkbox.setToolTip("Enable 15-minute auto-updates for indicators")
        self.auto_update_checkbox.stateChanged.connect(self.toggle_auto_update)
        self.auto_update_checkbox.setStyleSheet("""
            QCheckBox {
                color: #e8e8e8;
                margin-left: 10px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
            }
        """)
        graph_buttons_layout.addWidget(self.auto_update_checkbox)
        
        # Initialize managers
        self.init_market_bias_manager()
        self.init_super_trend_manager()
        
        # Initialize auto-update timer
        self.init_auto_update_timer()
        
        graph_buttons_layout.addStretch()  # Push buttons to the left
        
        # Position the toggle buttons at the bottom of the controls section
        graph_buttons_widget = QWidget()
        graph_buttons_widget.setLayout(graph_buttons_layout)
        self.layout.addWidget(graph_buttons_widget, 15, 1, 1, 5)
        
        # Add the chart to the bottom of the window
        # It spans row 16 across columns 0-6, taking up the entire bottom
        self.layout.addWidget(self.chart_view, 16, 0, 1, 7)
        
        # Initially hide the chart and expand button
        self.chart_view.setVisible(False)
        self.expand_graph_button.setVisible(False)

        
        # ========= Layout =========
        

        # Always try Bloomberg first as the default data source
        self.current_data_source = "Bloomberg"
        fx.check_bloomberg_availability()
        
        if fx.bloomberg_available:
            # Bloomberg available - use it
            self.bbg_gen = self.bb_obj.run()
            print("✅ Bloomberg API connected - Using live market data")
        else:
            # Bloomberg not available - try fallback options
            print("⚠️  Bloomberg Terminal not available")
            
            if websocket_sim_available:
                # Try WebSocket as first fallback
                try:
                    ws_url = getattr(self.args, 'ws_url', 'ws://localhost:8765')
                    self.feed = PriceFeedWithFailover(self.pricing_obj, url=ws_url)
                    self.bbg_gen = self.feed.run()
                    print(f"⚠️  FALLBACK: Using WebSocket price feed from {ws_url}")
                    print("⚠️  WARNING: Not using live Bloomberg data - prices may not be real-time")
                except Exception as e:
                    print(f"❌ WebSocket connection failed: {e}")
                    # Fall back to simulation
                    sim_data = fx.simulated_data(self.pricing_obj)
                    self.bbg_gen = sim_data.generate_simulated_data()
                    print("⚠️  FALLBACK: Using simulated FX data")
                    print("⚠️  WARNING: Not using live Bloomberg data - prices are simulated")
            else:
                # No WebSocket available - use simulation
                sim_data = fx.simulated_data(self.pricing_obj)
                self.bbg_gen = sim_data.generate_simulated_data()
                print("⚠️  FALLBACK: Using simulated FX data (WebSocket not available)")
                print("⚠️  WARNING: Not using live Bloomberg data - prices are simulated")

        # init
        # self.pricing_obj.create_dict_bid_offer_by_size()
        self.pricing_obj.get_spread(self.order_size)
        
        # Update data source status based on connection
        # Set initial dropdown value based on current data source
        if hasattr(self, 'current_data_source'):
            self.source_selector.setCurrentText(self.current_data_source)
        
        # Delay initial status update to allow WebSocket feed to establish state
        QTimer.singleShot(500, self.update_data_source_status)

        self.update_label()# Init the spread in the gui
        
        # Setup quick buttons after all components are initialized
        self.setup_quick_buttons()
        
        # Delay pip value pre-calculation to ensure rates are loaded
        QTimer.singleShot(1000, self.precalculate_pip_values)
        
        # Create a timer for price updates with higher priority
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_prices)
        self.timer.start(25) # Fast 40Hz updates for responsive price display
        
        # Setup timer to check connection health for WebSocket
        self.connection_check_timer = QTimer(self)
        self.connection_check_timer.timeout.connect(self.check_connection_health)
        self.connection_check_timer.start(1000)  # Check every 1 second for faster failover detection
        self.last_price_update_time = time.time()
        
        # Setup timer to update timestamp display
        self.timestamp_timer = QTimer(self)
        self.timestamp_timer.timeout.connect(lambda: self.update_timestamp() if not self.last_update_timestamp else None)
        self.timestamp_timer.start(1000)  # Update every second if no explicit timestamp
        
        # Set up a separate timer for graph updates with lower priority
        self.graph_timer = QTimer(self)
        self.graph_timer.timeout.connect(self.update_graph_data)
        self.graph_timer.start(100) # 10Hz for smoother graph updates
        
        # Set up a timer to check connection status periodically
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_connection_status)
        self.status_timer.start(2000) # Check every 2 seconds

    def apply_modern_styling(self):
        """Apply modern dark theme and professional styling"""
        # Modern window setup
        self.setWindowTitle('FX SPOT Pricer - Professional Trading Interface')
        self.setMinimumSize(900, 600)
        
        # Apply modern dark theme styling
        self.setStyleSheet("""
            * {
                font-family: 'SF Pro Display', 'Segoe UI', 'Helvetica', Arial, sans-serif;
            }
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Segoe UI', 'Helvetica', Arial, sans-serif;
                font-size: 11px;
            }
            QPushButton {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 10px;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #777777;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
            QPushButton:checked {
                background-color: #0078d4;
                border-color: #106ebe;
                color: #ffffff;
            }
            QPushButton.currency-btn {
                background-color: #2d4a7a;
                border: 2px solid #3d5a8a;
                font-size: 11px;
                color: #ffffff;
                min-width: 50px;
                max-width: 55px;
                padding: 4px 2px;
            }
            QPushButton.currency-btn:hover {
                background-color: #3d5a8a;
                color: #ffffff;
                border-color: #4d6a9a;
            }
            QPushButton.currency-btn:checked {
                background-color: #0078d4;
                border-color: #106ebe;
                color: #ffffff;
            }
            QPushButton.size-btn {
                background-color: #2d4a2d;
                border: 2px solid #3d5a3d;
                font-size: 11px;
                color: #ffffff;
                min-width: 50px;
                max-width: 55px;
                padding: 4px 2px;
            }
            QPushButton.size-btn:hover {
                background-color: #3d5a3d;
                color: #ffffff;
                border-color: #4d6a4d;
            }
            QPushButton.size-btn:checked {
                background-color: #0d7377;
                border-color: #1d8387;
                color: #ffffff;
            }
            QLineEdit {
                background-color: #2d2d2d;
                border: 2px solid #404040;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #0078d4;
            }
            QLabel {
                color: #ffffff;
                font-size: 11px;
            }
            QLabel.price-label {
                font-size: 14px;
                font-weight: bold;
                color: #00ff00;
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px;
                min-width: 100px;
            }
            QLabel.bid-label {
                color: #ff6b6b;
                font-weight: bold;
                font-size: 12px;
            }
            QLabel.offer-label {
                color: #51cf66;
                font-weight: bold;
                font-size: 12px;
            }
            QLabel.high-low-label {
                color: #ffffff;
                font-size: 10px;
                background-color: #2d2d2d;
                border: 1px solid #404040;
                border-radius: 3px;
                padding: 4px;
            }
            QComboBox {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                color: #ffffff;
            }
            QComboBox:hover {
                border-color: #777777;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
                margin-right: 5px;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                font-size: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

    def setup_quick_buttons(self):
        """Setup quick currency and size selection buttons"""
        # Currency quick buttons
        self.currency_group = QButtonGroup(self)
        self.currency_buttons = {}
        
        major_currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']
        
        for currency in major_currencies:
            btn = QPushButton(currency)
            btn.setProperty("class", "currency-btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, curr=currency: self.switch_to_currency(curr))
            self.currency_group.addButton(btn)
            self.currency_buttons[currency] = btn
        
        # Size quick buttons  
        self.size_group = QButtonGroup(self)
        self.size_buttons = {}
        
        common_sizes = ['1M', '5M', '10M', '25M', '50M', '100M']
        
        for size in common_sizes:
            btn = QPushButton(size)
            btn.setProperty("class", "size-btn")
            btn.setCheckable(True)
            size_val = int(size.replace('M', ''))
            btn.clicked.connect(lambda checked, s=size_val: self.switch_to_size(s))
            self.size_group.addButton(btn)
            self.size_buttons[size] = btn

    def switch_to_currency(self, currency):
        """Switch to a specific currency pair"""
        if self.debug_monitor:
            self.debug_monitor.record_gui_update()
            
        # Find currency pair containing this currency
        for ccy_pair in self.pricing_obj.ccys:
            if currency in ccy_pair:
                self.pricing_obj.ccy = ccy_pair
                self.combo_ccy.setCurrentText(ccy_pair)
                self.ccy_typing_input.setText(ccy_pair)
                self.update_label()
                break

    def switch_to_size(self, size):
        """Switch to a specific order size"""
        if self.debug_monitor:
            self.debug_monitor.record_gui_update()
            
        self.order_size = size
        self.order_size_input.setText(self.format_order_size(size))
        self.update_order_size()

    def clickLine(self, mouseEvent):

        self.ccy_typing_input.setText(str(""))

    def clickLine_amount(self, mouseEvent):
        self.order_size_input.setText(str(""))

    def inverse(self):
        """Toggle inverse price display mode"""
        self.inverse_bool_active = not self.inverse_bool_active
        
        if self.inverse_bool_active:
            # Clear help text in inverse mode
            self.lhs_help.setText("")
            self.rhs_help.setText("")
        else:
            # Restore help text in regular mode
            self.lhs_help.setText("Bid LHS Yours, Customer sells, Sell higherr ↑")
            self.rhs_help.setText("Offer RHS Mine, Customer Buys, Buy back Lower  ↓ ")
        
        # Force immediate update
        self.update_prices()

    def lhs_skew(self):
        self.pricing_obj.skew -= self.pricing_obj.skew_round_value
        self.update_skew_display()
        
        # Immediately update prices
        self.pricing_obj.price()

    def rhs_skew(self):
        self.pricing_obj.skew += self.pricing_obj.skew_round_value
        self.update_skew_display()
        
        # Immediately update prices
        self.pricing_obj.price()

    def update_skew_display(self):
        """Update skew badges - show on correct side based on skew direction"""
        if abs(self.pricing_obj.skew) < 0.000001:
            # No skew - hide both badges
            self.lhs_skew_badge.setVisible(False)
            self.rhs_skew_badge.setVisible(False)
        else:
            # Show skew badge on the appropriate side
            skew_pips = round((self.pricing_obj.skew * self.pricing_obj.decimal_places), 1)
            
            if self.pricing_obj.skew > 0:
                # RHS skew - show badge on right side (under offer price)
                self.lhs_skew_badge.setVisible(False)  # Hide LHS badge
                self.rhs_skew_badge.setText(f"+{skew_pips:.1f} skew ▼")
                self.rhs_skew_badge.setStyleSheet("""
                    QLabel {
                        background-color: #51cf66;
                        border-radius: 9px;
                        padding: 2px 4px;
                        color: #ffffff;
                        font-weight: bold;
                    }
                """)
                self.rhs_skew_badge.setVisible(True)
            else:
                # LHS skew - show badge on left side (under bid price)
                self.rhs_skew_badge.setVisible(False)  # Hide RHS badge
                self.lhs_skew_badge.setText(f"{skew_pips:.1f} skew ▲")
                self.lhs_skew_badge.setStyleSheet("""
                    QLabel {
                        background-color: #ff6b6b;
                        border-radius: 9px;
                        padding: 2px 4px;
                        color: #ffffff;
                        font-weight: bold;
                    }
                """)
                self.lhs_skew_badge.setVisible(True)

    def update_spread_display(self):
        """Update spread display and manual spread badge"""
        base_spread = self.pricing_obj.spread - self.pricing_obj.manual_spread
        manual_spread = self.pricing_obj.manual_spread
        
        # Check if we're in synthetic cross mode
        is_synthetic = getattr(self.pricing_obj, 'synthetic_cross_mode', False)
        
        # Reset width for regular pairs
        if not is_synthetic:
            self.spread_label.setMinimumWidth(0)  # Reset to auto-size
        
        # Update main spread label
        if abs(manual_spread) < 0.000001:
            # No manual spread modification - show base spread only
            self.spread_label.setText(f"Spread pips: {self.pricing_obj.spread}")
            self.spread_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    border: 2px solid #3a3a3a;
                    border-radius: 4px;
                    padding: 6px;
                    color: #ffffff;
                }
            """)
        else:
            # Show base spread with modification indicator
            if manual_spread > 0:
                self.spread_label.setText(f"Spread pips: {self.pricing_obj.spread} (+{manual_spread})")
            else:
                self.spread_label.setText(f"Spread pips: {self.pricing_obj.spread} ({manual_spread})")
            self.spread_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    border: 2px solid #3a3a3a;
                    border-radius: 4px;
                    padding: 6px;
                    color: #ffffff;
                }
            """)
        
        # Update manual spread badge
        if abs(manual_spread) < 0.000001:
            # No manual spread - hide the badge
            self.manual_spread_badge.setVisible(False)
        else:
            # Show manual spread badge with appropriate styling
            if manual_spread > 0:
                # Wider spread - Orange pill
                self.manual_spread_badge.setText(f"+{manual_spread}")
                self.manual_spread_badge.setStyleSheet("""
                    QLabel {
                        background-color: #ff8c00;
                        border-radius: 9px;
                        padding: 2px 4px;
                        color: #ffffff;
                        font-weight: bold;
                    }
                """)
            else:
                # Tighter spread - Blue pill
                self.manual_spread_badge.setText(f"{manual_spread}")
                self.manual_spread_badge.setStyleSheet("""
                    QLabel {
                        background-color: #4169e1;
                        border-radius: 9px;
                        padding: 2px 4px;
                        color: #ffffff;
                        font-weight: bold;
                    }
                """)
            
            self.manual_spread_badge.setVisible(True)
    
    def update_flags_display(self):
        """Update flag display based on current currency pair"""
        current_ccy = self.pricing_obj.ccy
        
        if len(current_ccy) >= 6:
            # Extract base and quote currencies
            base_ccy = current_ccy[:3]
            quote_ccy = current_ccy[3:6]
            
            # Get flags with fallback to question mark if not found
            base_flag = self.currency_flags.get(base_ccy, '❓')
            quote_flag = self.currency_flags.get(quote_ccy, '❓')
            
            # Update the label with both flags
            self.flags_label.setText(f"{base_flag} {quote_flag}")
            self.setWindowTitle(f'SPOT Pricer & Alpha signals {base_flag} {quote_flag}')
        else:
            # For non-standard pairs or CROSS, show default
            self.flags_label.setText("Flags: 🌐")

    def widen(self):
        self.pricing_obj.widen()
        
        # For synthetic crosses, we need to recalculate the spread properly
        if self.pricing_obj.synthetic_cross_mode:
            # Trigger full update which will apply manual spread to legs
            self.update_order_size()
        else:
            self.pricing_obj.get_spread(self.order_size)
            # Update spread display
            self.update_spread_display()
            # Immediately recalculate and update all prices
            self.pricing_obj.price()
        
        # Flash red to indicate widening
        self.spread_label.setStyleSheet("""
            QLabel {
                background-color: #4a2a2a;
                border: 2px solid #ff6b6b;
                border-radius: 4px;
                padding: 6px;
                color: #ff6b6b;
                font-weight: bold;
            }
        """)
        
        # Reset style after a short delay
        QTimer.singleShot(300, lambda: self.update_spread_display())
        
        # Force immediate GUI update
        self.update_prices()

    def tighten(self):
        self.pricing_obj.tighten()
        
        # For synthetic crosses, we need to recalculate the spread properly
        if self.pricing_obj.synthetic_cross_mode:
            # Trigger full update which will apply manual spread to legs
            self.update_order_size()
        else:
            self.pricing_obj.get_spread(self.order_size)
            # Update spread display
            self.update_spread_display()
            # Immediately recalculate and update all prices
            self.pricing_obj.price()
        
        # Flash green to indicate tightening
        self.spread_label.setStyleSheet("""
            QLabel {
                background-color: #2a4a2a;
                border: 2px solid #51cf66;
                border-radius: 4px;
                padding: 6px;
                color: #51cf66;
                font-weight: bold;
            }
        """)
        
        # Reset style after a short delay
        QTimer.singleShot(300, lambda: self.update_spread_display())
        
        # Force immediate GUI update
        self.update_prices()

    def update_current_spread_matrix(self):
        # When we change current spread matrix choice
        
        self.pricing_obj.choose_spread_matrix(self.combo_choose_spread_matrix.currentText())
        
        
        if self.combo_choose_spread_matrix.currentText() == 'Default':
            self.combo_choose_spread_matrix.setStyleSheet("""
                QComboBox {
                    background-color: #2b2b2b;
                    color: #e8e8e8;
                    border: 1px solid #555;
                    padding: 4px;
                    border-radius: 4px;
                    min-width: 120px;
                }
                QComboBox:hover {
                    border-color: #777;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 4px solid transparent;
                    border-right: 4px solid transparent;
                    border-top: 4px solid #e8e8e8;
                    margin-right: 5px;
                }
            """)
        else:
            # Highlight non-default spread matrix with accent color
            self.combo_choose_spread_matrix.setStyleSheet("""
                QComboBox {
                    background-color: #3a3a4a;
                    color: #ffd700;
                    border: 1px solid #ffd700;
                    padding: 4px;
                    border-radius: 4px;
                    min-width: 120px;
                    font-weight: bold;
                }
                QComboBox:hover {
                    border-color: #ffed4e;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 4px solid transparent;
                    border-right: 4px solid transparent;
                    border-top: 4px solid #ffd700;
                    margin-right: 5px;
                }
            """)
        
        self.update_order_size()
        

    def update_label(self):
        # When we change currency
        self.pricing_obj.ccy = self.combo_ccy.currentText()
        if self.pricing_obj.ccy != 'CROSS':
            if self.debug_ui_actions:
                print(f"Currency changed to: {self.pricing_obj.ccy}")
            self.ccy_typing_input.setText(str(self.pricing_obj.ccy))
            # Hide cross help text when not in cross mode
            self.cross_help_amount_lhs.setVisible(False)
            self.cross_help_amount_rhs.setVisible(False)
            # Update market bias display for new currency
            if hasattr(self, 'update_bias_display'):
                self.update_bias_display()
            
            # Update super trend display for new currency
            if hasattr(self, 'update_trend_display'):
                self.update_trend_display()
            
            # Update chart analysis window if open
            if hasattr(self, 'chart_analysis_window') and self.chart_analysis_window and self.chart_analysis_window.isVisible():
                self.chart_analysis_window.currency_pair = self.pricing_obj.ccy
                self.chart_analysis_window.setWindowTitle(f"Chart Analysis - {self.pricing_obj.ccy}")
                self.chart_analysis_window.load_data()
            
            # Update decimal override display for new currency
            current_ccy = self.pricing_obj.ccy
            if current_ccy in self.pricing_obj.config['manual_dp_override']:
                override_dp = self.pricing_obj.config['manual_dp_override'][current_ccy]
                self.dp_override_input.setText(str(override_dp))
            else:
                self.dp_override_input.setText("")
            
            # Update current DP display if config is visible
            if self.config_visible:
                self.update_current_dp_display()
            # self.reset_live_graph()
            # When we change CCY, we myst revert reverse ammount to 0
            self.pricing_obj.reverse_size_input = 0
            self.pricing_obj.skew = 0
            self.pricing_obj.manual_spread = 0.0
            self.pricing_obj.deactivate_synthetic_mode()
            self.pricing_obj.price()
            
            
            # Reset skew and spread displays
            self.pricing_obj.skew = 0.0
            self.pricing_obj.manual_spread = 0.0
            self.update_skew_display()
            self.update_spread_display()
            
            # Ensure badges are hidden when no modifications
            self.lhs_skew_badge.setVisible(False)
            self.rhs_skew_badge.setVisible(False)
            self.manual_spread_badge.setVisible(False)
            
            # New section - update labels
            self.reverse_label.setText(f"Reverse Amount: {self.pricing_obj.ccy[-3:]}:")
            self.reverse_size_input.setText("0")
            self.reverse_size_output_label.setText(f"0 {self.pricing_obj.ccy[:3]} ")

            # Subscribe to the executable sizes for the new ccy
            # self.bb_obj.resubscribe()
            
            self.update_order_size()
            self.update_pip_value_display()  # Update pip value only when currency changes
            if self.inverse_bool_active:

                self.inverse()
            
            self.reset_live_graph()
            
    def toggle_graph_visibility(self):
        """Toggle the visibility of the bottom graph panel and pause/resume graph updates"""
        self.graph_visible = not self.graph_visible
        
        if self.graph_visible:
            # Show graph and resume updates
            self.chart_view.setVisible(True)
            self.toggle_graph_button.setText("Hide Graph")
            self.toggle_graph_button.setFixedWidth(80)  # Adjust width for new text
            self.expand_graph_button.setVisible(True)
            if not self.graph_timer.isActive():
                self.graph_timer.start(250)
            
            # Expand the window height to accommodate the bottom graph
            self.resize(self.window_width_with_graph, self.window_height_with_graph)
            
            # Keep layout spacing compact
            self.layout.setHorizontalSpacing(5)
            self.layout.setVerticalSpacing(2)
            
            print("Bottom graph shown and updates resumed")
        else:
            # Hide graph and pause updates
            self.chart_view.setVisible(False)
            self.toggle_graph_button.setText("Show Graph")
            self.toggle_graph_button.setFixedWidth(80)  # Reset width
            self.expand_graph_button.setVisible(False)
            if self.graph_timer.isActive():
                self.graph_timer.stop()
            
            # Force layout update before resizing
            self.layout.update()
            
            # Add a small delay before resizing to ensure layout updates properly
            QTimer.singleShot(50, lambda: self.resize_after_hide())
            
            print("Bottom graph hidden and updates paused")
            
    def resize_after_hide(self):
        """Resize window after hiding graph with a small delay to ensure proper layout update"""
        # Resize the window to the compact height (no bottom graph)
        self.resize(self.window_width_without_graph, self.window_height_without_graph)
        self.setMaximumWidth(self.window_width_without_graph)
        
        # Force another layout update after resize
        self.layout.update()
        
    def toggle_graph_expansion(self):
        """Toggle between compact and expanded graph view"""
        if not self.graph_visible:
            return
            
        self.graph_expanded = not self.graph_expanded
        
        if self.graph_expanded:
            # Expand the graph vertically at bottom
            self.chart_view.setMinimumSize(400, 300)
            self.chart_view.setMaximumSize(2000, 400)  # Taller expanded view
            self.resize(self.window_width_with_graph, self.window_height_with_graph + 130)  # Extra height for expansion and cross help text
            self.expand_graph_button.setText("Compact")
            print("Graph expanded")
        else:
            # Return to compact view
            self.chart_view.setMinimumSize(400, 200)
            self.chart_view.setMaximumSize(2000, 300)  # Standard height
            self.resize(self.window_width_with_graph, self.window_height_with_graph)  # Standard height
            self.expand_graph_button.setText("Expand")
            print("Graph compacted")
            
        # Force layout update
        self.layout.update()
    
    def toggle_voice_announcements(self):
        """Toggle voice announcements on/off"""
        if not voice_available or not self.voice_announcer:
            return
        
        self.voice_enabled = not self.voice_enabled
        
        if self.voice_enabled:
            success = self.voice_announcer.enable()
            if success:
                self.voice_toggle_button.setText("🔊 Voice On")
                self.voice_toggle_button.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 2px 8px;
                        font-weight: bold;
                        min-height: 20px;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                    }
                """)
                print("🔊 Voice announcements enabled")
            else:
                self.voice_enabled = False
                print("❌ Failed to enable voice announcements")
        else:
            self.voice_announcer.disable()
            self.voice_toggle_button.setText("🔇 Voice Off")
            self.voice_toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-weight: bold;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
            """)
            print("🔇 Voice announcements disabled")
    
    def open_chart_analysis(self):
        """Open the chart analysis window"""
        try:
            from chart_analysis_widget import ChartAnalysisWidget
            
            # Get current currency pair from pricing object
            current_pair = self.pricing_obj.ccy if hasattr(self, 'pricing_obj') and self.pricing_obj else "EURUSD"
            
            # Create and show the chart analysis widget
            if not hasattr(self, 'chart_analysis_window') or self.chart_analysis_window is None:
                self.chart_analysis_window = ChartAnalysisWidget(self, currency_pair=current_pair)
                
                # Position to the left of main window
                main_geometry = self.geometry()
                chart_width = 1200
                chart_height = 800
                
                # Calculate position to the left of main window
                x_pos = main_geometry.x() - chart_width - 20  # 20px gap
                y_pos = main_geometry.y()
                
                # Ensure it's on screen
                screen = QApplication.desktop().screenGeometry()
                if x_pos < 0:
                    x_pos = 10  # If would be off-screen, place at left edge
                
                self.chart_analysis_window.setGeometry(x_pos, y_pos, chart_width, chart_height)
            else:
                # Update currency pair if window already exists
                self.chart_analysis_window.currency_pair = current_pair
                self.chart_analysis_window.setWindowTitle(f"Chart Analysis - {current_pair}")
                self.chart_analysis_window.load_data()
            
            self.chart_analysis_window.show()
            self.chart_analysis_window.raise_()
            self.chart_analysis_window.activateWindow()
            
        except ImportError as e:
            print(f"Error importing chart analysis widget: {e}")
            QMessageBox.warning(self, "Import Error", 
                               "Chart Analysis module not found. Please ensure chart_analysis_widget.py is available.")
        except Exception as e:
            print(f"Error opening chart analysis: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open chart analysis: {str(e)}")
    
    def init_market_bias_manager(self):
        """Initialize the market bias manager"""
        try:
            from market_bias_manager import get_market_bias_manager
            self.bias_manager = get_market_bias_manager()
            
            # Load initial bias for current pair if available
            self.update_bias_display()
            
            # Set up update thread
            self.bias_update_thread = None
            
        except ImportError as e:
            print(f"Market bias manager not available: {e}")
            self.bias_manager = None
    
    def refresh_market_bias(self):
        """Refresh market bias for all pairs when button clicked"""
        if not hasattr(self, 'bias_manager') or self.bias_manager is None:
            QMessageBox.warning(self, "Error", "Market bias manager not available")
            return
        
        # Check if update already in progress
        if self.bias_manager.is_updating():
            QMessageBox.information(self, "Update in Progress", 
                                   "Market bias update is already in progress. Please wait...")
            return
        
        # Show updating state
        self.market_bias_indicator.setText("Updating...")
        self.market_bias_indicator.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
                background-color: #3a3a3a;
                color: #ffeb3b;
                border: 2px solid #ffeb3b;
                margin-left: 10px;
            }
        """)
        
        # Start background update
        class BiasUpdateThread(QThread):
            finished = pyqtSignal(int, int)
            
            def __init__(self, bias_manager):
                super().__init__()
                self.bias_manager = bias_manager
            
            def run(self):
                def callback(success, total):
                    self.finished.emit(success, total)
                
                self.bias_manager.update_all_pairs(callback=callback)
                
                # Wait for completion
                while self.bias_manager.is_updating():
                    self.msleep(100)
        
        self.bias_update_thread = BiasUpdateThread(self.bias_manager)
        self.bias_update_thread.finished.connect(self.on_bias_update_complete)
        self.bias_update_thread.start()
    
    def on_bias_update_complete(self, success: int, total: int):
        """Handle completion of bias update"""
        # Update display for current pair
        self.update_bias_display()
        
        # Show completion message
        if success == total:
            QMessageBox.information(self, "Update Complete", 
                                   f"Successfully updated market bias for all {total} pairs")
        else:
            QMessageBox.warning(self, "Update Partial", 
                               f"Updated {success} of {total} pairs. Some updates failed.")
    
    def update_bias_display(self):
        """Update the bias display for current currency pair"""
        if not hasattr(self, 'bias_manager') or self.bias_manager is None:
            return
        
        # Get current pair
        current_pair = self.price_engine.ccy if hasattr(self, 'price_engine') else "EURUSD"
        
        # Get bias data
        bias_data = self.bias_manager.get_bias(current_pair)
        bias = bias_data.get('bias', 0)
        strength = bias_data.get('strength', 0)
        
        # Update display
        if bias == 1:
            self.market_bias_indicator.setText(f"Market: BULLISH ({strength:.1f}%)")
            self.market_bias_indicator.setStyleSheet("""
                QPushButton {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #1b5e20;
                    color: #4caf50;
                    border: 2px solid #4caf50;
                    margin-left: 10px;
                }
                QPushButton:hover {
                    background-color: #2b6e30;
                    border: 2px solid #5cbf60;
                }
            """)
        elif bias == -1:
            self.market_bias_indicator.setText(f"Market: BEARISH ({strength:.1f}%)")
            self.market_bias_indicator.setStyleSheet("""
                QPushButton {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #b71c1c;
                    color: #f44336;
                    border: 2px solid #f44336;
                    margin-left: 10px;
                }
                QPushButton:hover {
                    background-color: #c72c2c;
                    border: 2px solid #f55346;
                }
            """)
        else:
            self.market_bias_indicator.setText(f"Market: --")
            self.market_bias_indicator.setStyleSheet("""
                QPushButton {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #3a3a3a;
                    color: #888;
                    border: 1px solid #555;
                    margin-left: 10px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                    border: 1px solid #666;
                }
            """)
    
    def update_market_bias(self, currency_pair: str, bias: int):
        """Update market bias indicator on main GUI (legacy method for chart widget)"""
        # Store in bias manager if available
        if hasattr(self, 'bias_manager') and self.bias_manager:
            self.bias_manager.bias_data[currency_pair] = {
                'bias': bias,
                'strength': 0,  # Will be updated on next refresh
                'timestamp': datetime.now().isoformat()
            }
        
        # Update display if it's the current pair
        current_pair = self.price_engine.ccy if hasattr(self, 'price_engine') else "EURUSD"
        if currency_pair == current_pair:
            if bias == 1:
                self.market_bias_indicator.setText(f"Market: BULLISH")
                self.market_bias_indicator.setStyleSheet("""
                    QPushButton {
                        padding: 5px 10px;
                        border-radius: 3px;
                        font-weight: bold;
                        background-color: #1b5e20;
                        color: #4caf50;
                        border: 2px solid #4caf50;
                        margin-left: 10px;
                    }
                    QPushButton:hover {
                        background-color: #2b6e30;
                        border: 2px solid #5cbf60;
                    }
                """)
            else:
                self.market_bias_indicator.setText(f"Market: BEARISH")
                self.market_bias_indicator.setStyleSheet("""
                    QPushButton {
                        padding: 5px 10px;
                        border-radius: 3px;
                        font-weight: bold;
                        background-color: #b71c1c;
                        color: #f44336;
                        border: 2px solid #f44336;
                        margin-left: 10px;
                    }
                    QPushButton:hover {
                        background-color: #c72c2c;
                        border: 2px solid #f55346;
                    }
                """)
    
    def init_super_trend_manager(self):
        """Initialize the super trend manager"""
        try:
            from super_trend_manager import get_super_trend_manager
            self.trend_manager = get_super_trend_manager()
            
            # Load initial trend for current pair if available
            self.update_trend_display()
            
        except ImportError as e:
            print(f"Super trend manager not available: {e}")
            self.trend_manager = None
    
    def refresh_super_trend(self):
        """Refresh super trend for all pairs when button clicked"""
        if not hasattr(self, 'trend_manager') or self.trend_manager is None:
            QMessageBox.warning(self, "Error", "Super trend manager not available")
            return
        
        # Check if update already in progress
        if self.trend_manager.is_updating():
            QMessageBox.information(self, "Update in Progress", 
                                   "Super trend update is already in progress. Please wait...")
            return
        
        # Show updating state
        self.super_trend_indicator.setText("Updating...")
        self.super_trend_indicator.setStyleSheet("""
            QPushButton {
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
                background-color: #3a3a3a;
                color: #ffaa00;
                border: 1px solid #555;
                margin-left: 5px;
            }
        """)
        
        # Create update thread
        class TrendUpdateThread(QThread):
            finished = pyqtSignal(int, int)
            
            def __init__(self, trend_manager):
                super().__init__()
                self.trend_manager = trend_manager
            
            def run(self):
                def callback(success, total):
                    self.finished.emit(success, total)
                
                self.trend_manager.update_all_pairs(callback=callback)
                
                # Wait for completion
                while self.trend_manager.is_updating():
                    self.msleep(100)
        
        self.trend_update_thread = TrendUpdateThread(self.trend_manager)
        self.trend_update_thread.finished.connect(self.on_trend_update_complete)
        self.trend_update_thread.start()
    
    def on_trend_update_complete(self, success_count, total_count):
        """Called when trend update is complete"""
        QMessageBox.information(self, "Update Complete", 
                               f"Super Trend update complete!\n"
                               f"Successfully updated {success_count}/{total_count} pairs")
        
        # Update display for current pair
        self.update_trend_display()
    
    def update_trend_display(self):
        """Update the trend display for current currency pair"""
        if not hasattr(self, 'trend_manager') or self.trend_manager is None:
            return
        
        # Get current pair
        current_pair = self.price_engine.ccy if hasattr(self, 'price_engine') else "EURUSD"
        
        # Get trend data
        trend_data = self.trend_manager.get_trend(current_pair)
        trend = trend_data.get('trend', 0)
        direction = trend_data.get('direction', 'NEUTRAL')
        distance = trend_data.get('distance', 0)
        
        # Update display
        if trend == 1:
            self.super_trend_indicator.setText(f"Trend: UP ({distance:.1f}%)")
            self.super_trend_indicator.setStyleSheet("""
                QPushButton {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #1b5e20;
                    color: #4caf50;
                    border: 2px solid #4caf50;
                    margin-left: 5px;
                }
                QPushButton:hover {
                    background-color: #2b6e30;
                    border: 2px solid #5cbf60;
                }
            """)
        elif trend == -1:
            self.super_trend_indicator.setText(f"Trend: DOWN ({distance:.1f}%)")
            self.super_trend_indicator.setStyleSheet("""
                QPushButton {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #b71c1c;
                    color: #f44336;
                    border: 2px solid #f44336;
                    margin-left: 5px;
                }
                QPushButton:hover {
                    background-color: #c72c2c;
                    border: 2px solid #f55346;
                }
            """)
        else:
            self.super_trend_indicator.setText(f"Trend: --")
            self.super_trend_indicator.setStyleSheet("""
                QPushButton {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #3a3a3a;
                    color: #888;
                    border: 1px solid #555;
                    margin-left: 5px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                    border: 1px solid #666;
                }
            """)
    
    def init_auto_update_timer(self):
        """Initialize the 15-minute auto-update timer"""
        self.auto_update_timer = QTimer(self)
        self.auto_update_timer.timeout.connect(self.auto_update_indicators)
        # 15 minutes = 900000 milliseconds
        self.auto_update_timer.setInterval(900000)
        
        # Load saved auto-update preference
        self.auto_update_enabled = False  # Default to disabled
    
    def toggle_auto_update(self, state):
        """Toggle auto-update timer on/off"""
        from PyQt5.QtCore import Qt
        self.auto_update_enabled = (state == Qt.Checked)
        
        if self.auto_update_enabled:
            self.auto_update_timer.start()
            # Perform immediate update
            self.auto_update_indicators()
            QMessageBox.information(self, "Auto-Update Enabled", 
                                   "Indicators will auto-update every 15 minutes")
        else:
            self.auto_update_timer.stop()
            QMessageBox.information(self, "Auto-Update Disabled", 
                                   "Auto-updates have been disabled")
    
    def auto_update_indicators(self):
        """Auto-update both market bias and super trend indicators"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-updating indicators...")
        
        # Update current pair only for efficiency
        current_pair = self.price_engine.ccy if hasattr(self, 'price_engine') else "EURUSD"
        
        # Update market bias for current pair
        if hasattr(self, 'bias_manager') and self.bias_manager:
            try:
                self.bias_manager.update_single_pair(current_pair)
                self.update_bias_display()
            except Exception as e:
                print(f"Error updating market bias: {e}")
        
        # Update super trend for current pair
        if hasattr(self, 'trend_manager') and self.trend_manager:
            try:
                self.trend_manager.update_single_pair(current_pair)
                self.update_trend_display()
            except Exception as e:
                print(f"Error updating super trend: {e}")
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-update complete")
    
    def toggle_trade_calculator(self):
        """Toggle the trade calculator panel visibility"""
        if self.trade_calculator is None:
            # Lazy initialization
            self.trade_calculator = TradeCalculatorWidget(self)
            self.trade_calculator.hide()
        
        self.trade_calc_visible = not self.trade_calc_visible
        
        if self.trade_calc_visible:
            # Show the calculator as a separate floating panel
            self.trade_calculator.show_animated()
            
            # Update button appearance
            self.trade_calc_button.setText("📊 Hide Calc")
            self.trade_calc_button.setStyleSheet("""
                QPushButton {
                    background-color: #0078d4;
                    color: white;
                    border: 1px solid #106ebe;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #106ebe;
                }
                QPushButton:pressed {
                    background-color: #0053a0;
                }
            """)
        else:
            # Hide the calculator
            self.trade_calculator.hide_animated()
            
            # Update button appearance
            self.trade_calc_button.setText("📊 Trade Calc")
            self.trade_calc_button.setStyleSheet("""
                QPushButton {
                    background-color: #3a3a4a;
                    color: #e8e8e8;
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #4a4a5a;
                    border-color: #777;
                }
                QPushButton:pressed {
                    background-color: #2a2a3a;
                }
            """)
    
            
    def select_currency(self, currency):
        """Handle currency button clicks"""
        # Find the currency pair in the combo box
        index = self.combo_ccy.findText(currency)
        if index >= 0:
            self.combo_ccy.setCurrentIndex(index)
            if self.debug_ui_actions:
                print(f"Selected currency: {currency}")
            # Highlight the selected button
            for ccy, btn in self.currency_buttons.items():
                if currency.startswith(ccy) or currency.endswith(ccy):
                    btn.setStyleSheet("QPushButton { background-color: #0078d4; border: 2px solid #106ebe; color: #ffffff; }")
                else:
                    btn.setStyleSheet("")  # Reset to default style
    
    def select_size(self, size):
        """Handle size button clicks"""
        self.order_size_input.setText(self.format_order_size(size))
        self.update_order_size()
        if self.debug_ui_actions:
            print(f"Selected size: {size}")
    
    def update_decimal_override(self):
        """Handle decimal places override input"""
        try:
            text = self.dp_override_input.text().strip()
            if text == "":
                # Remove override for current currency
                self.pricing_obj.remove_manual_decimal_override(self.pricing_obj.ccy)
            else:
                dp = int(text)
                if 0 <= dp <= 8:  # Reasonable range
                    self.pricing_obj.set_manual_decimal_override(self.pricing_obj.ccy, dp)
                else:
                    self.dp_override_input.setText("")  # Clear invalid input
            
            # Update current DP display if config is visible
            if self.config_visible:
                self.update_current_dp_display()
                
        except ValueError:
            self.dp_override_input.setText("")  # Clear invalid input
    
    def toggle_standard_decimal_places(self):
        """Toggle between standard and custom decimal place logic"""
        self.pricing_obj.toggle_standard_dp()
        is_standard = self.pricing_obj.config['use_standard_dp']
        
        if is_standard:
            self.toggle_standard_dp_button.setText("Standard DP: ON")
            self.toggle_standard_dp_button.setStyleSheet("QPushButton { background-color: #2d5a2d; color: #ffffff; }")
        else:
            self.toggle_standard_dp_button.setText("Standard DP: OFF")
            self.toggle_standard_dp_button.setStyleSheet("QPushButton { background-color: #5a2d2d; color: #ffffff; }")
    
    def toggle_config_section(self):
        """Toggle the visibility of config section"""
        self.config_visible = not self.config_visible
        self.config_widget.setVisible(self.config_visible)
        
        if self.config_visible:
            self.config_toggle_button.setText("▼ Config")
            # Update current DP display
            self.update_current_dp_display()
            # Expand window height slightly to accommodate config
            current_height = self.height()
            self.resize(self.width(), current_height + 40)
        else:
            self.config_toggle_button.setText("▶ Config")
            # Restore original height
            current_height = self.height()
            self.resize(self.width(), current_height - 40)
    
    def update_current_dp_display(self):
        """Update the current DP display in config section"""
        current_dp = self.pricing_obj.get_display_decimal_places()
        self.current_dp_value.setText(str(current_dp))
        
        # Color code based on whether it's standard or overridden
        if self.pricing_obj.ccy in self.pricing_obj.config['manual_dp_override']:
            self.current_dp_value.setStyleSheet("color: #ff6b6b;")  # Red for override
        else:
            self.current_dp_value.setStyleSheet("color: #51cf66;")  # Green for standard
    
    def check_connection_status(self):
        """Periodically check and update connection status"""
        if getattr(self.args, 'websocket', False) and websocket_sim_available:
            # Only update if status has changed
            self.update_data_source_status()
    

    def update_data_source_status(self):
        """Update the data source indicator based on connection status"""
        # Determine current data source
        if hasattr(self, 'current_data_source'):
            source = self.current_data_source
        else:
            # Auto-detect based on initial setup
            if fx.bloomberg_available and not getattr(self.args, 'websocket', False):
                source = "Bloomberg"
            elif getattr(self.args, 'websocket', False):
                source = "WebSocket"
            else:
                source = "Simulation"
            self.current_data_source = source
        
        # Update status display based on current source
        if source == "Bloomberg":
            # Always keep dropdown on Bloomberg when selected
            self.source_selector.blockSignals(True)
            self.source_selector.setCurrentText("Bloomberg")
            self.source_selector.blockSignals(False)
            
            if fx.bloomberg_available:
                # Bloomberg connected successfully
                self.data_source_icon.setText("●")
                self.data_source_icon.setStyleSheet("color: #51cf66;")  # Green
                self.data_source_status.setText("Bloomberg Live")
                self.data_source_status.setStyleSheet("color: #51cf66;")
                self.reconnect_button.setVisible(False)
            else:
                # Bloomberg selected but not available
                if hasattr(self, 'feed') and self.feed:
                    # Using WebSocket as fallback
                    if hasattr(self.feed, 'is_using_simulation') and self.feed.is_using_simulation():
                        # WebSocket also failed, using simulation
                        self.data_source_icon.setText("●")
                        self.data_source_icon.setStyleSheet("color: #ff6b6b;")  # Red
                        self.data_source_status.setText("⚠️ NOT LIVE - Using Simulation")
                        self.data_source_status.setStyleSheet("color: #ff6b6b; font-weight: bold;")
                    else:
                        # WebSocket working as fallback
                        self.data_source_icon.setText("●")
                        self.data_source_icon.setStyleSheet("color: #ffa94d;")  # Orange
                        self.data_source_status.setText("⚠️ NOT BLOOMBERG - Using WebSocket")
                        self.data_source_status.setStyleSheet("color: #ffa94d; font-weight: bold;")
                else:
                    # Using simulation as fallback
                    self.data_source_icon.setText("●")
                    self.data_source_icon.setStyleSheet("color: #ff6b6b;")  # Red
                    self.data_source_status.setText("⚠️ NOT LIVE - Using Simulation")
                    self.data_source_status.setStyleSheet("color: #ff6b6b; font-weight: bold;")
                
                self.reconnect_button.setVisible(True)
                self.reconnect_button.setText("Retry BBG")
        elif source == "WebSocket":
            # Always keep dropdown on WebSocket when it's selected
            self.source_selector.blockSignals(True)
            self.source_selector.setCurrentText("WebSocket")
            self.source_selector.blockSignals(False)
            
            if hasattr(self, 'feed'):
                # Check if we're in failover mode
                if hasattr(self.feed, 'is_using_simulation') and self.feed.is_using_simulation():
                    # WebSocket selected but using simulation - show RED
                    self.data_source_icon.setText("●")
                    self.data_source_icon.setStyleSheet("color: #ff6b6b;")  # Red for failed
                    self.data_source_status.setText("⚠️ NOT LIVE - Using Simulation")
                    self.data_source_status.setStyleSheet("color: #ff6b6b; font-weight: bold;")
                    self.reconnect_button.setVisible(True)
                    self.reconnect_button.setText("Retry WS")
                else:
                    # WebSocket connected successfully - show BLUE
                    self.data_source_icon.setText("●")
                    self.data_source_icon.setStyleSheet("color: #4a90e2;")  # Blue
                    self.data_source_status.setText("⚠️ WebSocket (Not Bloomberg)")
                    self.data_source_status.setStyleSheet("color: #ffa94d; font-weight: bold;")
                    self.reconnect_button.setVisible(True)
                    self.reconnect_button.setText("Reconnect")
            else:
                # No feed object yet, show as attempting connection
                self.data_source_icon.setText("●")
                self.data_source_icon.setStyleSheet("color: #ffd700;")  # Yellow
                self.data_source_status.setText("WebSocket Connecting...")
                self.data_source_status.setStyleSheet("color: #ffd700;")
                self.reconnect_button.setVisible(False)
        else:
            # Simulation mode explicitly selected
            self.source_selector.blockSignals(True)
            self.source_selector.setCurrentText("Simulation")
            self.source_selector.blockSignals(False)
            
            self.data_source_icon.setText("●")
            self.data_source_icon.setStyleSheet("color: #ff6b6b;")  # Red
            self.data_source_status.setText("⚠️ SIMULATION - Not Live Data")
            self.data_source_status.setStyleSheet("color: #ff6b6b; font-weight: bold;")
            self.reconnect_button.setVisible(False)
    
    def switch_data_source(self, source_name):
        """Switch between different data sources"""
        print(f"🔄 Switching data source to: {source_name}")
        
        # Stop current generator if exists
        if hasattr(self, 'feed') and self.feed:
            try:
                self.feed.shutdown()
            except:
                pass
            self.feed = None
        
        # Reset generator
        self.bbg_gen = None
        
        # Stop current connection during switch
        
        # Switch based on selection
        if source_name == "Bloomberg":
            # Always attempt Bloomberg connection when user selects it
            print("🔄 Attempting to connect to Bloomberg...")
            fx.check_bloomberg_availability()
            try:
                self.bb_obj = fx.bbg(self.pricing_obj)
                self.bbg_gen = self.bb_obj.run()
                fx.bloomberg_available = True  # Mark as available if successful
                print("✅ Switched to Bloomberg Terminal")
            except Exception as e:
                print(f"❌ Failed to connect to Bloomberg: {e}")
                fx.bloomberg_available = False
                
                # Try WebSocket as first fallback
                if websocket_sim_available:
                    try:
                        print("🔄 Attempting WebSocket as fallback...")
                        ws_url = getattr(self.args, 'ws_url', 'ws://localhost:8765')
                        self.feed = PriceFeedWithFailover(self.pricing_obj, url=ws_url)
                        self.bbg_gen = self.feed.run()
                        print("✅ Using WebSocket feed as Bloomberg fallback")
                    except Exception as ws_e:
                        print(f"❌ WebSocket also failed: {ws_e}")
                        # Fall back to simulation as last resort
                        sim_data = fx.simulated_data(self.pricing_obj)
                        self.bbg_gen = sim_data.generate_simulated_data()
                        print("🟡 Using simulated data (both Bloomberg and WebSocket unavailable)")
                else:
                    # No WebSocket available, use simulation
                    sim_data = fx.simulated_data(self.pricing_obj)
                    self.bbg_gen = sim_data.generate_simulated_data()
                    print("🟡 Using simulated data (Bloomberg unavailable, WebSocket not installed)")
                
        elif source_name == "WebSocket":
            if websocket_sim_available:
                try:
                    ws_url = getattr(self.args, 'ws_url', 'ws://localhost:8765')
                    self.feed = PriceFeedWithFailover(self.pricing_obj, url=ws_url)
                    self.bbg_gen = self.feed.run()
                    print(f"✅ Switched to WebSocket feed at {ws_url}")
                except Exception as e:
                    print(f"❌ Failed to connect to WebSocket: {e}")
                    # Fall back to simulation
                    self.switch_data_source("Simulation")
                    return
            else:
                print("❌ WebSocket module not available")
                # Fall back to simulation
                self.switch_data_source("Simulation")
                return
                
        else:  # Simulation
            sim_data = fx.simulated_data(self.pricing_obj)
            self.bbg_gen = sim_data.generate_simulated_data()
            print("✅ Switched to simulated data")
        
        # Update the data source tracking
        self.current_data_source = source_name
        
        # Update UI status
        self.update_data_source_status()
        
        # Clear any existing data and restart updates
        self.reinitialize_price_displays()
    
    def reconnect_current_source(self):
        """Reconnect to the current data source"""
        # Show reconnecting status
        self.reconnect_button.setEnabled(False)
        self.reconnect_button.setText("Connecting...")
        self.data_source_icon.setText("●")
        self.data_source_icon.setStyleSheet("color: #ffd700;")  # Yellow circle for attempting
        self.data_source_status.setText("Attempting reconnection...")
        self.data_source_status.setStyleSheet("color: #ffd700;")  # Yellow for attempting
        
        # Force UI update
        QApplication.processEvents()
        
        if hasattr(self, 'current_data_source'):
            print(f"🔄 Reconnecting to {self.current_data_source}...")
            self.switch_data_source(self.current_data_source)
        else:
            # Try to determine current source and reconnect
            if fx.bloomberg_available and not getattr(self.args, 'websocket', False):
                self.switch_data_source("Bloomberg")
            elif getattr(self.args, 'websocket', False):
                self.switch_data_source("WebSocket")
            else:
                self.switch_data_source("Simulation")
        
        # Re-enable button after attempt
        self.reconnect_button.setEnabled(True)
        self.reconnect_button.setText("Reconnect")
    
    def reinitialize_price_displays(self):
        """Clear and reinitialize price displays after switching data source"""
        # Clear current prices
        self.bid_px.setText("0.000000")
        self.offer_px.setText("0.000000")
        
        # Reset high/low tracking
        self.session_high = None
        self.session_low = None
        self.high_value.setText("High: -")
        self.low_value.setText("Low: -")
        
        # Clear graph data if visible
        if hasattr(self, 'connector') and self.connector:
            self.connector.clear()
    
    def attempt_bloomberg_reconnect(self):
        """Attempt to reconnect to Bloomberg API"""
        self.reconnect_button.setEnabled(False)
        self.reconnect_button.setText("Connecting...")
        
        # Check if Bloomberg is now available
        fx.check_bloomberg_availability()
        
        if fx.bloomberg_available:
            # Successfully connected to Bloomberg
            try:
                # Stop simulated data
                if hasattr(self, 'bbg_gen'):
                    # Clean up the generator
                    self.bbg_gen = None
                
                # Initialize Bloomberg connection
                self.bb_obj = fx.bloomberg_api(self.pricing_obj)
                self.bbg_gen = self.bb_obj.run()
                
                # Update status
                self.update_data_source_status()
                print("✅ Successfully connected to Bloomberg Terminal")
                
            except Exception as e:
                print(f"❌ Failed to connect to Bloomberg: {str(e)}")
                fx.bloomberg_available = False
                self.update_data_source_status()
        else:
            print("⚠️  Bloomberg Terminal not available")
        
        self.reconnect_button.setEnabled(True)
        self.reconnect_button.setText("Reconnect Bloomberg")
    
    def reset_decimal_places(self):
        """Reset decimal places to default for current currency"""
        self.pricing_obj.remove_manual_decimal_override(self.pricing_obj.ccy)
        self.dp_override_input.clear()
        self.update_current_dp_display()

    def reverse_order_size_method(self):
        # When we change the reverse size input
        self.reverse_label.setText(f"Reverse Amount: {self.pricing_obj.ccy[-3:]}:")
        bool_B_str = False
        bool_T_str = False
        try:
            text = self.reverse_size_input.text().lstrip('0')

            if not text.isnumeric():
                text = text.upper()
                if "B" in text:

                    text = text.strip("B")
                    text = (float(text) * 1_000_000_000) # BILLION
                    text = str(int(text)) #remove any . points
                    bool_B_str = True
                elif "T" in text:
                    text = text.strip("T")
                    text = (float(text) * 1_000_000_000_000) # TRILLION
                    text = str(int(text)) #remove any . points
                    bool_T_str = True

            self.reverse_size_input.setText(text)

        except:
            self.reverse_size_input.setText("0")
            return
        if text.isnumeric():
            # Ensure the input is a number
            self.pricing_obj.reverse_size_input = int(text)
            if self.pricing_obj.reverse_size_input > 0:
                # Ensure the reverse input is greate than 0
                self.pricing_obj.reverse_order_size()
              
                self.reverse_label.setText(f"Reverse Amount: {self.pricing_obj.ccy[-3:]}:")
                self.reverse_size_output_label.setText(f"{self.pricing_obj.reverse_size_output:,} {self.pricing_obj.ccy[:3]} ")

                if bool_B_str:
                    self.bb_obj.order_size = self.pricing_obj.reverse_size_output / 1_000_000
                elif bool_T_str:
                    self.bb_obj.order_size = self.pricing_obj.reverse_size_output / 1_000_000_000
                else:
                    self.bb_obj.order_size = self.pricing_obj.reverse_size_output
                self.order_size_input.setText(self.format_order_size(self.bb_obj.order_size))
                # self.order_size_input.
                self.update_order_size()

            else:
                self.reverse_size_input.setText("0")

        else:
            self.bb_obj.order_size = 10
            self.order_size_input.setText(self.format_order_size(self.bb_obj.order_size))
            
    # def get_cross_spread(self):

    #     text = self.ccy_cross.text()
        
    #     if len(text) ==6:
    #         self.pricing_obj.get_crosses_spreads(text, self.order_size)

    def typing_ccy_change(self):
        
        try:
        
            text = self.ccy_typing_input.text()
            

            if not text.isnumeric():
                text = (str(text)).upper()
                if " " in text:
                    self.ccy_typing_input.setText(str(""))
                    return
                if len(text) >6:
                    
                    self.ccy_typing_input.setText(str(text.replace(self.prior_text_ccy_typing_input,"")))

                elif len(text) == 6:
                    if text in self.pricing_obj.ccys:
                        
                        self.ccy_typing_input.setText(str(text))
                        self.combo_ccy.setCurrentIndex(self.combo_ccy.findText(text))
                        self.pricing_obj.deactivate_synthetic_mode()
                        self.cross_help_amount_lhs.setText("")
                        self.cross_help_amount_rhs.setText("")
                        self.cross_help_amount_lhs.setVisible(False)  # Hide when not in cross mode
                        self.cross_help_amount_rhs.setVisible(False)  # Hide when not in cross mode
                        self.spread_label.setFont(QFont('Arial', 12))
                        self.prior_text_ccy_typing_input = text
                        self.update_flags_display()
                    else:
                        try:
                            # SYNTHETIC CROSS
                            self.spread_label.setFont(QFont('Arial', 8))
                            self.pricing_obj.get_crosses_spreads(str(text),self.order_size)
                            # Check if cross creation was successful
                            if self.pricing_obj.synthetic_cross_mode == True:
                                # New section - update labels
                                # RESET LABELS
                                self.reverse_label.setText(f"Reverse Amount: {self.pricing_obj.ccy[-3:]}:")
                                self.reverse_size_input.setText("0")
                                self.reverse_size_output_label.setText(f"0 {self.pricing_obj.ccy[:3]} ")
                                # Show cross help labels in cross mode
                                self.cross_help_amount_lhs.setVisible(True)
                                self.cross_help_amount_rhs.setVisible(True)

                                self.combo_ccy.setCurrentIndex(self.combo_ccy.findText('CROSS'))
                                self.pricing_obj.ccy = self.pricing_obj.cross_ccy
                                self.pricing_obj.init_new_synthetic_in_bid_offer_array_dict()
                                self.pricing_obj.price_synthetic_cross()
                                self.update_order_size()
                                self.ccy_typing_input.setText(str(text.upper()))
                                # Update flags for synthetic cross
                                self.update_flags_display()
                                # Update pip value for synthetic cross
                                self.update_pip_value_display()
                                self.prior_text_ccy_typing_input = text
                            else:
                                # Cross creation failed - reset to regular mode
                                print(f"Failed to create cross for {text}")
                                self.ccy_typing_input.setText("")
                                self.spread_label.setFont(QFont('Arial', 12))
                                # Hide cross help text when cross creation fails
                                self.cross_help_amount_lhs.setVisible(False)
                                self.cross_help_amount_rhs.setVisible(False)
                                

                        except Exception as e:
                            print(e)
        
        except Exception as e:
            print(e)

    
    
    
        
    def update_order_size(self):
        bool_numeric = True
        # Only clear manual_spread when we're not in synthetic cross mode
        if not self.pricing_obj.synthetic_cross_mode:
            self.pricing_obj.manual_spread = 0.0
        text = self.order_size_input.text()
        
        # Parse the formatted input
        parsed_size = self.parse_order_size(text)
        if parsed_size > 0:
            self.order_size = parsed_size
            if self.debug_ui_actions:
                print(f"Order size changed to: {self.order_size}")
        else:
            bool_numeric = False

        if bool_numeric and not self.pricing_obj.synthetic_cross_mode:
            
            self.pricing_obj.get_spread(self.order_size)
            self.spread_label.setText(f"Spread pips: {self.pricing_obj.spread}")
            
            self.pricing_obj.price()
            # self.reverse_order_size_method()
        
        if self.pricing_obj.synthetic_cross_mode:
            self.pricing_obj.get_crosses_spreads(self.pricing_obj.cross_ccy,self.order_size)
            # print(f'Spread cross 1:{self.pricing_obj.ccy_1} Spread cross 2:{self.pricing_obj.ccy_2}')
            
            self.pricing_obj.ccy = self.pricing_obj.cross_ccy
            self.pricing_obj.init_new_synthetic_in_bid_offer_array_dict()
            self.pricing_obj.price_synthetic_cross()
            
            # Format spread display for crosses with leg information
            leg1_spread = f"{self.pricing_obj.ccy_1_leg}: {self.pricing_obj.spread_cross_1}"
            leg2_spread = f"{self.pricing_obj.ccy_2_leg}: {self.pricing_obj.spread_cross_2}"
            
            # Calculate total spread including manual spread adjustment
            # The spread from price_synthetic_cross is the market spread
            # We need to add the manual spread to get the total
            total_spread = round((self.pricing_obj.spread + self.pricing_obj.manual_spread) * 2) / 2
            
            self.spread_label.setText(f"Spread: {leg1_spread} | {leg2_spread} | Total: {total_spread}")
            self.spread_label.setFont(QFont('Arial', 10, QFont.Bold))
            
            # Set wider width for synthetic crosses to ensure full visibility
            self.spread_label.setMinimumWidth(300)
            self.spread_label.adjustSize()
            
            try:
                # Format order sizes - round to max 1 decimal place
                leg1_size = self.pricing_obj.order_size_ccy_leg_1
                leg2_size = self.pricing_obj.order_size_ccy_leg_2
                
                # Format leg 1 size
                if leg1_size == int(leg1_size):
                    leg1_fmt = f"{int(leg1_size)}"
                else:
                    leg1_fmt = f"{leg1_size:.1f}".rstrip('0').rstrip('.')
                
                # Format leg 2 size
                if leg2_size == int(leg2_size):
                    leg2_fmt = f"{int(leg2_size)}"
                else:
                    leg2_fmt = f"{leg2_size:.1f}".rstrip('0').rstrip('.')
                
                if self.pricing_obj.ccy_1_leg[-3:] == 'USD' and self.pricing_obj.ccy_2_leg[:3] == 'USD':
                    self.cross_help_amount_lhs.setText(f"Sell {leg1_fmt} {self.pricing_obj.ccy_1_leg}, Sell {leg2_fmt} {self.pricing_obj.ccy_2_leg}")
                    self.cross_help_amount_rhs.setText(f"Buy {leg1_fmt} {self.pricing_obj.ccy_1_leg}, Buy {leg2_fmt} {self.pricing_obj.ccy_2_leg}")
                    self.cross_help_amount_lhs.setVisible(True)
                    self.cross_help_amount_rhs.setVisible(True)
                
                elif self.pricing_obj.ccy_1_leg[:3] == 'USD' and self.pricing_obj.ccy_2_leg[:3] == 'USD':
                    self.cross_help_amount_lhs.setText(f"Buy {leg1_fmt} {self.pricing_obj.ccy_1_leg}, Sell {leg2_fmt} {self.pricing_obj.ccy_2_leg}")
                    self.cross_help_amount_rhs.setText(f"Sell {leg1_fmt} {self.pricing_obj.ccy_1_leg}, Buy {leg2_fmt} {self.pricing_obj.ccy_2_leg}")
                    self.cross_help_amount_lhs.setVisible(True)
                    self.cross_help_amount_rhs.setVisible(True)
                else:
                    # GBPNZD - GBPUSD and NZDUSD
                    self.cross_help_amount_lhs.setText(f"Sell {leg1_fmt} {self.pricing_obj.ccy_1_leg}, Buy {leg2_fmt} {self.pricing_obj.ccy_2_leg}")
                    self.cross_help_amount_rhs.setText(f"Buy {leg1_fmt} {self.pricing_obj.ccy_1_leg}, Sell {leg2_fmt} {self.pricing_obj.ccy_2_leg}")
                    self.cross_help_amount_lhs.setVisible(True)
                    self.cross_help_amount_rhs.setVisible(True)
            except Exception as e:
                print(e)
        try:
            
            self.pre_hedge_tittle.setText(f"Pre-Hedge 25%: {round(self.order_size/4)}M {self.pricing_obj.ccy[:3]}")
            
        except Exception as e:
            print(e)
        
        # Update pip value display when order size changes
        self.update_pip_value_display()

    def start_threaded_graph(self):
        self.running = True
        self.thread_graph = Thread(target=self.update_graph)
        self.thread_graph.daemon = True  # Make thread daemon so it exits when main thread exits
        self.thread_graph.start()

    def reset_live_graph(self):
        try:

            for i in range(self.deque_live_chart_max):
                timestamp = time.time()
                
                self.bid_connector.cb_append_data_point(self.pricing_obj.bid_offer[self.pricing_obj.ccy][0], 
                                                        timestamp)
                self.offer_connector.cb_append_data_point(self.pricing_obj.bid_offer[self.pricing_obj.ccy][1], 
                                                        timestamp)

                self.my_bid_connector.cb_append_data_point(self.pricing_obj.bid, 
                                                        timestamp)    
                self.my_offer_connector.cb_append_data_point(self.pricing_obj.offer, 
                                                        timestamp)
                # self.rsi_connector.cb_append_data_point(self.pricing_obj.bid_offer_signals_rolling[0,3], 
                #                                         timestamp)                                                
            
        except:
            None

    def update_graph_data(self):
        """Update graph data points using timer instead of thread"""
        try:
            # Cache frequently accessed values to reduce lookups
            timestamp = time.time()
            pricing_obj = self.pricing_obj
            ccy = pricing_obj.ccy
            
            # Update graph title with current currency pair
            self.chart_view.setTitle(f'{ccy} Live Pricing', color='#ffffff', size='12pt')
            
            # Get all values at once to avoid multiple dictionary lookups
            bid_raw = pricing_obj.bid_offer[ccy][0]
            offer_raw = pricing_obj.bid_offer[ccy][1]
            bid_calculated = pricing_obj.bid
            offer_calculated = pricing_obj.offer
            
            # Batch prepare all data points before updating connectors
            # This reduces the overhead of multiple function calls
            data_points = [
                (self.bid_connector, bid_raw),
                (self.offer_connector, offer_raw),
                (self.my_bid_connector, bid_calculated),
                (self.my_offer_connector, offer_calculated)
            ]
            
            # Update all data points in a single loop
            for connector, value in data_points:
                connector.cb_append_data_point(value, timestamp)
                
        except Exception as e:
            # More specific error message to help with debugging
            print(f"Error updating graph data for {getattr(self.pricing_obj, 'ccy', 'unknown')}: {e}")
    
    def update_graph(self):
        """Legacy threaded graph update method - now just sleeps to keep thread alive"""
        while self.running:
            # No longer doing work here - just keeping thread alive
            time.sleep(0.5)
    
    def check_connection_health(self):
        """Check if WebSocket connection is healthy based on update frequency"""
        # Always update status to catch failover state changes
        if self.current_data_source == "WebSocket":
            self.update_data_source_status()
            
            # Additional check for stale connections
            if hasattr(self, 'feed') and not self.feed.is_using_simulation():
                time_since_update = time.time() - self.last_price_update_time
                
                if time_since_update > 5.0:
                    # Connection seems stale, update status to show issue
                    self.data_source_icon.setText("●")
                    self.data_source_icon.setStyleSheet("color: #ffa94d;")  # Orange for stale
                    self.data_source_status.setText("WebSocket Stale - No Updates")
                    self.data_source_status.setStyleSheet("color: #ffa94d;")
                    self.reconnect_button.setVisible(True)
                    self.reconnect_button.setText("Reconnect")

    def update_timestamp(self, timestamp=None):
        """Update the timestamp display with market data time or system time fallback"""
        try:
            from datetime import datetime
            
            # If specific timestamp provided, use it
            if timestamp is not None:
                if isinstance(timestamp, str):
                    # Parse ISO format timestamp
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime("%H:%M:%S.%f")[:-3]
                    except:
                        time_str = timestamp[:8] if len(timestamp) >= 8 else timestamp
                else:
                    # Numeric timestamp
                    try:
                        dt = datetime.fromtimestamp(timestamp)
                        time_str = dt.strftime("%H:%M:%S.%f")[:-3]
                    except:
                        time_str = str(timestamp)
                
                # Green for explicitly provided timestamp
                self._set_market_timestamp_style()
            
            # Otherwise try to use market data timestamp from pricing object
            elif hasattr(self.pricing_obj, 'market_data_timestamp') and self.pricing_obj.market_data_timestamp:
                # Check if market data is recent (within last 5 seconds)
                current_time = time.time()
                if hasattr(self.pricing_obj, 'last_market_update_time'):
                    age = current_time - self.pricing_obj.last_market_update_time
                    if age < 5.0:  # Market data is fresh
                        # Use market data timestamp
                        dt = datetime.fromtimestamp(self.pricing_obj.market_data_timestamp)
                        time_str = dt.strftime("%H:%M:%S.%f")[:-3]
                        self._set_market_timestamp_style()
                    else:
                        # Market data is stale, use system time
                        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        self._set_stale_timestamp_style()
                else:
                    # No update time tracked, use system time
                    time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    self._set_default_timestamp_style()
            else:
                # No market timestamp available, use system time
                time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._set_default_timestamp_style()
            
            self.timestamp_label.setText(time_str)
            
        except Exception:
            # Fail silently - don't let timestamp errors affect trading
            # Use system time as ultimate fallback
            try:
                from datetime import datetime
                time_str = datetime.now().strftime("%H:%M:%S")
                self.timestamp_label.setText(time_str)
                self._set_default_timestamp_style()
            except:
                pass
    
    def _set_default_timestamp_style(self):
        """Set default timestamp style for system time"""
        self.timestamp_label.setStyleSheet("""
            QLabel {
                color: #e8e8e8;
                background-color: #2b2b2b;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
    
    def _set_market_timestamp_style(self):
        """Set timestamp style for market data time"""
        self.timestamp_label.setStyleSheet("""
            QLabel {
                color: #51cf66;
                background-color: #2b2b2b;
                border: 1px solid #51cf66;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
    
    def _set_stale_timestamp_style(self):
        """Set timestamp style for stale market data"""
        self.timestamp_label.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                background-color: #2b2b2b;
                border: 1px solid #ff6b6b;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)

    def update_prices(self):
        """Update price display with latest data from Bloomberg"""
        try:
            # Get next price update from Bloomberg generator
            prices = next(self.bbg_gen)
            
            # Track successful update time and update timestamp
            if prices:
                self.last_price_update_time = time.time()
                
                # Try to extract timestamp from data if available
                timestamp_found = False
                if isinstance(prices, dict):
                    # Check for timestamp in various formats
                    for key in ['timestamp', 'time', 'ts', 'datetime']:
                        if key in prices:
                            self.update_timestamp(prices[key])
                            self.last_update_timestamp = True
                            timestamp_found = True
                            break
                
                # If no timestamp in data, use current time
                if not timestamp_found:
                    self.update_timestamp()
                    self.last_update_timestamp = False
            
            # Cache pricing object reference to avoid repeated lookups
            pricing_obj = self.pricing_obj
            
            # Get prices based on mode (regular or inverse)
            if self.inverse_bool_active and hasattr(pricing_obj, 'inverse_bid') and pricing_obj.inverse_bid > 0:
                # Use inverse prices
                bid_text, bid_color = pricing_obj.get_formatted_inverse_bid_with_arrow()
                offer_text, offer_color = pricing_obj.get_formatted_inverse_offer_with_arrow()
                bid_pips_text = pricing_obj.pips_str_inverse_bid
                mid_pips_text = pricing_obj.pips_str_inverse_mid
                offer_pips_text = pricing_obj.pips_str_inverse_offer
                current_bid = pricing_obj.inverse_bid
                current_offer = pricing_obj.inverse_offer
                current_ccy = pricing_obj.inverse_ccy
                bid_direction = pricing_obj.inverse_bid_direction
                offer_direction = pricing_obj.inverse_offer_direction
            else:
                # Use regular prices
                bid_text, bid_color = pricing_obj.get_formatted_bid_with_arrow()
                offer_text, offer_color = pricing_obj.get_formatted_offer_with_arrow()
                bid_pips_text = pricing_obj.pips_str_bid
                mid_pips_text = getattr(pricing_obj, 'pips_str_mid', '')
                offer_pips_text = pricing_obj.pips_str_offer
                current_bid = pricing_obj.bid
                current_offer = pricing_obj.offer
                current_ccy = pricing_obj.ccy
                bid_direction = pricing_obj.bid_direction
                offer_direction = pricing_obj.offer_direction
            
            # Add debug monitoring
            if self.debug_monitor:
                self.debug_monitor.record_gui_update()
            
            # Update UI elements with colored text and dynamic backgrounds
            self.bid_label.setText(bid_text)
            
            # Style bid label with color and optional background highlight
            if bid_direction == 'up':
                bid_bg = "background-color: #1a3a1a;"  # Subtle green background for up
            elif bid_direction == 'down':
                bid_bg = "background-color: #3a1a1a;"  # Subtle red background for down
            else:
                bid_bg = "background-color: #2a2a2a;"  # Neutral background
                
            self.bid_label.setStyleSheet(f"""
                QLabel {{
                    {bid_bg}
                    border: 2px solid {bid_color};
                    border-radius: 6px;
                    padding: 10px;
                    color: {bid_color};
                    font-weight: bold;
                    font-size: 14px;
                }}
            """)
            
            self.offer_label.setText(offer_text)
            
            # Style offer label with color and optional background highlight
            if offer_direction == 'up':
                offer_bg = "background-color: #1a3a1a;"  # Subtle green background for up
            elif offer_direction == 'down':
                offer_bg = "background-color: #3a1a1a;"  # Subtle red background for down
            else:
                offer_bg = "background-color: #2a2a2a;"  # Neutral background
                
            self.offer_label.setStyleSheet(f"""
                QLabel {{
                    {offer_bg}
                    border: 2px solid {offer_color};
                    border-radius: 6px;
                    padding: 10px;
                    color: {offer_color};
                    font-weight: bold;
                    font-size: 14px;
                }}
            """)
            
            # Voice announcements for price updates
            if self.voice_enabled and self.voice_announcer and self.voice_announcer.is_enabled():
                self.voice_announcer.announce_price(
                    bid=current_bid,
                    offer=current_offer,
                    currency_pair=current_ccy,
                    bid_pips=bid_pips_text,
                    offer_pips=offer_pips_text
                )
            
            # Color code pip displays
            self.bid_pips_label.setText(bid_pips_text)
            self.bid_pips_label.setStyleSheet(f"""
                QLabel {{
                    color: {bid_color};
                    font-weight: bold;
                    font-size: 12px;
                    background-color: transparent;
                }}
            """)
            
            self.mid_pips_label.setText(mid_pips_text)
            
            self.offer_pips_label.setText(offer_pips_text)
            self.offer_pips_label.setStyleSheet(f"""
                QLabel {{
                    color: {offer_color};
                    font-weight: bold;
                    font-size: 12px;
                    background-color: transparent;
                }}
            """)
            
            # Always update high/low labels - these are essential for trading
            try:
                # Get current mid price for distance calculation
                current_mid = pricing_obj.mid
                
                if self.inverse_bool_active:
                    # Calculate inverse high/low
                    if pricing_obj.bid_offer[pricing_obj.ccy][3] > 0:  # Low becomes high
                        inverse_high = 1 / pricing_obj.bid_offer[pricing_obj.ccy][3]
                        convention = pricing_obj.get_inverse_decimal_convention()
                        high_val = f"{inverse_high:.{convention['round_dp']}f}"
                        high_numeric = inverse_high
                    else:
                        high_val = "N/A"
                        high_numeric = None
                    
                    if pricing_obj.bid_offer[pricing_obj.ccy][2] > 0:  # High becomes low
                        inverse_low = 1 / pricing_obj.bid_offer[pricing_obj.ccy][2]
                        convention = pricing_obj.get_inverse_decimal_convention()
                        low_val = f"{inverse_low:.{convention['round_dp']}f}"
                        low_numeric = inverse_low
                    else:
                        low_val = "N/A"
                        low_numeric = None
                        
                    # For inverse, use inverse mid
                    if hasattr(pricing_obj, 'inverse_mid'):
                        current_mid = pricing_obj.inverse_mid
                else:
                    # Use the reliable get_high_val and get_low_val methods
                    high_val = pricing_obj.get_high_val()
                    low_val = pricing_obj.get_low_val()
                    
                    # Get numeric values for distance calculation
                    high_numeric = pricing_obj.bid_offer[pricing_obj.ccy][2]
                    low_numeric = pricing_obj.bid_offer[pricing_obj.ccy][3]
                
                # Update high/low values
                self.high_value_label.setText(high_val)
                self.low_value_label.setText(low_val)
                
                # Calculate distances and range
                high_distance = None
                low_distance = None
                high_percent = None
                low_percent = None
                range_percent = None
                range_pips = None
                closer_to_high = False
                
                if high_numeric is not None and low_numeric is not None and high_numeric > 0 and low_numeric > 0 and current_mid > 0:
                    # Calculate distances in pips/points
                    decimal_factor = pricing_obj.decimal_places if hasattr(pricing_obj, 'decimal_places') else 10000
                    
                    # For JPY pairs and others with 2 decimal places
                    if pricing_obj.ccy.endswith('JPY') or (hasattr(pricing_obj, 'round_dp') and pricing_obj.round_dp == 2):
                        decimal_factor = 100
                    
                    high_distance = abs(high_numeric - current_mid) * decimal_factor
                    low_distance = abs(current_mid - low_numeric) * decimal_factor
                    
                    # Calculate percentages from current price
                    high_percent = (abs(high_numeric - current_mid) / current_mid) * 100 if current_mid != 0 else 0
                    low_percent = (abs(current_mid - low_numeric) / current_mid) * 100 if current_mid != 0 else 0
                    
                    # Calculate H-L range
                    range_pips = (high_numeric - low_numeric) * decimal_factor
                    range_percent = ((high_numeric - low_numeric) / low_numeric) * 100 if low_numeric != 0 else 0
                    
                    # Determine which is closer
                    closer_to_high = high_distance < low_distance
                
                # Update distance labels with both pips and percentage
                if high_distance is not None and high_percent is not None:
                    self.high_distance_label.setText(f"{high_distance:.0f}p {high_percent:.2f}%")
                else:
                    self.high_distance_label.setText("--p --%")
                    
                if low_distance is not None and low_percent is not None:
                    self.low_distance_label.setText(f"{low_distance:.0f}p {low_percent:.2f}%")
                else:
                    self.low_distance_label.setText("--p --%")
                
                # Update H-L range indicator
                if range_percent is not None and range_pips is not None:
                    if range_percent < 0.2:
                        range_text = "Tight"
                        range_color = "#4CAF50"  # Green
                    elif range_percent < 0.6:
                        range_text = "Normal"
                        range_color = "#FFA726"  # Orange
                    else:
                        range_text = "Wide"
                        range_color = "#FF5252"  # Red
                    
                    self.range_label.setText(f"{range_text}\n{range_pips:.0f}p {range_percent:.1f}%")
                    self.range_label.setStyleSheet(f"color: {range_color}; font-weight: bold; font-size: 8pt;")
                else:
                    self.range_label.setText("--")
                    self.range_label.setStyleSheet("color: #aaaaaa;")
                
                # Reset styles first - always do this
                self.high_widget.setStyleSheet("background: transparent;")
                self.low_widget.setStyleSheet("background: transparent;")
                self.high_distance_label.setStyleSheet("color: #999999; font-size: 8pt;")
                self.low_distance_label.setStyleSheet("color: #999999; font-size: 8pt;")
                
                # Highlight sections and update bias based on proximity
                if high_distance is not None and low_distance is not None:
                    
                    # Determine trading bias and highlight
                    # Check distances are valid
                    if high_distance is None or low_distance is None:
                        self.bias_label.setText("")
                        self.bias_label.setStyleSheet("color: #888888; font-size: 8pt;")
                    elif low_distance < 10 and low_distance < high_distance:  # Very close to low AND closer to low
                        self.bias_label.setText("Likely\nBuyer")
                        self.bias_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 8pt;")
                        self.low_widget.setStyleSheet("""
                            QWidget {
                                background-color: #152a15;
                                border-left: 2px solid #4CAF50;
                            }
                        """)
                        self.low_distance_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 8pt;")
                    elif high_distance < 10 and high_distance < low_distance:  # Very close to high AND closer to high
                        self.bias_label.setText("Likely\nSeller")
                        self.bias_label.setStyleSheet("color: #ff5252; font-weight: bold; font-size: 8pt;")
                        self.high_widget.setStyleSheet("""
                            QWidget {
                                background-color: #2a1515;
                                border-left: 2px solid #ff5252;
                            }
                        """)
                        self.high_distance_label.setStyleSheet("color: #ff5252; font-weight: bold; font-size: 8pt;")
                        
                    elif not closer_to_high and low_distance < 30:  # Check LOW proximity before HIGH
                        self.bias_label.setText("Near\nLow")
                        self.bias_label.setStyleSheet("color: #66bb6a; font-size: 8pt;")
                        self.low_widget.setStyleSheet("""
                            QWidget {
                                background-color: #101a10;
                            }
                        """)
                        self.low_distance_label.setStyleSheet("color: #66bb6a; font-size: 8pt;")
                    elif closer_to_high and high_distance < 30:
                        self.bias_label.setText("Near\nHigh")
                        self.bias_label.setStyleSheet("color: #ffa726; font-size: 8pt;")
                        self.high_widget.setStyleSheet("""
                            QWidget {
                                background-color: #1a1510;
                            }
                        """)
                        self.high_distance_label.setStyleSheet("color: #ffa726; font-size: 8pt;")
                        
                    else:
                        self.bias_label.setText("Neutral")
                        self.bias_label.setStyleSheet("color: #888888; font-size: 8pt;")
                else:
                    self.bias_label.setText("")
                    self.bias_label.setStyleSheet("color: #888888; font-size: 8pt;")
                    
            except Exception:
                # Fallback display in case of any errors
                self.high_value_label.setText("-.----")
                self.low_value_label.setText("-.----")
                self.high_distance_label.setText("--p --%")
                self.low_distance_label.setText("--p --%")
                self.range_label.setText("--")
                self.bias_label.setText("")
            
            # Update spread display
            if self.inverse_bool_active:
                # Calculate spread for inverse prices
                inv_convention = pricing_obj.get_inverse_decimal_convention()
                inverse_spread = (pricing_obj.inverse_offer - pricing_obj.inverse_bid) * inv_convention['decimal_places']
                self.spread_label.setText(f"Spread pips: {inverse_spread:.1f}")
                current_spread = inverse_spread
                # Reset to smaller width for inverse mode to avoid covering pip values
                self.spread_label.setMinimumWidth(150)
                self.spread_label.adjustSize()
            elif pricing_obj.synthetic_cross_mode:
                # For cross rates, show spread per leg
                if hasattr(pricing_obj, 'spread_cross_1') and hasattr(pricing_obj, 'spread_cross_2'):
                    leg1_spread = f"{pricing_obj.ccy_1_leg}: {pricing_obj.spread_cross_1}"
                    leg2_spread = f"{pricing_obj.ccy_2_leg}: {pricing_obj.spread_cross_2}"
                    total_spread = getattr(pricing_obj, 'spread', 0)
                    
                    self.spread_label.setText(f"Spread: {leg1_spread} | {leg2_spread} | Total: {total_spread}")
                    self.spread_label.setFont(QFont('Arial', 10, QFont.Bold))
                    current_spread = total_spread
            else:
                # For regular pairs, show simple spread with color coding
                if hasattr(pricing_obj, 'spread'):
                    current_spread = pricing_obj.spread
                    self.spread_label.setText(f"Spread pips: {current_spread}")
            
            # Color code spread changes for all modes
            if 'current_spread' in locals():
                if hasattr(self, 'previous_spread') and self.previous_spread > 0:
                    if current_spread > self.previous_spread:
                        # Spread widening - red (worse for trader)
                        spread_color = "#ff6b6b"
                        spread_bg = "#3a1a1a"
                    elif current_spread < self.previous_spread:
                        # Spread tightening - green (better for trader)
                        spread_color = "#51cf66"
                        spread_bg = "#1a3a1a"
                    else:
                        # No change
                        spread_color = "#ffffff"
                        spread_bg = "#2a2a2a"
                else:
                    spread_color = "#ffffff"
                    spread_bg = "#2a2a2a"
                
                self.spread_label.setStyleSheet(f"""
                    QLabel {{
                        background-color: {spread_bg};
                        border: 2px solid {spread_color};
                        border-radius: 4px;
                        padding: 6px;
                        color: {spread_color};
                        font-weight: bold;
                    }}
                """)
                
                self.previous_spread = current_spread
                
        except StopIteration:
            # Handle StopIteration specifically - this is normal when the generator ends
            pass  # Don't sleep here - let the timer handle the next call
        except Exception as e:
            # Only log serious errors, not common ones
            if "Error in update_prices" not in str(e):
                print(f"Error in update_prices: {e}")

    def update_pip_value_display(self):
        """Update the pip value display based on current pair"""
        try:
            # Get current pair
            current_pair = self.pricing_obj.ccy
            if current_pair == 'CROSS' or not current_pair or len(current_pair) != 6:
                self.pip_value_label.setText("")
                return
            
            # Special handling for waiting for rates
            if not hasattr(self, '_pip_retry_count'):
                self._pip_retry_count = {}
            
            # Check if this is a cross currency (not in standard G10 direct pairs)
            base_ccy = current_pair[:3]
            quote_ccy = current_pair[3:6]
            is_cross = False
            
            # List of currencies that have direct USD pairs
            usd_pairs = ['EUR', 'GBP', 'AUD', 'NZD', 'USD', 'CAD', 'CHF', 'JPY']
            
            # It's a cross if neither currency is USD
            if 'USD' not in current_pair:
                is_cross = True
            
            # For synthetic crosses or non-G10 crosses, always calculate fresh
            if self.pricing_obj.synthetic_cross_mode or is_cross:
                if hasattr(self.pricing_obj, 'cross_ccy') and self.pricing_obj.cross_ccy:
                    # Use the cross currency from pricing object
                    current_pair = self.pricing_obj.cross_ccy
                
                # Get rate from bid_offer or calculate it
                if current_pair in self.pricing_obj.bid_offer:
                    bid_data = self.pricing_obj.bid_offer[current_pair]
                    if hasattr(bid_data, '__len__') and len(bid_data) >= 2:
                        bid = float(bid_data[0])
                        ask = float(bid_data[1])
                        if bid > 0 and ask > 0:
                            current_rate = (bid + ask) / 2
                        else:
                            # Use pricing object's calculated values
                            current_rate = (self.pricing_obj.bid + self.pricing_obj.offer) / 2
                    else:
                        current_rate = (self.pricing_obj.bid + self.pricing_obj.offer) / 2
                else:
                    # For crosses not in bid_offer, try to calculate from USD pairs
                    base_usd_pair = base_ccy + 'USD'
                    usd_base_pair = 'USD' + base_ccy
                    quote_usd_pair = quote_ccy + 'USD'
                    usd_quote_pair = 'USD' + quote_ccy
                    
                    base_to_usd = None
                    quote_to_usd = None
                    
                    # Get base currency to USD rate
                    if base_usd_pair in self.pricing_obj.bid_offer:
                        rate_data = self.pricing_obj.bid_offer[base_usd_pair]
                        if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                            base_to_usd = float((rate_data[0] + rate_data[1]) / 2)
                    elif usd_base_pair in self.pricing_obj.bid_offer:
                        rate_data = self.pricing_obj.bid_offer[usd_base_pair]
                        if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                            usd_to_base = float((rate_data[0] + rate_data[1]) / 2)
                            if usd_to_base > 0:
                                base_to_usd = 1.0 / usd_to_base
                    
                    # Get quote currency to USD rate
                    if quote_usd_pair in self.pricing_obj.bid_offer:
                        rate_data = self.pricing_obj.bid_offer[quote_usd_pair]
                        if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                            quote_to_usd = float((rate_data[0] + rate_data[1]) / 2)
                    elif usd_quote_pair in self.pricing_obj.bid_offer:
                        rate_data = self.pricing_obj.bid_offer[usd_quote_pair]
                        if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                            usd_to_quote = float((rate_data[0] + rate_data[1]) / 2)
                            if usd_to_quote > 0:
                                quote_to_usd = 1.0 / usd_to_quote
                    
                    # Calculate cross rate
                    if base_to_usd and quote_to_usd:
                        current_rate = base_to_usd / quote_to_usd
                    else:
                        # Fall back to pricing object's values if available
                        if hasattr(self.pricing_obj, 'bid') and hasattr(self.pricing_obj, 'offer'):
                            if self.pricing_obj.bid > 0 and self.pricing_obj.offer > 0:
                                current_rate = (self.pricing_obj.bid + self.pricing_obj.offer) / 2
                            else:
                                # Can't calculate rate
                                self.pip_value_label.setText("")
                                return
                        else:
                            self.pip_value_label.setText("")
                            return
                
                # For synthetic crosses, ensure leg rates are included
                rates_for_calc = dict(self.pricing_obj.bid_offer)
                
                # Add leg rates if available and not already included
                if hasattr(self.pricing_obj, 'ccy_1_leg') and self.pricing_obj.ccy_1_leg:
                    if self.pricing_obj.ccy_1_leg in self.pricing_obj.bid_offer:
                        rates_for_calc[self.pricing_obj.ccy_1_leg] = self.pricing_obj.bid_offer[self.pricing_obj.ccy_1_leg]
                
                if hasattr(self.pricing_obj, 'ccy_2_leg') and self.pricing_obj.ccy_2_leg:
                    if self.pricing_obj.ccy_2_leg in self.pricing_obj.bid_offer:
                        rates_for_calc[self.pricing_obj.ccy_2_leg] = self.pricing_obj.bid_offer[self.pricing_obj.ccy_2_leg]
                
                # Calculate pip value with all available rates
                result = self.pip_calculator.calculate_pip_value(
                    current_pair, 
                    current_rate, 
                    rates_for_calc
                )
            else:
                # Try to get cached pip value first for regular pairs
                cached_pip_value = self.pip_calculator.get_cached_pip_value(current_pair)
                
                if cached_pip_value is not None:
                    # Use cached value - create result dict for formatting
                    result = {
                        'success': True,
                        'pip_in_usd': cached_pip_value,
                        'base_ccy': current_pair[:3],
                        'quote_ccy': current_pair[3:6]
                    }
                else:
                    # Fall back to calculation if not cached
                    if current_pair in self.pricing_obj.bid_offer:
                        bid_data = self.pricing_obj.bid_offer[current_pair]
                        # Extract bid and ask values, handling numpy arrays
                        if hasattr(bid_data, '__len__') and len(bid_data) >= 2:
                            bid = float(bid_data[0])
                            ask = float(bid_data[1])
                        else:
                            self.pip_value_label.setText("")
                            return
                            
                        if bid > 0 and ask > 0:
                            current_rate = (bid + ask) / 2
                        else:
                            self.pip_value_label.setText("")
                            return
                    else:
                        self.pip_value_label.setText("")
                        return
                    
                    # Calculate pip value
                    result = self.pip_calculator.calculate_pip_value(
                        current_pair, 
                        current_rate, 
                        self.pricing_obj.bid_offer
                    )
            
            # Display result in compact format
            if result.get('success'):
                # Clear retry count on success
                if current_pair in self._pip_retry_count:
                    del self._pip_retry_count[current_pair]
                    
                # Show both per-million and scaled values
                compact_text = self.pip_calculator.format_compact_display_both(result, self.order_size)
                self.pip_value_label.setText(f"pip: {compact_text}")
                self.pip_value_label.setToolTip(
                    self.pip_calculator.format_pip_value_display_scaled(result, self.order_size)
                )
                
                # Subtle styling
                self.pip_value_label.setStyleSheet("""
                    QLabel {
                        background-color: rgba(42, 58, 74, 0.7);
                        border-radius: 3px;
                        padding: 2px 6px;
                        color: #a0a0a0;
                        border: 1px solid rgba(58, 74, 90, 0.5);
                        font-size: 11px;
                    }
                """)
            else:
                # If calculation failed, retry a few times for crosses and synthetic pairs
                if self.pricing_obj.synthetic_cross_mode or is_cross:
                    retry_count = self._pip_retry_count.get(current_pair, 0)
                    if retry_count < 5:
                        self._pip_retry_count[current_pair] = retry_count + 1
                        # Schedule retry in 500ms
                        QTimer.singleShot(500, self.update_pip_value_display)
                        self.pip_value_label.setText("pip: ...")
                    else:
                        # Give up after 5 retries
                        self.pip_value_label.setText("")
                else:
                    # Hide when no USD conversion available
                    self.pip_value_label.setText("")
                
        except Exception as e:
            # Silently fail - don't spam console with errors
            self.pip_value_label.setText("")
    
    def precalculate_pip_values(self):
        """Pre-calculate pip values for all currency pairs at initialization"""
        try:
            # Get all available currency pairs
            all_pairs = self.pricing_obj.ccys
            
            # Debug: Check if rates are populated
            print(f"Pre-calculating pip values for {len(all_pairs)} pairs...")
            available_rates = [pair for pair in self.pricing_obj.bid_offer.keys() if len(pair) == 6]
            print(f"Available rates: {len(available_rates)} pairs")
            
            # Pre-calculate pip values
            self.pip_calculator.precalculate_all_pairs(all_pairs, self.pricing_obj.bid_offer)
            
            # Debug: Check EURCNH specifically
            if 'EURCNH' in self.pip_calculator.static_pip_values:
                print(f"EURCNH pip value cached: ${self.pip_calculator.static_pip_values['EURCNH']:.2f}")
            
            # Update display for current pair
            self.update_pip_value_display()
        except Exception as e:
            print(f"Error pre-calculating pip values: {e}")
    
    def stop_thread(self):

        self.running = False
        self.thread_graph.join()
    
    def closeEvent(self, event):
        """Handle window close event - cleanup voice and other resources"""
        print("🔄 Cleaning up resources...")
        
        # Disable voice if it's running
        if self.voice_announcer and self.voice_enabled:
            print("🔇 Stopping voice announcements...")
            self.voice_announcer.disable()
        
        # Stop WebSocket if running
        if hasattr(self, 'websocket_sim') and self.websocket_sim:
            print("📡 Stopping WebSocket connection...")
            self.websocket_sim.stop()
        
        # Stop any timers
        if hasattr(self, 'timer') and self.timer:
            self.timer.stop()
        
        print("✅ Cleanup complete")
        event.accept()



def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='FX GUI Trading Application (April 2025)')
    parser.add_argument('--debug', action='store_true', 
                        help='Enable debug mode with performance monitoring')
    parser.add_argument('--debug-interval', type=int, default=10,
                        help='Debug report interval in seconds (default: 10)')
    parser.add_argument('--websocket', action='store_true',
                        help='Use WebSocket-based price feed simulator instead of built-in')
    parser.add_argument('--ws-url', default='ws://localhost:8765',
                        help='WebSocket server URL (default: ws://localhost:8765)')
    parser.add_argument('--voice-speed', type=float, default=1.5,
                        help='Voice playback speed multiplier (default: 1.5, range: 0.5-3.0)')
    return parser.parse_args()

if __name__ == '__main__':
    # Parse command line arguments
    args = parse_arguments()
    
    # Initialize debug monitoring
    init_debug_monitor(enabled=args.debug, report_interval=args.debug_interval)
    
    if args.debug:
        print("🔍 Debug mode enabled!")
        print(f"📊 Performance reports every {args.debug_interval} seconds")
        print("💡 Tip: Use Ctrl+C to exit gracefully")
        print("-" * 60)
    
    app = QApplication(sys.argv)
    my_app = MyApp(args)
    
    # Ensure we start with graph hidden
    my_app.graph_visible = False
    my_app.chart_view.setVisible(False)
    my_app.expand_graph_button.setVisible(False)
    my_app.resize(my_app.window_width_without_graph, my_app.window_height_without_graph)
    my_app.setMaximumWidth(my_app.window_width_without_graph)  # Set maximum width to prevent stretching
    
    # Set column stretch to 0 for the graph column
    my_app.layout.setColumnStretch(0, 0)
    
    my_app.show()
    my_app.start_threaded_graph()
    app.aboutToQuit.connect(my_app.stop_thread)
    
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
        my_app.stop_thread()
        sys.exit(0)