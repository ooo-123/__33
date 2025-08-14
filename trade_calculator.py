from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QPushButton, QLabel, QFrame,
                             QHeaderView, QAbstractItemView, QLineEdit, QTextEdit,
                             QDialog, QDialogButtonBox, QTabWidget, QMenu)
from PyQt5.QtCore import Qt, QPropertyAnimation, QRect, QTimer, pyqtSignal, QEvent, QPoint
from PyQt5.QtGui import QFont, QColor, QKeyEvent
from typing import List, Tuple, Optional, Dict
import re
import json


class TradeEntry:
    """Data model for individual trade entries"""
    def __init__(self, price: float = 0.0, size: float = 0.0):
        self.price = price
        self.size = size
        self.exit_price = 0.0  # For closed trades
        self.pnl = 0.0  # Realized P&L for closed trades
    
    @property
    def total_value(self) -> float:
        return self.price * self.size


class TabData:
    """Data model for each tab"""
    def __init__(self, name: str = "New Tab"):
        self.name = name
        self.currency_pair = name  # Assume tab name is currency pair
        self.trades: List[TradeEntry] = []
        self.table_widget = None  # Will be set when tab is created
        self.current_price = 0.0  # Current market price for P&L calculation
        self.closed_trades: List[TradeEntry] = []  # For realized P&L
        self.big_figure = 0  # Current big figure for pip entry
        self.is_jpy_pair = False  # Track if it's a JPY pair for pip calculation


class WeightedAverageCalculator:
    """Handles weighted average price calculations with net position support"""
    
    @staticmethod
    def calculate(trades: List[TradeEntry]) -> Tuple[float, float, float]:
        """
        Calculate weighted average price, net size, and total value
        Supports both long and short positions (negative sizes)
        Returns: (weighted_avg_price, net_size, total_value)
        """
        if not trades:
            return 0.0, 0.0, 0.0
        
        # Calculate net size (can be positive, negative, or zero)
        net_size = sum(t.size for t in trades)
        
        # Calculate weighted sum (price * size for each trade)
        weighted_sum = sum(t.price * t.size for t in trades)
        
        # Calculate average price
        if net_size != 0:
            weighted_avg = weighted_sum / net_size
        else:
            weighted_avg = 0.0
        
        # Total value is the absolute sum of all trade values
        # This represents the total notional value traded
        total_value = abs(weighted_sum)
        
        return weighted_avg, net_size, total_value
    
    @staticmethod
    def calculate_unrealized_pnl(trades: List[TradeEntry], current_price: float) -> float:
        """Calculate unrealized P&L for open positions"""
        if not trades or current_price <= 0:
            return 0.0
        
        pnl = 0.0
        for trade in trades:
            if trade.size != 0:
                # For long positions (positive size): (current - entry) * size
                # For short positions (negative size): (current - entry) * size (size is negative)
                pnl += (current_price - trade.price) * trade.size
        
        return pnl
    
    @staticmethod
    def calculate_realized_pnl(closed_trades: List[TradeEntry]) -> float:
        """Calculate realized P&L from closed trades"""
        return sum(t.pnl for t in closed_trades)
    
    @staticmethod
    def calculate_realized_unrealized_pnl(trades: List[TradeEntry], current_price: float) -> Tuple[float, float, List[Tuple[int, float]]]:
        """
        Calculate realized and unrealized P&L using FIFO (First-In, First-Out) accounting
        Returns: (realized_pnl, unrealized_pnl, [(trade_index, realized_amount), ...])
        """
        if not trades or current_price <= 0:
            return 0.0, 0.0, []
        
        realized_pnl = 0.0
        realized_trades = []
        
        # Create a FIFO queue for long and short positions
        long_queue = []  # List of (price, size, trade_index) tuples
        short_queue = []  # List of (price, size, trade_index) tuples
        
        for i, trade in enumerate(trades):
            if trade.size == 0:
                continue
                
            if trade.size > 0:  # Buy/Long
                remaining_size = trade.size
                
                # First, close any short positions (FIFO)
                while remaining_size > 0 and short_queue:
                    short_price, short_size, short_idx = short_queue[0]
                    
                    # Calculate how much we're closing
                    closing_size = min(remaining_size, short_size)
                    
                    # Realized P&L: We were short, now buying
                    # Profit = (short price - buy price) * size
                    trade_pnl = (short_price - trade.price) * closing_size
                    realized_pnl += trade_pnl
                    realized_trades.append((i, trade_pnl))
                    
                    # Update the short queue
                    if closing_size >= short_size:
                        short_queue.pop(0)  # Remove fully closed position
                    else:
                        short_queue[0] = (short_price, short_size - closing_size, short_idx)
                    
                    remaining_size -= closing_size
                
                # Add any remaining size to long queue
                if remaining_size > 0:
                    long_queue.append((trade.price, remaining_size, i))
                    
            else:  # Sell/Short
                remaining_size = abs(trade.size)
                
                # First, close any long positions (FIFO)
                while remaining_size > 0 and long_queue:
                    long_price, long_size, long_idx = long_queue[0]
                    
                    # Calculate how much we're closing
                    closing_size = min(remaining_size, long_size)
                    
                    # Realized P&L: We were long, now selling
                    # Profit = (sell price - buy price) * size
                    trade_pnl = (trade.price - long_price) * closing_size
                    realized_pnl += trade_pnl
                    realized_trades.append((i, trade_pnl))
                    
                    # Update the long queue
                    if closing_size >= long_size:
                        long_queue.pop(0)  # Remove fully closed position
                    else:
                        long_queue[0] = (long_price, long_size - closing_size, long_idx)
                    
                    remaining_size -= closing_size
                
                # Add any remaining size to short queue
                if remaining_size > 0:
                    short_queue.append((trade.price, remaining_size, i))
        
        # Calculate unrealized P&L on remaining positions
        unrealized_pnl = 0.0
        
        # Unrealized P&L on long positions
        for price, size, _ in long_queue:
            unrealized_pnl += (current_price - price) * size
        
        # Unrealized P&L on short positions
        for price, size, _ in short_queue:
            unrealized_pnl += (price - current_price) * size
        
        return realized_pnl, unrealized_pnl, realized_trades


