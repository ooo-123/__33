from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QButtonGroup, QWidget, QSplitter, QToolBar,
                            QAction, QMessageBox, QComboBox, QSpinBox, QCheckBox,
                            QProgressBar)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QPointF
from PyQt5.QtGui import QFont, QIcon, QPen
import pyqtgraph as pg
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import multiprocessing as mp
from queue import Empty
import logging
from typing import Optional, Dict, List, Tuple
from pathlib import Path

from chart_cache_manager import ChartCacheManager
from data_fetcher_process import start_data_fetcher_process
from chart_drawing_tools import DrawingToolManager, TrendLine, HorizontalLine, FibonacciRetracement

logger = logging.getLogger(__name__)


class DataFetcherThread(QThread):
    """Thread to manage the data fetcher subprocess"""
    data_received = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.request_queue = mp.Queue()
        self.response_queue = mp.Queue()
        self.process = None
        self.running = False
    
    def start_process(self):
        """Start the data fetcher subprocess"""
        if self.process is None or not self.process.is_alive():
            self.process = mp.Process(
                target=start_data_fetcher_process, 
                args=(self.request_queue, self.response_queue)
            )
            self.process.start()
            self.running = True
    
    def stop_process(self):
        """Stop the data fetcher subprocess"""
        if self.process and self.process.is_alive():
            self.request_queue.put({'command': 'stop'})
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.terminate()
            self.process = None
        self.running = False
    
    def fetch_data(self, ticker: str, interval: str, start_date: datetime, end_date: datetime):
        """Request data fetch"""
        if not self.running:
            self.start_process()
        
        request = {
            'command': 'fetch',
            'ticker': ticker,
            'interval': interval,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }
        self.request_queue.put(request)
    
    def run(self):
        """Thread main loop to check for responses"""
        self.start_process()
        
        while self.running:
            try:
                response = self.response_queue.get(timeout=0.1)
                if response:
                    if response.get('success'):
                        self.data_received.emit(response)
                    else:
                        self.error_occurred.emit(response.get('error', 'Unknown error'))
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Thread error: {e}")
                self.error_occurred.emit(str(e))
    
    def __del__(self):
        self.stop_process()