class TradeCalculatorWidget(QWidget):
    """Slide-out trade calculator panel"""
    
    # Signal emitted when panel visibility changes
    visibility_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.parent_app = parent
        self.panel_width = 450  # Increased width for better visibility
        self.animation_duration = 300
        self.is_visible = False
        self.tabs_data: Dict[int, TabData] = {}  # Store data for each tab
        self.max_tabs = 10
        self.calculation_timer = QTimer()
        self.calculation_timer.timeout.connect(self._perform_calculation)
        self.calculation_timer.setSingleShot(True)
        
        # Timer to sync with market prices
        self.price_sync_timer = QTimer()
        self.price_sync_timer.timeout.connect(self._sync_market_price)
        self.price_sync_timer.start(1000)  # Update every second
        
        # Set window attributes
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # Connect to parent's move event to keep panel attached
        if parent:
            parent.installEventFilter(self)
        
        self._init_ui()
        self._apply_styling()
    
    def _is_jpy_pair(self, currency_pair: str) -> bool:
        """Check if the currency pair involves JPY"""
        return 'JPY' in currency_pair.upper()
    
    def _normalize_currency_pair(self, pair: str) -> str:
        """Normalize currency pair format (e.g., EUR/USD -> EURUSD)"""
        if not pair:
            return ""
        # Remove common separators and spaces
        normalized = pair.upper().replace('/', '').replace('-', '').replace(' ', '').replace('_', '')
        # Validate it's a 6-character currency pair
        if len(normalized) == 6 and normalized.isalpha():
            return normalized
        return ""
    
    def _update_current_tab_currency(self, currency_pair: str):
        """Update current tab name and currency pair"""
        tab_data = self._get_current_tab_data()
        if not tab_data or not currency_pair:
            return
            
        # Update tab data
        tab_data.currency_pair = currency_pair
        tab_data.is_jpy_pair = self._is_jpy_pair(currency_pair)
        
        # Update tab name
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, currency_pair)
    
    def _convert_pip_to_price(self, pip_value: str, tab_data: TabData) -> float:
        """Convert pip value to full price based on big figure"""
        try:
            value = float(pip_value)
            
            # If value is already a full price (has decimal places or > 999)
            if '.' in pip_value or value > 999:
                return value
            
            # For pip values, construct full price
            if tab_data.is_jpy_pair:
                # JPY pairs: typically XXX.XX format
                # If big figure is 108 and pip is 24, result is 108.24
                if tab_data.big_figure > 0:
                    return tab_data.big_figure + (value / 100)
                else:
                    # Guess big figure from recent trades
                    if tab_data.trades:
                        recent_price = tab_data.trades[-1].price
                        big_fig = int(recent_price)
                        return big_fig + (value / 100)
                    return value / 100
            else:
                # Non-JPY pairs: typically X.XXXX format
                # If big figure is 0.65 and pip is 24, result is 0.6524
                if tab_data.big_figure > 0:
                    # Big figure for non-JPY is like 1.08 or 0.65
                    # Extract the first 2 significant digits after removing the decimal
                    if tab_data.big_figure >= 1:
                        # For prices like 1.0856, big figure is 108
                        big_int = int(tab_data.big_figure * 100) 
                    else:
                        # For prices like 0.6524, big figure is 65
                        big_int = int(tab_data.big_figure * 10000) // 100
                    return (big_int * 100 + value) / 10000
                else:
                    # Guess big figure from recent trades
                    if tab_data.trades:
                        recent_price = tab_data.trades[-1].price
                        big_fig = int(recent_price * 100)
                        return (big_fig + value) / 10000
                    return value / 10000
        except ValueError:
            return 0.0
    
    def _update_big_figure(self, tab_data: TabData, price: float):
        """Update the big figure based on the latest price"""
        if tab_data.is_jpy_pair:
            tab_data.big_figure = int(price)
        else:
            tab_data.big_figure = int(price * 100) / 100
        
    def _init_ui(self):
        """Initialize the user interface"""
        # Main layout
        self.setFixedWidth(self.panel_width)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        
        # Title
        title_label = QLabel("Trade Calculator")
        title_label.setFont(QFont('Arial', 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #ffffff; padding: 2px;")
        layout.addWidget(title_label)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setUsesScrollButtons(True)  # Enable scroll buttons
        self.tab_widget.setElideMode(Qt.ElideRight)  # Elide text on the right if too long
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # Add button for new tabs
        self.add_tab_button = QPushButton("+")
        self.add_tab_button.setFixedSize(20, 20)
        self.add_tab_button.clicked.connect(self._add_new_tab)
        self.add_tab_button.setToolTip("Add new tab")
        self.add_tab_button.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #999999;
                border: 1px solid #444444;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #3a3a4a;
                color: #e8e8e8;
            }
            QPushButton:pressed {
                background-color: #252525;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                color: #555555;
                border-color: #333333;
            }
        """)
        self.tab_widget.setCornerWidget(self.add_tab_button, Qt.TopRightCorner)
        
        # Add initial tab
        self._add_new_tab("EURUSD")
        
        layout.addWidget(self.tab_widget, 1)  # Give tab widget stretch priority
        
        # Button controls
        button_layout = QHBoxLayout()
        button_layout.setSpacing(4)
        
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._add_trade_row)
        self.add_button.setFixedHeight(24)
        
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_selected_row)
        self.remove_button.setFixedHeight(24)
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_all_trades)
        self.clear_button.setFixedHeight(24)
        
        self.paste_button = QPushButton("Paste")
        self.paste_button.clicked.connect(self._show_paste_dialog)
        self.paste_button.setFixedHeight(24)
        
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.paste_button)
        layout.addLayout(button_layout)
        
        # Summary section
        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Box)
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(6, 4, 6, 4)
        summary_layout.setSpacing(2)
        
        # Summary fields in horizontal layout
        summary_h_layout = QHBoxLayout()
        summary_h_layout.setSpacing(15)
        
        self.total_size_label = QLabel("Net: 0")
        self.avg_price_label = QLabel("Avg: 0.00000")
        self.total_value_label = QLabel("Value: 0.00")
        
        for label in [self.total_size_label, self.avg_price_label, self.total_value_label]:
            label.setFont(QFont('Arial', 9))
            summary_h_layout.addWidget(label)
        
        summary_layout.addLayout(summary_h_layout)
        
        layout.addWidget(summary_frame)
        
        # Copy summary button
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self._copy_summary_to_clipboard)
        self.copy_button.setFixedHeight(22)
        layout.addWidget(self.copy_button)
        
        # P&L Section
        pnl_frame = QFrame()
        pnl_frame.setFrameShape(QFrame.Box)
        pnl_layout = QVBoxLayout(pnl_frame)
        pnl_layout.setContentsMargins(6, 4, 6, 4)
        pnl_layout.setSpacing(3)
        
        # Current price input
        price_layout = QHBoxLayout()
        price_label = QLabel("Price:")
        price_label.setFont(QFont('Arial', 9))
        price_label.setFixedWidth(35)
        self.current_price_input = QLineEdit("0.00000")
        self.current_price_input.setAlignment(Qt.AlignRight)
        self.current_price_input.setFixedHeight(20)
        self.current_price_input.setFont(QFont('Arial', 9))
        self.current_price_input.textChanged.connect(self._on_current_price_changed)
        price_layout.addWidget(price_label)
        price_layout.addWidget(self.current_price_input)
        pnl_layout.addLayout(price_layout)
        
        # P&L display fields
        self.unrealized_pnl_label = QLabel("Unrealized: 0.00")
        self.realized_pnl_label = QLabel("Realized: 0.00")
        self.total_pnl_label = QLabel("Total: 0.00")
        
        # Style P&L labels
        for label in [self.unrealized_pnl_label, self.realized_pnl_label, self.total_pnl_label]:
            label.setFont(QFont('Arial', 9))
            pnl_layout.addWidget(label)
        
        # Close position button
        self.close_position_button = QPushButton("Close")
        self.close_position_button.clicked.connect(self._close_position)
        self.close_position_button.setToolTip("Close all open positions at current price")
        self.close_position_button.setFixedHeight(22)
        pnl_layout.addWidget(self.close_position_button)
        
        layout.addWidget(pnl_frame)
        
        # Note: Initial row will be added when tab is created
    
    def _create_tab_content(self):
        """Create the content widget for a tab"""
        # Container widget
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Table for trade entries
        trade_table = QTableWidget()
        trade_table.setColumnCount(4)
        trade_table.setHorizontalHeaderLabels(['#', 'Price', 'Size', 'Total'])
        
        # Set column widths
        header = trade_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        trade_table.setColumnWidth(0, 35)
        
        # Set row height for better visibility
        trade_table.verticalHeader().setDefaultSectionSize(28)
        
        # Table properties
        trade_table.setAlternatingRowColors(False)  # Single color for all rows
        trade_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        trade_table.itemChanged.connect(self._on_item_changed)
        
        # Install event filter for keyboard navigation
        trade_table.installEventFilter(self)
        
        layout.addWidget(trade_table)
        
        return container, trade_table
    
    def _add_new_tab(self, name: str = None):
        """Add a new tab"""
        if self.tab_widget.count() >= self.max_tabs:
            return
        
        # Generate default name if not provided
        if not name:
            existing_names = [self.tabs_data[i].name for i in self.tabs_data]
            for i in range(1, self.max_tabs + 2):
                default_name = f"Tab {i}"
                if default_name not in existing_names:
                    name = default_name
                    break
        
        # Create tab data
        tab_data = TabData(name)
        tab_data.is_jpy_pair = self._is_jpy_pair(name)
        
        # Create tab content
        container, trade_table = self._create_tab_content()
        tab_data.table_widget = trade_table
        
        # Add tab
        index = self.tab_widget.addTab(container, name)
        self.tabs_data[index] = tab_data
        
        # Add custom close button
        if self.tab_widget.count() > 1:  # Only add close button if more than one tab
            close_button = QPushButton("×")
            close_button.setFixedSize(16, 16)
            close_button.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #999999;
                    border: none;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #ff4444;
                    color: white;
                    border-radius: 8px;
                }
            """)
            close_button.clicked.connect(lambda: self._close_tab(index))
            self.tab_widget.tabBar().setTabButton(index, self.tab_widget.tabBar().RightSide, close_button)
        
        # Switch to new tab
        self.tab_widget.setCurrentIndex(index)
        
        # Add initial row
        self._add_trade_row()
        
        # Update close buttons when adding new tab
        self._update_close_buttons()
        
        # Update add button visibility
        if self.tab_widget.count() >= self.max_tabs:
            self.add_tab_button.setEnabled(False)
    
    def _close_tab(self, index: int):
        """Close a tab"""
        if self.tab_widget.count() <= 1:
            return  # Keep at least one tab
        
        # Remove tab data
        if index in self.tabs_data:
            del self.tabs_data[index]
        
        # Remove tab
        self.tab_widget.removeTab(index)
        
        # Re-index remaining tabs
        new_tabs_data = {}
        for i in range(self.tab_widget.count()):
            if i >= index and (i + 1) in self.tabs_data:
                new_tabs_data[i] = self.tabs_data[i + 1]
            elif i < index and i in self.tabs_data:
                new_tabs_data[i] = self.tabs_data[i]
        self.tabs_data = new_tabs_data
        
        # Update close buttons
        self._update_close_buttons()
        
        # Update add button
        if self.tab_widget.count() < self.max_tabs:
            self.add_tab_button.setEnabled(True)
    
    def _update_close_buttons(self):
        """Update close button visibility based on tab count"""
        if self.tab_widget.count() == 1:
            # Hide close button on the last remaining tab
            self.tab_widget.tabBar().setTabButton(0, self.tab_widget.tabBar().RightSide, None)
        else:
            # Ensure all tabs have close buttons
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabBar().tabButton(i, self.tab_widget.tabBar().RightSide) is None:
                    close_button = QPushButton("×")
                    close_button.setFixedSize(16, 16)
                    close_button.setStyleSheet("""
                        QPushButton {
                            background-color: transparent;
                            color: #999999;
                            border: none;
                            font-size: 14px;
                            font-weight: bold;
                            padding: 0px;
                        }
                        QPushButton:hover {
                            background-color: #ff4444;
                            color: white;
                            border-radius: 8px;
                        }
                    """)
                    close_button.clicked.connect(lambda checked, idx=i: self._close_tab(idx))
                    self.tab_widget.tabBar().setTabButton(i, self.tab_widget.tabBar().RightSide, close_button)
    
    def _on_tab_changed(self, index: int):
        """Handle tab change"""
        if index >= 0:
            self._perform_calculation()
            self._sync_market_price()  # Sync price when switching tabs
            self._update_pnl_display()
    
    def _get_current_tab_data(self) -> Optional[TabData]:
        """Get the current tab's data"""
        index = self.tab_widget.currentIndex()
        return self.tabs_data.get(index)
    
    def _get_current_table(self) -> Optional[QTableWidget]:
        """Get the current tab's table widget"""
        tab_data = self._get_current_tab_data()
        return tab_data.table_widget if tab_data else None
        
    def _apply_styling(self):
        """Apply dark theme styling to match the main GUI"""
        self.setStyleSheet("""
            TradeCalculatorWidget {
                background-color: #1e1e1e;
                color: #e8e8e8;
                border: 2px solid #444444;
                border-radius: 8px;
            }
            
            QWidget {
                background-color: #1e1e1e;
                color: #e8e8e8;
            }
            
            QLabel {
                color: #e8e8e8;
            }
            
            QFrame[frameShape="4"] {
                color: #444444;
            }
            
            QFrame[frameShape="16"] {
                background-color: #2b2b2b;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 10px;
            }
            
            QTabWidget::pane {
                border: 1px solid #444444;
                background-color: #1e1e1e;
                border-radius: 4px;
            }
            
            QTabBar::tab {
                background-color: #2b2b2b;
                color: #999999;
                border: 1px solid #444444;
                padding: 4px 20px 4px 8px;  /* Reduced padding, less on right for close button */
                margin-right: 1px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 60px;
                max-width: 120px;
                font-size: 11px;
            }
            
            QTabBar::tab:selected {
                background-color: #3d5a8a;
                color: #ffffff;
                border-bottom-color: #3d5a8a;
            }
            
            QTabBar::tab:hover {
                background-color: #3a3a4a;
                color: #e8e8e8;
            }
            
            QTabBar::close-button {
                image: url(none.png);  /* Hide default image */
                subcontrol-position: right;
                subcontrol-origin: padding;
                position: absolute;
                right: 8px;
                width: 16px;
                height: 16px;
                padding: 0px;
            }
            
            QTabBar::close-button:hover {
                background-color: #ff4444;
                border-radius: 8px;
            }
            
            QTabBar::scroller {
                width: 20px;
            }
            
            QTabBar QToolButton {
                background-color: #2b2b2b;
                color: #999999;
                border: 1px solid #444444;
            }
            
            QTabBar QToolButton:hover {
                background-color: #3a3a4a;
                color: #e8e8e8;
            }
            
            QTabBar QToolButton::right-arrow {
                image: none;
                width: 0px;
            }
            
            QTabBar QToolButton::left-arrow {
                image: none;
                width: 0px;
            }
            
            QTabBar QToolButton::right-arrow:enabled {
                color: #e8e8e8;
            }
            
            QTabBar QToolButton::left-arrow:enabled {
                color: #e8e8e8;
            }
            
            QTableWidget {
                background-color: #2b2b2b;
                border: 1px solid #444444;
                border-radius: 4px;
                gridline-color: #444444;
                font-size: 11px;
            }
            
            QTableWidget::item {
                padding: 4px 8px;
                border: none;
            }
            
            QTableWidget::item:selected {
                background-color: #3d5a8a;
                color: #ffffff;
            }
            
            QHeaderView::section {
                background-color: #2b2b2b;
                color: #e8e8e8;
                padding: 5px;
                border: none;
                border-bottom: 2px solid #444444;
                font-weight: bold;
            }
            
            QPushButton {
                background-color: #3a3a4a;
                color: #e8e8e8;
                border: 1px solid #555;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-height: 25px;
            }
            
            QPushButton:hover {
                background-color: #4a4a5a;
                border-color: #777;
            }
            
            QPushButton:pressed {
                background-color: #2a2a3a;
            }
            
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666666;
                border-color: #333333;
            }
            
            QLineEdit {
                background-color: #2b2b2b;
                color: #e8e8e8;
                border: 1px solid #444444;
                padding: 4px;
                border-radius: 3px;
            }
            
            QLineEdit:focus {
                border-color: #4a90e2;
            }
        """)
        
        # Enable custom context menu for tabs
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)
    
    def _show_tab_context_menu(self, pos):
        """Show context menu for tab operations"""
        tab_bar = self.tab_widget.tabBar()
        index = tab_bar.tabAt(pos)
        
        if index < 0:
            return
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                color: #e8e8e8;
                border: 1px solid #444444;
            }
            QMenu::item:selected {
                background-color: #3d5a8a;
            }
        """)
        
        rename_action = menu.addAction("Rename Tab")
        rename_action.triggered.connect(lambda: self._rename_tab(index))
        
        menu.exec_(tab_bar.mapToGlobal(pos))
    
    def _rename_tab(self, index: int):
        """Rename a tab"""
        current_name = self.tab_widget.tabText(index)
        
        # Create simple rename dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Rename Tab")
        dialog.setModal(True)
        dialog.setFixedSize(300, 100)
        
        layout = QVBoxLayout(dialog)
        
        # Input field
        line_edit = QLineEdit(current_name)
        line_edit.selectAll()
        layout.addWidget(line_edit)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        # Apply styling
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #e8e8e8;
            }
            QLineEdit {
                background-color: #2b2b2b;
                color: #e8e8e8;
                border: 1px solid #444;
                padding: 5px;
                border-radius: 4px;
            }
        """)
        
        if dialog.exec_():
            new_name = line_edit.text().strip()
            if new_name and new_name != current_name:
                self.tab_widget.setTabText(index, new_name)
                if index in self.tabs_data:
                    self.tabs_data[index].name = new_name
                    self.tabs_data[index].currency_pair = new_name
                    self.tabs_data[index].is_jpy_pair = self._is_jpy_pair(new_name)
    
    def _add_trade_row(self):
        """Add a new row to the current tab's trade table"""
        trade_table = self._get_current_table()
        tab_data = self._get_current_tab_data()
        
        if not trade_table or not tab_data:
            return
            
        row_count = trade_table.rowCount()
        trade_table.insertRow(row_count)
        
        # Row number (read-only)
        row_item = QTableWidgetItem(str(row_count + 1))
        row_item.setFlags(row_item.flags() & ~Qt.ItemIsEditable)
        row_item.setTextAlignment(Qt.AlignCenter)
        trade_table.setItem(row_count, 0, row_item)
        
        # Price and Size (editable)
        for col in [1, 2]:
            item = QTableWidgetItem("0")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            trade_table.setItem(row_count, col, item)
        
        # Total (read-only)
        total_item = QTableWidgetItem("0.00")
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_item.setForeground(QColor('#999999'))
        trade_table.setItem(row_count, 3, total_item)
        
        # Add corresponding TradeEntry
        tab_data.trades.append(TradeEntry())
    
    def _remove_selected_row(self):
        """Remove the currently selected row"""
        trade_table = self._get_current_table()
        tab_data = self._get_current_tab_data()
        
        if not trade_table or not tab_data:
            return
            
        current_row = trade_table.currentRow()
        if current_row >= 0:
            trade_table.removeRow(current_row)
            del tab_data.trades[current_row]
            self._renumber_rows()
            self._schedule_calculation()
    
    def _clear_all_trades(self):
        """Clear all trade entries"""
        trade_table = self._get_current_table()
        tab_data = self._get_current_tab_data()
        
        if not trade_table or not tab_data:
            return
            
        trade_table.setRowCount(0)
        tab_data.trades.clear()
        self._add_trade_row()  # Add one empty row
        self._update_summary(0, 0, 0)
    
    def _renumber_rows(self):
        """Update row numbers after deletion"""
        trade_table = self._get_current_table()
        if not trade_table:
            return
            
        for row in range(trade_table.rowCount()):
            item = trade_table.item(row, 0)
            if item:
                item.setText(str(row + 1))
    
    def _on_item_changed(self, item):
        """Handle changes to table items"""
        if item.column() in [1, 2]:  # Price or Size columns
            row = item.row()
            self._update_trade_data(row)
            self._schedule_calculation()
    
    def _update_trade_data(self, row: int):
        """Update trade data from table"""
        trade_table = self._get_current_table()
        tab_data = self._get_current_tab_data()
        
        if not trade_table or not tab_data or row >= len(tab_data.trades):
            return
        
        # Parse price (handle pip entry)
        price_item = trade_table.item(row, 1)
        if price_item:
            price_text = price_item.text().strip()
            if price_text:
                price = self._convert_pip_to_price(price_text, tab_data)
                tab_data.trades[row].price = price
                
                # Update big figure if this is a full price
                if price > 0 and ('.' in price_text or float(price_text) > 999):
                    self._update_big_figure(tab_data, price)
                
                # Update the display to show full price
                if price != float(price_text):
                    price_item.setText(f"{price:.5f}" if not tab_data.is_jpy_pair else f"{price:.2f}")
            else:
                tab_data.trades[row].price = 0.0
        
        # Parse size with K/M/B support
        size_item = trade_table.item(row, 2)
        if size_item:
            tab_data.trades[row].size = self._parse_size(size_item.text())
        
        # Update total column
        total = tab_data.trades[row].total_value
        total_item = trade_table.item(row, 3)
        if total_item:
            total_item.setText(f"{total:,.2f}")
    
    def _parse_size(self, text: str) -> float:
        """Parse size text supporting K/M/B suffixes and negative values
        Default: numbers without suffix are treated as millions
        """
        text = text.strip().upper()
        if not text:
            return 0.0
        
        try:
            # Check for negative sign
            is_negative = text.startswith('-')
            if is_negative:
                text = text[1:]
            
            # Handle suffixes
            if text.endswith('K'):
                value = float(text[:-1]) * 1_000
            elif text.endswith('M'):
                value = float(text[:-1]) * 1_000_000
            elif text.endswith('B'):
                value = float(text[:-1]) * 1_000_000_000
            else:
                # No suffix - default to millions
                value = float(text) * 1_000_000
            
            return -value if is_negative else value
        except ValueError:
            return 0.0
    
    def _schedule_calculation(self):
        """Schedule calculation with debouncing"""
        self.calculation_timer.stop()
        self.calculation_timer.start(50)  # 50ms delay
        # Also try to sync market price
        self._sync_market_price()
    
    def _perform_calculation(self):
        """Perform weighted average calculation and update summary"""
        # Skip if panel is not visible
        if not self.is_visible:
            return
            
        tab_data = self._get_current_tab_data()
        if not tab_data:
            return
        
        # Skip if no trades
        if not tab_data.trades:
            return
            
        # Include all trades, even with negative sizes (shorts)
        weighted_avg, net_size, total_value = WeightedAverageCalculator.calculate(tab_data.trades)
        self._update_summary(weighted_avg, net_size, total_value)
        self._update_pnl_display()
    
    def _update_summary(self, avg_price: float, net_size: float, total_value: float):
        """Update summary labels"""
        self.total_size_label.setText(f"Net: {self._format_size(net_size)}")
        self.avg_price_label.setText(f"Avg: {avg_price:.5f}")
        self.total_value_label.setText(f"Value: {total_value:,.2f}")
    
    def _format_size(self, size: float) -> str:
        """Format size for display, handling negative values"""
        abs_size = abs(size)
        sign = "-" if size < 0 else ""
        
        if abs_size >= 1_000_000_000:
            return f"{sign}{abs_size/1_000_000_000:.1f}B"
        elif abs_size >= 1_000_000:
            return f"{sign}{abs_size/1_000_000:.1f}M"
        elif abs_size >= 1_000:
            return f"{sign}{abs_size/1_000:.1f}K"
        else:
            return f"{sign}{abs_size:,.0f}"
    
    def _on_current_price_changed(self, text: str):
        """Handle current price input changes"""
        tab_data = self._get_current_tab_data()
        if not tab_data:
            return
        
        try:
            # Convert pip value to full price if needed
            price = self._convert_pip_to_price(text, tab_data)
            tab_data.current_price = price
            
            # Update big figure if this is a full price
            if price > 0 and ('.' in text or float(text) > 999):
                self._update_big_figure(tab_data, price)
            
            self._update_pnl_display()
        except ValueError:
            tab_data.current_price = 0.0
            self._update_pnl_display()
    
    def _update_pnl_display(self):
        """Update P&L display with current calculations"""
        # Skip if panel is not visible
        if not self.is_visible:
            return
            
        tab_data = self._get_current_tab_data()
        if not tab_data:
            return
        
        # Skip if no trades and no closed trades
        if not tab_data.trades and not tab_data.closed_trades:
            self._update_pnl_label(self.unrealized_pnl_label, "Unrealized", 0)
            self._update_pnl_label(self.realized_pnl_label, "Realized", 0) 
            self._update_pnl_label(self.total_pnl_label, "Total", 0)
            return
        
        # Calculate realized and unrealized P&L using the new method
        realized_pnl, unrealized_pnl, _ = WeightedAverageCalculator.calculate_realized_unrealized_pnl(
            tab_data.trades, tab_data.current_price
        )
        
        # Add any P&L from previously closed positions
        realized_pnl += WeightedAverageCalculator.calculate_realized_pnl(tab_data.closed_trades)
        
        # Total P&L
        total_pnl = unrealized_pnl + realized_pnl
        
        # Update labels with color coding
        self._update_pnl_label(self.unrealized_pnl_label, "Unrealized", unrealized_pnl)
        self._update_pnl_label(self.realized_pnl_label, "Realized", realized_pnl)
        self._update_pnl_label(self.total_pnl_label, "Total", total_pnl)
        
        # Update current price input if switching tabs
        if not self.current_price_input.hasFocus():  # Don't update if user is typing
            if tab_data.is_jpy_pair:
                self.current_price_input.setText(f"{tab_data.current_price:.2f}")
            else:
                self.current_price_input.setText(f"{tab_data.current_price:.5f}")
    
    def _update_pnl_label(self, label: QLabel, prefix: str, value: float):
        """Update P&L label with color based on value"""
        formatted_value = f"{value:,.2f}"
        label.setText(f"{prefix}: {formatted_value}")
        
        # Color coding
        if value > 0:
            label.setStyleSheet("color: #4CAF50;")  # Green for profit
        elif value < 0:
            label.setStyleSheet("color: #f44336;")  # Red for loss
        else:
            label.setStyleSheet("color: #e8e8e8;")  # Default color for zero
    
    def _copy_summary_to_clipboard(self):
        """Copy summary to clipboard"""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        
        tab_data = self._get_current_tab_data()
        if not tab_data:
            return
        
        # Include all trades (including shorts)
        weighted_avg, net_size, total_value = WeightedAverageCalculator.calculate(tab_data.trades)
        
        # Get current tab name
        current_index = self.tab_widget.currentIndex()
        tab_name = self.tab_widget.tabText(current_index) if current_index >= 0 else "Unknown"
        
        # Calculate P&L
        realized_pnl, unrealized_pnl, _ = WeightedAverageCalculator.calculate_realized_unrealized_pnl(
            tab_data.trades, tab_data.current_price
        )
        realized_pnl += WeightedAverageCalculator.calculate_realized_pnl(tab_data.closed_trades)
        total_pnl = unrealized_pnl + realized_pnl
        
        summary_text = f"""Trade Summary - {tab_name}:
Net Size: {self._format_size(net_size)}
Average Price: {weighted_avg:.5f}
Total Value: {total_value:,.2f}

P&L Analysis:
Current Price: {tab_data.current_price:.5f}
Unrealized P&L: {unrealized_pnl:,.2f}
Realized P&L: {realized_pnl:,.2f}
Total P&L: {total_pnl:,.2f}

Trade Details:
"""
        for i, trade in enumerate(tab_data.trades):
            if trade.size != 0:  # Skip empty trades
                action = "Long" if trade.size > 0 else "Short"
                trade_pnl = (tab_data.current_price - trade.price) * trade.size
                summary_text += f"{i+1}. {action} {self._format_size(abs(trade.size))} @ {trade.price:.5f}, Value: {trade.total_value:,.2f}, P&L: {trade_pnl:,.2f}\n"
        
        clipboard.setText(summary_text)
        
        # Visual feedback
        original_text = self.copy_button.text()
        self.copy_button.setText("Copied!")
        QTimer.singleShot(1000, lambda: self.copy_button.setText(original_text))
    
    def show_animated(self):
        """Show the panel with slide-in animation"""
        if self.is_visible:
            return
        
        self.is_visible = True
        
        # Position the panel to the right of the parent window
        if self.parent_app:
            parent_geometry = self.parent_app.geometry()
            
            # Set panel size
            self.setFixedWidth(self.panel_width)
            self.setFixedHeight(parent_geometry.height())
            
            # Calculate position - panel appears to the right of main window
            start_x = parent_geometry.x() + parent_geometry.width() + self.panel_width
            end_x = parent_geometry.x() + parent_geometry.width() + 5  # 5px gap
            y_pos = parent_geometry.y()
            
            # Set initial position off-screen
            self.move(start_x, y_pos)
            self.show()
            
            # Animate sliding in from off-screen
            self.animation = QPropertyAnimation(self, b"pos")
            self.animation.setDuration(self.animation_duration)
            self.animation.setStartValue(self.pos())
            self.animation.setEndValue(QPoint(end_x, y_pos))
            self.animation.start()
        
        self.visibility_changed.emit(True)
    
    def hide_animated(self):
        """Hide the panel with slide-out animation"""
        if not self.is_visible:
            return
        
        self.is_visible = False
        
        # Animate sliding out to the right
        if self.parent_app:
            parent_geometry = self.parent_app.geometry()
            
            self.animation = QPropertyAnimation(self, b"pos")
            self.animation.setDuration(self.animation_duration)
            
            current_pos = self.pos()
            end_x = parent_geometry.x() + parent_geometry.width() + self.panel_width + 10
            end_pos = QPoint(end_x, current_pos.y())
            
            self.animation.setStartValue(current_pos)
            self.animation.setEndValue(end_pos)
            self.animation.finished.connect(self.hide)
            self.animation.start()
        
        self.visibility_changed.emit(False)
    
    def toggle_visibility(self):
        """Toggle panel visibility"""
        if self.is_visible:
            self.hide_animated()
        else:
            self.show_animated()
    
    def eventFilter(self, source, event):
        """Handle keyboard navigation in the table and parent window events"""
        # Handle parent window move/resize events
        if source == self.parent_app and self.is_visible:
            if event.type() == QEvent.Move or event.type() == QEvent.Resize:
                # Update panel position to stay attached to parent
                parent_geometry = self.parent_app.geometry()
                new_x = parent_geometry.x() + parent_geometry.width() + 5
                new_y = parent_geometry.y()
                self.move(new_x, new_y)
                
                if event.type() == QEvent.Resize:
                    # Update panel height to match parent
                    self.setFixedHeight(parent_geometry.height())
        
        # Handle keyboard shortcuts for tab navigation
        if isinstance(event, QKeyEvent) and event.type() == QEvent.KeyPress:
            if event.modifiers() == Qt.ControlModifier:
                # Ctrl+Tab to go to next tab
                if event.key() == Qt.Key_Tab:
                    current = self.tab_widget.currentIndex()
                    next_tab = (current + 1) % self.tab_widget.count()
                    self.tab_widget.setCurrentIndex(next_tab)
                    return True
                # Ctrl+Shift+Tab to go to previous tab
                elif event.key() == Qt.Key_Backtab:
                    current = self.tab_widget.currentIndex()
                    prev_tab = (current - 1) % self.tab_widget.count()
                    self.tab_widget.setCurrentIndex(prev_tab)
                    return True
        
        # Check if source is any of the trade tables
        if isinstance(event, QKeyEvent) and hasattr(source, 'currentRow'):
            # Check if this is one of our trade tables
            tab_data = self._get_current_tab_data()
            if tab_data and source == tab_data.table_widget:
                if event.type() == QEvent.KeyPress:
                    current_row = source.currentRow()
                    current_col = source.currentColumn()
                    
                    if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                        # Move to next cell on Enter
                        if current_col == 1:  # Price column
                            source.setCurrentCell(current_row, 2)  # Move to Size
                        elif current_col == 2:  # Size column
                            if current_row < source.rowCount() - 1:
                                source.setCurrentCell(current_row + 1, 1)  # Next row, Price
                            else:
                                # Add new row and move to it
                                self._add_trade_row()
                                source.setCurrentCell(current_row + 1, 1)
                        return True
                        
                    elif event.key() == Qt.Key_Tab:
                        # Handle Tab key similarly
                        if current_col == 1:
                            source.setCurrentCell(current_row, 2)
                            return True
                        elif current_col == 2 and current_row < source.rowCount() - 1:
                            source.setCurrentCell(current_row + 1, 1)
                            return True
        
        return super().eventFilter(source, event)
    
    def _sync_market_price(self):
        """Sync current price with market data from main GUI"""
        if not self.is_visible or not self.parent_app:
            return
            
        tab_data = self._get_current_tab_data()
        if not tab_data:
            return
        
        # Skip if no trades - no need to sync price
        if not tab_data.trades:
            return
        
        # Get the current currency pair from tab name (handle both EUR/USD and EURUSD formats)
        tab_ccy = tab_data.currency_pair.replace('/', '').replace(' ', '').upper()
        
        # Try to get price from parent app
        try:
            # Method 1: If tab currency matches current selection in main GUI
            if hasattr(self.parent_app, 'pricing_obj') and self.parent_app.pricing_obj:
                pricing = self.parent_app.pricing_obj
                
                # Check if the current selection matches
                current_ccy = getattr(pricing, 'ccy', '').replace('/', '').upper()
                if current_ccy == tab_ccy:
                    bid = getattr(pricing, 'bid', 0)
                    offer = getattr(pricing, 'offer', 0)
                    if bid > 0 and offer > 0:
                        mid_price = (bid + offer) / 2
                        self._update_price_if_changed(tab_data, mid_price)
                        return
                
                # Method 2: Try to get from bid_offer_array_dict (stores prices for all currencies)
                if hasattr(pricing, 'bid_offer_array_dict') and tab_ccy in pricing.bid_offer_array_dict:
                    try:
                        # Get the price array for this currency
                        price_data = pricing.bid_offer_array_dict[tab_ccy]
                        if price_data and len(price_data) > 0:
                            # Usually structured as [[size, bid, offer], ...]
                            # Get the first entry or find entry matching current order size
                            for entry in price_data:
                                if len(entry) >= 3:
                                    bid = entry[1]
                                    offer = entry[2]
                                    if bid > 0 and offer > 0:
                                        mid_price = (bid + offer) / 2
                                        self._update_price_if_changed(tab_data, mid_price)
                                        return
                    except:
                        pass
                
                # Method 2b: Try to get from bid_offer dictionary (includes synthetic crosses)
                if hasattr(pricing, 'bid_offer') and tab_ccy in pricing.bid_offer:
                    try:
                        # Get the latest price data
                        price_data = pricing.bid_offer[tab_ccy]
                        if price_data and len(price_data) >= 4:
                            # Structure: [mid, bid, offer, high, low]
                            bid = price_data[1]
                            offer = price_data[2]
                            if bid > 0 and offer > 0:
                                mid_price = (bid + offer) / 2
                                self._update_price_if_changed(tab_data, mid_price)
                                return
                    except:
                        pass
                
                # Method 3 removed - switching currencies was causing issues with synthetic crosses
                    
        except Exception:
            pass  # Silently ignore errors
    
    def _update_price_if_changed(self, tab_data: TabData, new_price: float):
        """Update price if it has changed significantly"""
        if tab_data.current_price == 0 or abs(tab_data.current_price - new_price) > 0.00001:
            tab_data.current_price = new_price
            self._update_big_figure(tab_data, new_price)
            # Don't update input if user is typing
            if not self.current_price_input.hasFocus():
                if tab_data.is_jpy_pair:
                    self.current_price_input.setText(f"{new_price:.2f}")
                else:
                    self.current_price_input.setText(f"{new_price:.5f}")
            self._update_pnl_display()
    
    def _close_position(self):
        """Close all open positions at current price"""
        tab_data = self._get_current_tab_data()
        if not tab_data or tab_data.current_price <= 0:
            return
        
        # Calculate current net position
        weighted_avg, net_size, _ = WeightedAverageCalculator.calculate(tab_data.trades)
        
        if net_size == 0:
            return  # No position to close
        
        # Calculate P&L for closing position
        closing_pnl = (tab_data.current_price - weighted_avg) * net_size
        
        # Create a closed trade entry for realized P&L tracking
        closed_trade = TradeEntry(weighted_avg, net_size)
        closed_trade.exit_price = tab_data.current_price
        closed_trade.pnl = closing_pnl
        tab_data.closed_trades.append(closed_trade)
        
        # Clear open trades
        tab_data.trades.clear()
        self._clear_all_trades()
        
        # Update displays
        self._update_pnl_display()
    
    def _show_paste_dialog(self):
        """Show dialog for pasting trade data"""
        dialog = PasteDataDialog(self)
        if dialog.exec_():
            data = dialog.get_data()
            self._parse_pasted_data(data)
    
    def _parse_pasted_data(self, data: str):
        """Parse pasted data and populate the table"""
        # Clear existing trades
        self._clear_all_trades()
        
        detected_currency = None
        
        # Try to parse as JSON first
        try:
            trades = json.loads(data)
            if isinstance(trades, list):
                for trade in trades:
                    if isinstance(trade, dict):
                        # Try to extract currency pair from various fields
                        for field in ['symbol', 'pair', 'currency', 'instrument', 'ccy', 'ticker']:
                            if field in trade and trade[field]:
                                detected_currency = self._normalize_currency_pair(str(trade[field]))
                                break
                        
                        # Handle platform-specific JSON format
                        if 'price' in trade and 'quantity' in trade and 'side' in trade:
                            price = float(trade['price'])
                            size = float(trade['quantity'])
                            if trade['side'].lower() in ['sell', 'short']:
                                size = -abs(size)
                            self._add_trade_with_data(price, size)
                        # Handle simple format
                        elif 'price' in trade and 'size' in trade:
                            self._add_trade_with_data(float(trade['price']), float(trade['size']))
                    elif isinstance(trade, (list, tuple)) and len(trade) >= 2:
                        self._add_trade_with_data(float(trade[0]), float(trade[1]))
                
                # Update tab name if currency was detected
                if detected_currency:
                    self._update_current_tab_currency(detected_currency)
                    
                self._schedule_calculation()
                return
        except:
            pass
        
        # Try to parse as semicolon-separated trades (platform string format)
        if ';' in data:
            trades = data.split(';')
            for trade_str in trades:
                ccy = self._parse_single_trade_string(trade_str.strip())
                if ccy and not detected_currency:
                    detected_currency = ccy
            
            # Update tab name if currency was detected
            if detected_currency:
                self._update_current_tab_currency(detected_currency)
                
            self._schedule_calculation()
            return
        
        # Try to parse as text lines
        lines = data.strip().split('\n')
        for line in lines:
            ccy = self._parse_single_trade_string(line)
            if ccy and not detected_currency:
                detected_currency = ccy
        
        # Update tab name if currency was detected
        if detected_currency:
            self._update_current_tab_currency(detected_currency)
            
        self._schedule_calculation()
    
    def _parse_single_trade_string(self, line: str):
        """Parse a single trade from string format
        Returns: detected currency pair or None
        """
        if not line:
            return None
            
        detected_currency = None
        
        # Handle platform string format: "BUY 2.5M EUR/USD @ 1.0852 | ID: ..."
        if '@' in line and ('BUY' in line.upper() or 'SELL' in line.upper()):
            # Extract the main parts before any pipe symbol
            main_part = line.split('|')[0].strip()
            
            # Pattern to match: BUY/SELL <size> <pair> @ <price>
            pattern = r'(BUY|SELL)\s+([0-9.,]+[KMB]?)\s+(\S+)\s+@\s+([0-9.]+)'
            match = re.search(pattern, main_part, re.IGNORECASE)
            
            if match:
                side = match.group(1)
                size = self._parse_size(match.group(2))
                pair = match.group(3)
                price = float(match.group(4))
                
                # Try to extract currency pair
                detected_currency = self._normalize_currency_pair(pair)
                
                if side.upper() == 'SELL':
                    size = -abs(size)
                
                self._add_trade_with_data(price, size)
                return detected_currency
        
        # Try other formats
        # Remove common words
        cleaned = line.replace('Buy', '').replace('Sell', '').replace('Long', '').replace('Short', '')
        cleaned = cleaned.replace('@', '').replace('at', '').strip()
        
        # Try to extract numbers
        numbers = re.findall(r'-?\d+\.?\d*[KMB]?', cleaned, re.IGNORECASE)
        
        if len(numbers) >= 2:
            # Assume first is price, second is size (unless @ or "at" pattern suggests otherwise)
            if '@' in line or ' at ' in line.lower():
                # Format: size @ price
                size = self._parse_size(numbers[0])
                price = float(numbers[1])
            else:
                # Format: price size
                price = float(numbers[0])
                size = self._parse_size(numbers[1])
            
            # Check for sell/short indicators
            if any(word in line.lower() for word in ['sell', 'short']):
                size = -abs(size)
            
            self._add_trade_with_data(price, size)
        
        return detected_currency
    
    def _add_trade_with_data(self, price: float, size: float):
        """Add a trade row with specific data"""
        trade_table = self._get_current_table()
        tab_data = self._get_current_tab_data()
        
        if not trade_table or not tab_data:
            return
            
        row_count = trade_table.rowCount()
        trade_table.insertRow(row_count)
        
        # Row number
        row_item = QTableWidgetItem(str(row_count + 1))
        row_item.setFlags(row_item.flags() & ~Qt.ItemIsEditable)
        row_item.setTextAlignment(Qt.AlignCenter)
        trade_table.setItem(row_count, 0, row_item)
        
        # Price - format based on pair type
        if tab_data.is_jpy_pair:
            price_item = QTableWidgetItem(f"{price:.2f}")
        else:
            price_item = QTableWidgetItem(f"{price:.5f}")
        price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        trade_table.setItem(row_count, 1, price_item)
        
        # Update big figure
        self._update_big_figure(tab_data, price)
        
        # Size
        size_text = self._format_size(size) if abs(size) >= 1000 else str(size)
        size_item = QTableWidgetItem(size_text)
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        trade_table.setItem(row_count, 2, size_item)
        
        # Total
        total = price * size
        total_item = QTableWidgetItem(f"{total:,.2f}")
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_item.setForeground(QColor('#999999'))
        trade_table.setItem(row_count, 3, total_item)
        
        # Add TradeEntry
        tab_data.trades.append(TradeEntry(price, size))