class ChartAnalysisWidget(QDialog):
    """Advanced chart analysis widget with drawing tools"""
    
    def __init__(self, parent=None, currency_pair: str = "EURUSD"):
        super().__init__(parent)
        self.currency_pair = currency_pair
        self.current_interval = "1D"
        self.chart_data = None
        self.cache_manager = ChartCacheManager()
        
        # Data fetcher thread
        self.data_fetcher = DataFetcherThread()
        self.data_fetcher.data_received.connect(self.on_data_received)
        self.data_fetcher.error_occurred.connect(self.on_error)
        self.data_fetcher.start()
        
        # Drawing tools
        self.drawing_manager = None
        self.current_drawing_tool = None
        
        # Support/Resistance lines storage
        self.support_resistance_lines = []
        self.show_support_resistance = True
        
        # Market bias indicator
        self.market_bias = None
        self.market_bias_label = None
        self.market_bias_data = None
        self.show_market_bias = False
        self.market_bias_items = []
        
        # SuperTrend indicator
        self.supertrend_data = None
        self.show_supertrend = False
        self.supertrend_items = []
        
        self.setup_ui()
        
        # Defer initial data loading slightly to let window render
        QTimer.singleShot(100, self.load_initial_data)
    
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle(f"Chart Analysis - {self.currency_pair}")
        self.setGeometry(100, 100, 1200, 800)
        
        # Main layout
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Toolbar
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)
        
        # Control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Chart widget with candlesticks
        self.setup_chart()
        layout.addWidget(self.chart_widget)
        
        # Add progress bar for loading indicator
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #2b2b2b;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #4a90e2;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("QLabel { padding: 5px; background-color: #2b2b2b; }")
        layout.addWidget(self.status_label)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QPushButton {
                background-color: #3a3a3a;
                color: #ffffff;
                border: 1px solid #555;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
            QPushButton:checked {
                background-color: #4a90e2;
                border: 2px solid #6ab0ff;
            }
            QLabel {
                color: #ffffff;
            }
            QComboBox, QSpinBox {
                background-color: #3a3a3a;
                color: #ffffff;
                border: 1px solid #555;
                padding: 3px;
            }
            QToolBar {
                background-color: #2b2b2b;
                border: none;
                spacing: 5px;
            }
        """)
    
    def create_toolbar(self) -> QToolBar:
        """Create toolbar with drawing tools"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        
        # Drawing tools
        tools = [
            ("Select", "select", self.set_select_mode),
            ("Trend Line", "line", lambda: self.set_drawing_tool("trend_line")),
            ("Horizontal Line", "hline", lambda: self.set_drawing_tool("horizontal_line")),
            ("Vertical Line", "vline", lambda: self.set_drawing_tool("vertical_line")),
            ("Rectangle", "rect", lambda: self.set_drawing_tool("rectangle")),
            ("Fibonacci", "fib", lambda: self.set_drawing_tool("fibonacci")),
            ("Text", "text", lambda: self.set_drawing_tool("text")),
        ]
        
        self.tool_buttons = {}
        for name, key, callback in tools:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.clicked.connect(callback)
            self.tool_buttons[key] = btn
            toolbar.addWidget(btn)
        
        toolbar.addSeparator()
        
        # Chart tools
        chart_tools = [
            ("Clear Drawings", self.clear_drawings),
            ("Reset Zoom", self.reset_zoom),
            ("Export Chart", self.export_chart),
        ]
        
        # Add indicator toggle checkboxes
        checkbox_style = """
            QCheckBox {
                color: #ffffff;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #4a90e2;
                border: 1px solid #6ab0ff;
            }
        """
        
        # S/R toggle
        self.sr_checkbox = QCheckBox("S/R")
        self.sr_checkbox.setChecked(True)
        self.sr_checkbox.stateChanged.connect(self.toggle_support_resistance)
        self.sr_checkbox.setStyleSheet(checkbox_style)
        toolbar.addWidget(self.sr_checkbox)
        
        # Market Bias toggle
        self.mb_checkbox = QCheckBox("Market Bias")
        self.mb_checkbox.setChecked(False)
        self.mb_checkbox.stateChanged.connect(self.toggle_market_bias)
        self.mb_checkbox.setStyleSheet(checkbox_style)
        toolbar.addWidget(self.mb_checkbox)
        
        # SuperTrend toggle
        self.st_checkbox = QCheckBox("SuperTrend")
        self.st_checkbox.setChecked(False)
        self.st_checkbox.stateChanged.connect(self.toggle_supertrend)
        self.st_checkbox.setStyleSheet(checkbox_style)
        toolbar.addWidget(self.st_checkbox)
        
        for name, callback in chart_tools:
            btn = QPushButton(name)
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)
        
        return toolbar
    
    def create_control_panel(self) -> QWidget:
        """Create control panel with interval selection"""
        panel = QWidget()
        layout = QHBoxLayout()
        panel.setLayout(layout)
        
        # Interval selection
        layout.addWidget(QLabel("Interval:"))
        
        self.interval_buttons = {}
        intervals = [
            ("1 Min", "1M"),
            ("15 Min", "15M"),
            ("1 Day", "1D")
        ]
        
        # Use QButtonGroup to ensure only one interval is selected
        self.interval_group = QButtonGroup()
        self.interval_group.setExclusive(True)  # Only one button can be checked at a time
        
        for label, interval in intervals:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=interval: self.change_interval(i) if checked else None)
            self.interval_group.addButton(btn)
            self.interval_buttons[interval] = btn
            layout.addWidget(btn)
        
        # Set default interval
        self.interval_buttons["1D"].setChecked(True)
        
        layout.addStretch()
        
        # Data range selector
        layout.addWidget(QLabel("Bars:"))
        self.bars_spinbox = QSpinBox()
        self.bars_spinbox.setRange(50, 5000)
        self.bars_spinbox.setValue(500)
        self.bars_spinbox.setSingleStep(50)
        self.bars_spinbox.valueChanged.connect(self.on_bars_changed)
        layout.addWidget(self.bars_spinbox)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_data)
        layout.addWidget(refresh_btn)
        
        # Market Bias indicator display
        layout.addWidget(QLabel("Market Bias:"))
        self.market_bias_label = QLabel("Calculating...")
        self.market_bias_label.setStyleSheet("""
            QLabel {
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.market_bias_label)
        
        return panel
    
    def setup_chart(self):
        """Setup the chart widget"""
        self.chart_widget = pg.PlotWidget()
        
        # Configure chart
        self.chart_widget.setLabel('left', 'Price')
        self.chart_widget.setLabel('bottom', 'Time')
        self.chart_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Dark theme
        self.chart_widget.setBackground('#1e1e1e')
        self.chart_widget.getAxis('left').setPen(pg.mkPen('#666666', width=1))
        self.chart_widget.getAxis('bottom').setPen(pg.mkPen('#666666', width=1))
        
        # Create plot items for OHLC data
        self.candlestick_item = pg.GraphicsObject()
        self.chart_widget.addItem(self.candlestick_item)
        
        # Volume subplot (optional)
        # self.volume_plot = self.chart_widget.plot(pen='w')
        
        # Crosshair
        self.setup_crosshair()
        
        # Initialize drawing manager
        self.drawing_manager = DrawingToolManager(self.chart_widget)
        
        # Connect mouse events for drawing
        self.chart_widget.scene().sigMouseClicked.connect(self.on_chart_click)
        self.chart_widget.scene().sigMouseMoved.connect(self.on_chart_mouse_move)
    
    def setup_crosshair(self):
        """Setup crosshair cursor"""
        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#888888', width=0.5, style=Qt.DashLine))
        self.crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('#888888', width=0.5, style=Qt.DashLine))
        self.chart_widget.addItem(self.crosshair_v, ignoreBounds=True)
        self.chart_widget.addItem(self.crosshair_h, ignoreBounds=True)
        
        # Price label
        self.price_label = pg.TextItem(anchor=(0, 1))
        self.chart_widget.addItem(self.price_label)
        
        # Hide initially
        self.crosshair_v.setVisible(False)
        self.crosshair_h.setVisible(False)
        self.price_label.setVisible(False)
    
    def plot_candlesticks(self, df: pd.DataFrame):
        """Plot candlestick/OHLC data"""
        if df is None or df.empty:
            return
        
        # Save current view range if exists
        try:
            current_range = self.chart_widget.plotItem.viewRange()
            has_view = True
        except:
            has_view = False
        
        # Clear existing data
        self.chart_widget.clear()
        
        # Re-add crosshair
        self.chart_widget.addItem(self.crosshair_v, ignoreBounds=True)
        self.chart_widget.addItem(self.crosshair_h, ignoreBounds=True)
        self.chart_widget.addItem(self.price_label)
        
        # Prepare data
        x = np.arange(len(df))
        
        # Create candlestick data
        candle_data = []
        for i, (idx, row) in enumerate(df.iterrows()):
            is_bullish = row['close'] >= row['open']
            color = '#4CAF50' if is_bullish else '#F44336'
            
            # High-Low line
            candle_data.append({
                'x': [i, i],
                'y': [row['low'], row['high']],
                'pen': pg.mkPen(color, width=1)
            })
            
            # Open-Close body
            body_height = abs(row['close'] - row['open'])
            body_y = min(row['open'], row['close'])
            
            candle_data.append({
                'x': [i - 0.3, i + 0.3, i + 0.3, i - 0.3, i - 0.3],
                'y': [body_y, body_y, body_y + body_height, body_y + body_height, body_y],
                'pen': pg.mkPen(color, width=1),
                'brush': pg.mkBrush(color) if is_bullish else None
            })
        
        # Plot candles
        for candle in candle_data:
            self.chart_widget.plot(candle['x'], candle['y'], 
                                  pen=candle['pen'], 
                                  brush=candle.get('brush'))
        
        # Set x-axis labels (time)
        axis = self.chart_widget.getAxis('bottom')
        
        # Create time labels with DD/MM format
        time_labels = []
        step = max(1, len(df) // 10)  # Show ~10 labels
        for i in range(0, len(df), step):
            # Use DD/MM format instead of MM/DD
            if self.current_interval in ['1M', '15M']:
                time_str = df.index[i].strftime('%d/%m %H:%M')  # DD/MM HH:MM for intraday
            else:  # 1D
                # For daily, include year if spanning multiple years
                if len(df) > 365 or (df.index[-1].year != df.index[0].year):
                    time_str = df.index[i].strftime('%d/%m/%y')  # DD/MM/YY for daily with year
                else:
                    time_str = df.index[i].strftime('%d/%m')  # DD/MM for daily within same year
            time_labels.append((i, time_str))
        
        axis.setTicks([time_labels])
        
        # Store data for drawing tools
        self.chart_data = df
        
        # Store trades if provided (for future trade plotting)
        self.trades_data = getattr(self, 'trades_data', [])
        
        # Restore drawing tools
        if self.drawing_manager:
            self.drawing_manager.restore_items()
        
        # Auto-detect support and resistance levels
        self.detect_support_resistance(df)
        
        # Calculate and display market bias
        self.calculate_market_bias(df)
        
        # Calculate SuperTrend
        self.calculate_supertrend(df)
        
        # Plot indicators if enabled (after candlesticks to ensure proper layering)
        if self.show_market_bias and self.market_bias_data is not None:
            self.plot_market_bias()
        if self.show_supertrend and self.supertrend_data is not None:
            self.plot_supertrend()
        
        # Plot trades if available
        if self.trades_data:
            self.plot_trades()
    
    def change_interval(self, interval: str):
        """Change chart interval"""
        # QButtonGroup handles the exclusive checking automatically
        self.current_interval = interval
        self.update_status(f"Loading {interval} data...")
        self.load_data()
    
    def load_initial_data(self):
        """Load initial data from cache or fetch if needed"""
        # Show loading status
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.update_status("Loading chart data...")
        
        # Try to load from cache first
        cached_data = self.cache_manager.get_latest_data(
            self.currency_pair, 
            self.current_interval, 
            self.bars_spinbox.value()
        )
        
        if cached_data is not None:
            self.plot_candlesticks(cached_data)
            self.update_status(f"Loaded {len(cached_data)} cached bars")
            self.progress_bar.setVisible(False)
        else:
            # Fetch new data
            self.load_data()
    
    def load_data(self):
        """Load data for current settings with optimized windows for Bloomberg"""
        num_bars = self.bars_spinbox.value()
        
        # Calculate date range with optimal windows for Bloomberg
        end_date = datetime.now()
        
        # Optimize data windows for Bloomberg efficiency
        if self.current_interval == "1M":
            # For 1-minute data, limit to 2 days max (2880 bars)
            # Bloomberg has limits on intraday data
            max_bars = min(num_bars, 2880)  # 2 days of 1-minute data
            start_date = end_date - timedelta(minutes=max_bars)
            logger.info(f"Loading {max_bars} bars of 1M data (max 2 days)")
        elif self.current_interval == "15M":
            # For 15-minute data, up to 30 days (2880 bars)
            max_bars = min(num_bars, 2880)  # 30 days of 15-minute data
            start_date = end_date - timedelta(minutes=max_bars * 15)
            logger.info(f"Loading {max_bars} bars of 15M data (max 30 days)")
        else:  # 1D
            # For daily data, can fetch years of history efficiently
            start_date = end_date - timedelta(days=num_bars)
            logger.info(f"Loading {num_bars} bars of 1D data")
        
        # Request data from fetcher
        self.data_fetcher.fetch_data(
            self.currency_pair,
            self.current_interval,
            start_date,
            end_date
        )
    
    def on_data_received(self, response: dict):
        """Handle received data"""
        try:
            # Reconstruct DataFrame from response
            df = pd.DataFrame(response['data'])
            df.index = pd.to_datetime(response['index'])
            df.sort_index(inplace=True)
            
            # Plot data
            self.plot_candlesticks(df)
            
            # Update cache
            self.cache_manager.append_data(
                response['ticker'],
                response['interval'],
                df
            )
            
            self.update_status(f"Loaded {len(df)} bars")
            
            # Hide progress bar
            self.progress_bar.setVisible(False)
            
        except Exception as e:
            logger.error(f"Error processing data: {e}")
            self.update_status(f"Error: {e}")
            self.progress_bar.setVisible(False)
    
    def on_error(self, error_msg: str):
        """Handle data fetch errors"""
        self.update_status(f"Error: {error_msg}")
        QMessageBox.warning(self, "Data Error", error_msg)
    
    def on_bars_changed(self, value: int):
        """Handle change in number of bars"""
        # Debounce with timer
        if hasattr(self, 'reload_timer'):
            self.reload_timer.stop()
        
        self.reload_timer = QTimer()
        self.reload_timer.timeout.connect(self.load_data)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.start(500)  # 500ms delay
    
    def refresh_data(self):
        """Refresh chart data"""
        self.load_data()
    
    def update_status(self, message: str):
        """Update status bar"""
        self.status_label.setText(message)
    
    def set_select_mode(self):
        """Set chart to selection mode"""
        self.current_drawing_tool = None
        for key, btn in self.tool_buttons.items():
            btn.setChecked(key == "select")
        self.chart_widget.setMouseEnabled(x=True, y=True)
    
    def set_drawing_tool(self, tool: str):
        """Set current drawing tool"""
        self.current_drawing_tool = tool
        for key, btn in self.tool_buttons.items():
            btn.setChecked(False)
        self.chart_widget.setMouseEnabled(x=False, y=False)
        self.update_status(f"Drawing tool: {tool}")
    
    def on_chart_click(self, event):
        """Handle chart click for drawing"""
        if self.current_drawing_tool and self.drawing_manager:
            pos = event.scenePos()
            view_pos = self.chart_widget.plotItem.vb.mapSceneToView(pos)
            
            if self.current_drawing_tool == "trend_line":
                if not self.drawing_manager.drawing_in_progress:
                    self.drawing_manager.start_trend_line(view_pos.x(), view_pos.y())
                else:
                    self.drawing_manager.finish_current_drawing(view_pos.x(), view_pos.y())
            elif self.current_drawing_tool == "horizontal_line":
                self.drawing_manager.add_horizontal_line(view_pos.y())
            elif self.current_drawing_tool == "vertical_line":
                self.drawing_manager.add_vertical_line(view_pos.x())
            elif self.current_drawing_tool == "rectangle":
                if not self.drawing_manager.drawing_in_progress:
                    self.drawing_manager.start_rectangle(view_pos.x(), view_pos.y())
                else:
                    self.drawing_manager.finish_current_drawing(view_pos.x(), view_pos.y())
            elif self.current_drawing_tool == "fibonacci":
                if not self.drawing_manager.drawing_in_progress:
                    self.drawing_manager.start_fibonacci(view_pos.x(), view_pos.y())
                else:
                    self.drawing_manager.finish_current_drawing(view_pos.x(), view_pos.y())
            elif self.current_drawing_tool == "text":
                from PyQt5.QtWidgets import QInputDialog
                text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
                if ok and text:
                    self.drawing_manager.add_text(view_pos.x(), view_pos.y(), text)
    
    def on_chart_mouse_move(self, pos):
        """Handle mouse move for crosshair and drawing"""
        if self.chart_widget.plotItem.vb.sceneBoundingRect().contains(pos):
            mouse_point = self.chart_widget.plotItem.vb.mapSceneToView(pos)
            
            # Update crosshair
            self.crosshair_v.setPos(mouse_point.x())
            self.crosshair_h.setPos(mouse_point.y())
            self.crosshair_v.setVisible(True)
            self.crosshair_h.setVisible(True)
            
            # Update price label
            if self.chart_data is not None:
                index = int(mouse_point.x())
                if 0 <= index < len(self.chart_data):
                    row = self.chart_data.iloc[index]
                    text = f"O:{row['open']:.5f} H:{row['high']:.5f} L:{row['low']:.5f} C:{row['close']:.5f}"
                    self.price_label.setText(text)
                    self.price_label.setPos(mouse_point.x(), mouse_point.y())
                    self.price_label.setVisible(True)
            
            # Update drawing if in progress
            if self.drawing_manager:
                self.drawing_manager.update_drawing(mouse_point.x(), mouse_point.y())
    
    def clear_drawings(self):
        """Clear all drawings"""
        if self.drawing_manager:
            self.drawing_manager.clear_all()
        self.update_status("Drawings cleared")
    
    def reset_zoom(self):
        """Reset chart zoom"""
        self.chart_widget.plotItem.autoRange()
    
    def detect_support_resistance(self, df: pd.DataFrame):
        """Automatically detect and draw major support/resistance levels"""
        if df is None or df.empty or len(df) < 20:
            return
        
        # Clear existing S/R lines
        for line in self.support_resistance_lines:
            if line in self.drawing_manager.drawings:
                self.drawing_manager.drawings.remove(line)
            line.remove()
        self.support_resistance_lines = []
        
        try:
            # Use high/low for detection
            highs = df['high'].values
            lows = df['low'].values
            
            # Find local maxima and minima
            from scipy.signal import argrelextrema
            import numpy as np
            
            # Window size for local extrema
            window = min(10, len(df) // 5)
            
            # Find local maxima (resistance)
            local_max_indices = argrelextrema(highs, np.greater, order=window)[0]
            # Find local minima (support)  
            local_min_indices = argrelextrema(lows, np.less, order=window)[0]
            
            # Get resistance levels from local maxima
            resistance_levels = highs[local_max_indices]
            # Get support levels from local minima
            support_levels = lows[local_min_indices]
            
            # Cluster nearby levels
            def cluster_levels(levels, threshold=0.001):
                """Cluster nearby price levels"""
                if len(levels) == 0:
                    return []
                
                sorted_levels = sorted(levels)
                clusters = []
                current_cluster = [sorted_levels[0]]
                
                for level in sorted_levels[1:]:
                    if abs(level - current_cluster[-1]) / current_cluster[-1] < threshold:
                        current_cluster.append(level)
                    else:
                        clusters.append(np.mean(current_cluster))
                        current_cluster = [level]
                
                if current_cluster:
                    clusters.append(np.mean(current_cluster))
                
                return clusters
            
            # Cluster and get top levels
            resistance_clustered = cluster_levels(resistance_levels)
            support_clustered = cluster_levels(support_levels)
            
            # Sort by importance (frequency of touches)
            def count_touches(level, prices, threshold=0.001):
                """Count how many times price touched this level"""
                touches = 0
                for price in prices:
                    if abs(price - level) / level < threshold:
                        touches += 1
                return touches
            
            # Score each level
            resistance_scores = [(level, count_touches(level, highs)) for level in resistance_clustered]
            support_scores = [(level, count_touches(level, lows)) for level in support_clustered]
            
            # Sort by score and take top 3
            resistance_scores.sort(key=lambda x: x[1], reverse=True)
            support_scores.sort(key=lambda x: x[1], reverse=True)
            
            # Draw top resistance levels
            for i, (level, score) in enumerate(resistance_scores[:3]):
                if score > 1:  # Only draw if touched more than once
                    line = self.drawing_manager.add_horizontal_line(
                        level, 
                        label=f"R{i+1}: {level:.5f}"
                    )
                    if line:
                        # Make resistance lines red
                        line.color = '#ff4444'
                        line.line_item.setPen(pg.mkPen('#ff4444', width=2, style=Qt.DashLine))
                        self.support_resistance_lines.append(line)
                        # Set visibility based on checkbox
                        line.line_item.setVisible(self.show_support_resistance)
                        if line.label_item:
                            line.label_item.setVisible(self.show_support_resistance)
            
            # Draw top support levels
            for i, (level, score) in enumerate(support_scores[:3]):
                if score > 1:  # Only draw if touched more than once
                    line = self.drawing_manager.add_horizontal_line(
                        level,
                        label=f"S{i+1}: {level:.5f}"
                    )
                    if line:
                        # Make support lines green
                        line.color = '#44ff44'
                        line.line_item.setPen(pg.mkPen('#44ff44', width=2, style=Qt.DashLine))
                        self.support_resistance_lines.append(line)
                        # Set visibility based on checkbox
                        line.line_item.setVisible(self.show_support_resistance)
                        if line.label_item:
                            line.label_item.setVisible(self.show_support_resistance)
            
            self.update_status("Auto-detected support/resistance levels")
            
        except ImportError:
            logger.warning("scipy not available for support/resistance detection")
        except Exception as e:
            logger.error(f"Error detecting support/resistance: {e}")
    
    def export_chart(self):
        """Export chart as image"""
        from PyQt5.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Chart", 
            f"{self.currency_pair}_{self.current_interval}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
            "PNG Files (*.png);;All Files (*)"
        )
        
        if filename:
            exporter = pg.exporters.ImageExporter(self.chart_widget.plotItem)
            exporter.export(filename)
            self.update_status(f"Chart exported to {filename}")
    
    def toggle_support_resistance(self, state):
        """Toggle visibility of support/resistance lines"""
        self.show_support_resistance = (state == Qt.Checked)
        for line in self.support_resistance_lines:
            if line.line_item:
                line.line_item.setVisible(self.show_support_resistance)
            if line.label_item:
                line.label_item.setVisible(self.show_support_resistance)
    
    def toggle_market_bias(self, state):
        """Toggle visibility of market bias overlay"""
        self.show_market_bias = (state == Qt.Checked)
        if self.show_market_bias and self.market_bias_data is not None:
            self.plot_market_bias()
        else:
            self.clear_market_bias_plot()
        
        # Maintain current zoom level
        if hasattr(self, '_saved_view_range'):
            self.chart_widget.plotItem.setRange(
                xRange=self._saved_view_range[0],
                yRange=self._saved_view_range[1],
                padding=0
            )
    
    def toggle_supertrend(self, state):
        """Toggle visibility of SuperTrend indicator"""
        self.show_supertrend = (state == Qt.Checked)
        if self.show_supertrend and self.supertrend_data is not None:
            self.plot_supertrend()
        else:
            self.clear_supertrend_plot()
        
        # Maintain current zoom level
        if hasattr(self, '_saved_view_range'):
            self.chart_widget.plotItem.setRange(
                xRange=self._saved_view_range[0],
                yRange=self._saved_view_range[1],
                padding=0
            )
    
    def calculate_market_bias(self, df: pd.DataFrame):
        """Calculate market bias using Heikin-Ashi style indicator"""
        # First try to get from centralized manager for the label display
        centralized_bias = None
        centralized_strength = None
        try:
            from market_bias_manager import get_market_bias_manager
            bias_manager = get_market_bias_manager()
            bias_data = bias_manager.get_bias(self.currency_pair)
            
            if bias_data and bias_data.get('bias') != 0:
                centralized_bias = bias_data.get('bias')
                centralized_strength = bias_data.get('strength', 0)
        except:
            pass  # Will calculate locally
        
        # Original local calculation
        if df is None or df.empty or len(df) < 300:
            self.market_bias_label.setText("Insufficient data")
            self.market_bias_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #3a3a3a;
                    color: #888;
                }
            """)
            return
        
        try:
            # Fast EMA calculation
            def fast_ema(values, period):
                alpha = 2.0 / (period + 1)
                ema = np.empty_like(values)
                ema[0] = values[0]
                for i in range(1, len(values)):
                    ema[i] = alpha * values[i] + (1 - alpha) * ema[i-1]
                return ema
            
            # Market Bias calculation
            ha_len = min(300, len(df) // 2)  # Adjust for shorter data
            ha_len2 = min(30, len(df) // 10)
            
            open_vals = df['open'].values.astype(np.float64)
            high_vals = df['high'].values.astype(np.float64)
            low_vals = df['low'].values.astype(np.float64)
            close_vals = df['close'].values.astype(np.float64)
            
            # Initial Data Smoothing
            ha_ema_open = fast_ema(open_vals, ha_len)
            ha_ema_close = fast_ema(close_vals, ha_len)
            ha_ema_high = fast_ema(high_vals, ha_len)
            ha_ema_low = fast_ema(low_vals, ha_len)
            
            # Heikin-Ashi Style Candle Construction
            ha_close_val = (ha_ema_open + ha_ema_high + ha_ema_low + ha_ema_close) / 4
            
            n = len(df)
            ha_open_val = np.empty(n, dtype=np.float64)
            ha_open_val[0] = (ha_ema_open[0] + ha_ema_close[0]) / 2
            
            for i in range(1, n):
                ha_open_val[i] = (ha_open_val[i-1] + ha_close_val[i-1]) / 2
            
            # Calculate Heikin-Ashi high and low
            ha_high_val = np.maximum(ha_ema_high, np.maximum(ha_open_val, ha_close_val))
            ha_low_val = np.minimum(ha_ema_low, np.minimum(ha_open_val, ha_close_val))
            
            # Secondary Smoothing
            mb_o2 = fast_ema(ha_open_val, ha_len2)
            mb_c2 = fast_ema(ha_close_val, ha_len2)
            mb_h2 = fast_ema(ha_high_val, ha_len2)
            mb_l2 = fast_ema(ha_low_val, ha_len2)
            
            # Store market bias data for plotting
            self.market_bias_data = {
                'mb_bias': np.where(mb_c2 > mb_o2, 1, -1),
                'mb_o2': mb_o2,
                'mb_c2': mb_c2,
                'mb_h2': mb_h2,
                'mb_l2': mb_l2
            }
            
            # Use centralized bias if available, otherwise use local calculation
            if centralized_bias is not None and centralized_strength is not None:
                latest_bias = centralized_bias
                bias_diff = centralized_strength
            else:
                # Get latest bias from local calculation
                latest_bias = self.market_bias_data['mb_bias'][-1]
                # Calculate trend strength
                bias_diff = abs(mb_c2[-1] - mb_o2[-1]) / mb_o2[-1] * 100
            
            # Update market bias display
            if latest_bias == 1:
                self.market_bias = "BULLISH"
                self.market_bias_label.setText(f"BULLISH ({bias_diff:.2f}%)")
                self.market_bias_label.setStyleSheet("""
                    QLabel {
                        padding: 5px 10px;
                        border-radius: 3px;
                        font-weight: bold;
                        background-color: #1b5e20;
                        color: #4caf50;
                        border: 1px solid #4caf50;
                    }
                """)
            else:
                self.market_bias = "BEARISH"
                self.market_bias_label.setText(f"BEARISH ({bias_diff:.2f}%)")
                self.market_bias_label.setStyleSheet("""
                    QLabel {
                        padding: 5px 10px;
                        border-radius: 3px;
                        font-weight: bold;
                        background-color: #b71c1c;
                        color: #f44336;
                        border: 1px solid #f44336;
                    }
                """)
            
            # Emit signal to main GUI if parent exists
            if self.parent() and hasattr(self.parent(), 'update_market_bias'):
                self.parent().update_market_bias(self.currency_pair, latest_bias)
            
        except Exception as e:
            logger.error(f"Error calculating market bias: {e}")
            self.market_bias_label.setText("Error")
            self.market_bias_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    font-weight: bold;
                    background-color: #3a3a3a;
                    color: #ff9800;
                }
            """)
    
    def plot_market_bias(self):
        """Plot Market Bias overlay on chart"""
        if self.market_bias_data is None or self.chart_data is None:
            return
        
        # Clear existing market bias items
        self.clear_market_bias_plot()
        
        # Save current view range before adding overlays
        view_range = self.chart_widget.plotItem.viewRange()
        self._saved_view_range = view_range
        
        x_pos = np.arange(len(self.chart_data))
        mb_bias = self.market_bias_data['mb_bias']
        mb_o2 = self.market_bias_data['mb_o2']
        mb_c2 = self.market_bias_data['mb_c2']
        mb_h2 = self.market_bias_data['mb_h2']
        mb_l2 = self.market_bias_data['mb_l2']
        
        # Ensure arrays are same length as chart data
        min_len = min(len(x_pos), len(mb_bias))
        x_pos = x_pos[-min_len:]
        mb_bias = mb_bias[-min_len:]
        mb_o2 = mb_o2[-min_len:]
        mb_c2 = mb_c2[-min_len:]
        mb_h2 = mb_h2[-min_len:]
        mb_l2 = mb_l2[-min_len:]
        
        # Plot market bias as background rectangles
        for i in range(len(x_pos)):
            color = '#4CAF5030' if mb_bias[i] == 1 else '#F4433630'  # Very transparent
            
            # Plot high-low wick as thick transparent line
            wick = pg.PlotDataItem(
                [x_pos[i], x_pos[i]],
                [mb_l2[i], mb_h2[i]],
                pen=pg.mkPen(color[:-2] + '40', width=10)  # Very transparent thick line
            )
            wick.setZValue(-10)  # Put behind candlesticks
            self.chart_widget.addItem(wick, ignoreBounds=True)
            self.market_bias_items.append(wick)
            
            # Plot open-close body
            body_bottom = min(mb_o2[i], mb_c2[i])
            body_top = max(mb_o2[i], mb_c2[i])
            body_height = body_top - body_bottom
            
            # Ensure minimum body height
            if body_height < (self.chart_data['close'].mean() * 0.0001):
                body_height = self.chart_data['close'].mean() * 0.0001
            
            # Create rectangle for body
            xs = [x_pos[i] - 0.4, x_pos[i] + 0.4, x_pos[i] + 0.4, x_pos[i] - 0.4, x_pos[i] - 0.4]
            ys = [body_bottom, body_bottom, body_top, body_top, body_bottom]
            
            body = pg.PlotCurveItem(
                xs, ys,
                pen=pg.mkPen(None),
                fillLevel=0,
                brush=pg.mkBrush(color)
            )
            body.setZValue(-10)  # Put behind candlesticks
            self.chart_widget.addItem(body, ignoreBounds=True)
            self.market_bias_items.append(body)
        
        # Restore the view range to prevent zoom changes
        self.chart_widget.plotItem.setRange(
            xRange=view_range[0],
            yRange=view_range[1],
            padding=0
        )
    
    def clear_market_bias_plot(self):
        """Clear market bias overlay from chart"""
        for item in self.market_bias_items:
            self.chart_widget.removeItem(item)
        self.market_bias_items = []
    
    def calculate_supertrend(self, df: pd.DataFrame):
        """Calculate SuperTrend indicator"""
        if df is None or df.empty or len(df) < 20:
            return
        
        try:
            # SuperTrend parameters
            atr_period = 10
            multiplier = 3.0
            
            # Calculate ATR
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            
            # True Range
            hl = high - low
            hc = np.abs(high - np.roll(close, 1))
            lc = np.abs(low - np.roll(close, 1))
            hc[0] = hl[0]
            lc[0] = hl[0]
            tr = np.maximum(hl, np.maximum(hc, lc))
            
            # ATR using EMA
            alpha = 2.0 / (atr_period + 1)
            atr = np.empty(len(df))
            atr[0] = tr[0]
            for i in range(1, len(df)):
                atr[i] = alpha * tr[i] + (1 - alpha) * atr[i-1]
            
            # Calculate SuperTrend
            src = (high + low) / 2  # HL2
            basic_up = src - multiplier * atr
            basic_down = src + multiplier * atr
            
            up = np.empty(len(df))
            down = np.empty(len(df))
            trend = np.empty(len(df), dtype=int)
            
            up[0] = basic_up[0]
            down[0] = basic_down[0]
            trend[0] = 1
            
            for i in range(1, len(df)):
                # Update bands
                if close[i-1] > up[i-1]:
                    up[i] = max(basic_up[i], up[i-1])
                else:
                    up[i] = basic_up[i]
                
                if close[i-1] < down[i-1]:
                    down[i] = min(basic_down[i], down[i-1])
                else:
                    down[i] = basic_down[i]
                
                # Update trend
                if trend[i-1] == 1:
                    trend[i] = -1 if close[i] <= up[i] else 1
                else:
                    trend[i] = 1 if close[i] >= down[i] else -1
            
            # Store SuperTrend data
            self.supertrend_data = {
                'trend': trend,
                'line': np.where(trend == 1, up, down),
                'up': up,
                'down': down
            }
            
        except Exception as e:
            logger.error(f"Error calculating SuperTrend: {e}")
    
    def plot_supertrend(self):
        """Plot SuperTrend indicator on chart"""
        if self.supertrend_data is None or self.chart_data is None:
            return
        
        # Clear existing SuperTrend items
        self.clear_supertrend_plot()
        
        x_pos = np.arange(len(self.chart_data))
        st_trend = self.supertrend_data['trend']
        st_line = self.supertrend_data['line']
        
        # Ensure arrays are same length
        min_len = min(len(x_pos), len(st_trend))
        x_pos = x_pos[-min_len:]
        st_trend = st_trend[-min_len:]
        st_line = st_line[-min_len:]
        
        # Plot SuperTrend as continuous line with color changes
        i = 0
        while i < len(x_pos) - 1:
            # Find continuous segment with same trend
            j = i + 1
            while j < len(x_pos) and st_trend[j] == st_trend[i]:
                j += 1
            
            # Plot segment
            color = '#4CAF50' if st_trend[i] == 1 else '#F44336'
            line = pg.PlotDataItem(
                x_pos[i:j],
                st_line[i:j],
                pen=pg.mkPen(color, width=2.5, style=Qt.SolidLine)
            )
            self.chart_widget.addItem(line)
            self.supertrend_items.append(line)
            
            # Add transition line if trend changes
            if j < len(x_pos) and st_trend[j] != st_trend[i]:
                transition_color = '#F44336' if st_trend[i] == 1 else '#4CAF50'
                transition = pg.PlotDataItem(
                    [x_pos[j-1], x_pos[j]],
                    [st_line[j-1], st_line[j]],
                    pen=pg.mkPen(transition_color, width=2.5, style=Qt.SolidLine)
                )
                self.chart_widget.addItem(transition)
                self.supertrend_items.append(transition)
            
            i = j
    
    def clear_supertrend_plot(self):
        """Clear SuperTrend indicator from chart"""
        for item in self.supertrend_items:
            self.chart_widget.removeItem(item)
        self.supertrend_items = []
    
    def set_trades(self, trades: List[Dict]):
        """Set trades data to be plotted on the chart
        
        Args:
            trades: List of trade dicts with keys:
                - timestamp: datetime of trade
                - price: execution price
                - side: 'buy' or 'sell'
                - size: trade size
                - pair: currency pair
        """
        self.trades_data = trades
        if self.chart_data is not None:
            self.plot_trades()
    
    def plot_trades(self):
        """Plot trade markers on the chart"""
        if not hasattr(self, 'trades_data') or not self.trades_data or self.chart_data is None:
            return
        
        # Clear existing trade markers
        if hasattr(self, 'trade_markers'):
            for marker in self.trade_markers:
                self.chart_widget.removeItem(marker)
        self.trade_markers = []
        
        # Plot each trade
        for trade in self.trades_data:
            try:
                # Find the closest bar index for this trade
                trade_time = pd.to_datetime(trade['timestamp'])
                
                # Find closest index in chart data
                time_diff = abs(self.chart_data.index - trade_time)
                closest_idx = time_diff.argmin()
                
                # Only plot if trade is within chart range
                if time_diff[closest_idx] < pd.Timedelta(days=1):
                    x_pos = closest_idx
                    y_pos = trade['price']
                    
                    # Create marker based on trade side
                    if trade['side'].lower() == 'buy':
                        # Green upward triangle for buys
                        symbol = 't'
                        color = '#4CAF50'
                        brush = pg.mkBrush('#4CAF50')
                    else:
                        # Red downward triangle for sells
                        symbol = 't1'
                        color = '#F44336'
                        brush = pg.mkBrush('#F44336')
                    
                    # Create scatter plot item for the trade
                    marker = pg.ScatterPlotItem(
                        [x_pos], [y_pos],
                        size=12,
                        symbol=symbol,
                        pen=pg.mkPen(color, width=2),
                        brush=brush
                    )
                    
                    self.chart_widget.addItem(marker)
                    self.trade_markers.append(marker)
                    
                    # Add text label with trade info
                    label_text = f"{trade['side'].upper()}\n{trade.get('size', '')}"
                    label = pg.TextItem(
                        text=label_text,
                        color=color,
                        anchor=(0.5, 1 if trade['side'].lower() == 'sell' else 0),
                        fill=pg.mkBrush('#1e1e1e88')
                    )
                    label.setPos(x_pos, y_pos)
                    self.chart_widget.addItem(label)
                    self.trade_markers.append(label)
                    
            except Exception as e:
                logger.error(f"Error plotting trade: {e}")
    
    def closeEvent(self, event):
        """Clean up on close"""
        if self.data_fetcher:
            self.data_fetcher.stop_process()
            self.data_fetcher.quit()
            self.data_fetcher.wait()
        event.accept()


if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    # Test the widget
    widget = ChartAnalysisWidget(currency_pair="EURUSD")
    widget.show()
    
    sys.exit(app.exec_())