class PasteDataDialog(QDialog):
    """Dialog for pasting trade data in various formats"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste Trade Data")
        self.setModal(True)
        self.resize(400, 300)
        
        # Layout
        layout = QVBoxLayout(self)
        
        # Instructions
        instructions = QLabel("""Paste trade data in any of these formats:
        
Platform JSON: [{"price": 1.0852, "quantity": 2500000, "side": "Buy"}, ...]
Simple JSON: [{"price": 100, "size": 1000}, {"price": 101, "size": -500}]
Platform String: BUY 2.5M EUR/USD @ 1.0852 | ID: BARX-123; SELL 1M EUR/USD @ 1.0865
CSV: 100,1000
      101,-500
Text: Buy 1000 @ 100
      Sell 500 @ 101

Smart Entry:
• Price: Enter pip value (e.g., "24" → "0.6524") or full price
• Size: Default in millions (e.g., "1" = 1M, "1.5" = 1.5M)
• Supports K/M/B suffixes. Sell trades create negative positions.""")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Text input
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Paste your trade data here...")
        layout.addWidget(self.text_edit)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #e8e8e8;
            }
            QLabel {
                color: #e8e8e8;
                padding: 10px;
            }
            QTextEdit {
                background-color: #2b2b2b;
                color: #e8e8e8;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 5px;
            }
        """)
    
    def get_data(self) -> str:
        """Get the pasted data"""
        return self.text_edit.toPlainText()