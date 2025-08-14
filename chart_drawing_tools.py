import pyqtgraph as pg
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QPen, QColor, QFont
from typing import Optional, List, Dict, Tuple
import json
from datetime import datetime
import numpy as np


class DrawingTool:
    """Base class for all drawing tools"""
    
    def __init__(self, chart_widget):
        self.chart_widget = chart_widget
        self.items = []
        self.is_drawing = False
        self.start_point = None
        self.temp_items = []
    
    def start_drawing(self, x, y):
        """Start drawing at given coordinates"""
        self.is_drawing = True
        self.start_point = QPointF(x, y)
        self.clear_temp()
    
    def update_drawing(self, x, y):
        """Update drawing as mouse moves"""
        pass
    
    def finish_drawing(self, x, y):
        """Finish drawing at given coordinates"""
        self.is_drawing = False
        self.clear_temp()
    
    def clear_temp(self):
        """Clear temporary drawing items"""
        for item in self.temp_items:
            self.chart_widget.removeItem(item)
        self.temp_items = []
    
    def remove(self):
        """Remove this drawing from chart"""
        for item in self.items:
            self.chart_widget.removeItem(item)
        self.items = []
    
    def serialize(self) -> Dict:
        """Serialize drawing for saving"""
        return {}
    
    def deserialize(self, data: Dict):
        """Deserialize drawing from saved data"""
        pass


class TrendLine(DrawingTool):
    """Trend line drawing tool"""
    
    def __init__(self, chart_widget, color='#4a90e2', width=2, style=Qt.SolidLine):
        super().__init__(chart_widget)
        self.color = color
        self.width = width
        self.style = style
        self.line_item = None
        self.end_point = None
    
    def update_drawing(self, x, y):
        """Update trend line as mouse moves"""
        if not self.is_drawing or self.start_point is None:
            return
        
        self.clear_temp()
        
        # Create temporary line
        temp_line = pg.PlotDataItem(
            [self.start_point.x(), x],
            [self.start_point.y(), y],
            pen=pg.mkPen(self.color, width=self.width, style=self.style)
        )
        self.chart_widget.addItem(temp_line)
        self.temp_items.append(temp_line)
    
    def finish_drawing(self, x, y):
        """Finish drawing trend line"""
        if not self.is_drawing or self.start_point is None:
            return
        
        self.end_point = QPointF(x, y)
        
        # Create permanent line
        self.line_item = pg.PlotDataItem(
            [self.start_point.x(), self.end_point.x()],
            [self.start_point.y(), self.end_point.y()],
            pen=pg.mkPen(self.color, width=self.width, style=self.style)
        )
        self.chart_widget.addItem(self.line_item)
        self.items.append(self.line_item)
        
        super().finish_drawing(x, y)
    
    def serialize(self) -> Dict:
        """Serialize trend line"""
        if self.start_point and self.end_point:
            return {
                'type': 'trend_line',
                'start': [self.start_point.x(), self.start_point.y()],
                'end': [self.end_point.x(), self.end_point.y()],
                'color': self.color,
                'width': self.width,
                'style': self.style
            }
        return {}
    
    def deserialize(self, data: Dict):
        """Deserialize trend line"""
        if 'start' in data and 'end' in data:
            self.start_point = QPointF(data['start'][0], data['start'][1])
            self.end_point = QPointF(data['end'][0], data['end'][1])
            self.color = data.get('color', self.color)
            self.width = data.get('width', self.width)
            self.style = data.get('style', self.style)
            
            self.line_item = pg.PlotDataItem(
                [self.start_point.x(), self.end_point.x()],
                [self.start_point.y(), self.end_point.y()],
                pen=pg.mkPen(self.color, width=self.width, style=self.style)
            )
            self.chart_widget.addItem(self.line_item)
            self.items.append(self.line_item)


class HorizontalLine(DrawingTool):
    """Horizontal line (support/resistance) drawing tool"""
    
    def __init__(self, chart_widget, y_value, color='#ff9f40', width=2, style=Qt.DashLine, label=None):
        super().__init__(chart_widget)
        self.y_value = y_value
        self.color = color
        self.width = width
        self.style = style
        self.label = label
        self.line_item = None
        self.label_item = None
        
        self.create_line()
    
    def create_line(self):
        """Create the horizontal line"""
        self.line_item = pg.InfiniteLine(
            pos=self.y_value,
            angle=0,
            pen=pg.mkPen(self.color, width=self.width, style=self.style),
            movable=True
        )
        self.chart_widget.addItem(self.line_item)
        self.items.append(self.line_item)
        
        # Add label if provided
        if self.label:
            self.label_item = pg.TextItem(
                text=self.label,
                color=self.color,
                anchor=(0, 0.5)
            )
            self.label_item.setPos(0, self.y_value)
            self.chart_widget.addItem(self.label_item)
            self.items.append(self.label_item)
            
            # Connect line movement to label
            self.line_item.sigPositionChanged.connect(self.update_label_position)
    
    def update_label_position(self):
        """Update label position when line moves"""
        if self.label_item:
            new_y = self.line_item.value()
            self.label_item.setPos(0, new_y)
            self.y_value = new_y
    
    def serialize(self) -> Dict:
        """Serialize horizontal line"""
        return {
            'type': 'horizontal_line',
            'y_value': self.y_value,
            'color': self.color,
            'width': self.width,
            'style': self.style,
            'label': self.label
        }
    
    def deserialize(self, data: Dict):
        """Deserialize horizontal line"""
        self.y_value = data.get('y_value', self.y_value)
        self.color = data.get('color', self.color)
        self.width = data.get('width', self.width)
        self.style = data.get('style', self.style)
        self.label = data.get('label', self.label)
        self.create_line()


class VerticalLine(DrawingTool):
    """Vertical line drawing tool"""
    
    def __init__(self, chart_widget, x_value, color='#4a90e2', width=2, style=Qt.DashLine, label=None):
        super().__init__(chart_widget)
        self.x_value = x_value
        self.color = color
        self.width = width
        self.style = style
        self.label = label
        self.line_item = None
        self.label_item = None
        
        self.create_line()
    
    def create_line(self):
        """Create the vertical line"""
        self.line_item = pg.InfiniteLine(
            pos=self.x_value,
            angle=90,
            pen=pg.mkPen(self.color, width=self.width, style=self.style),
            movable=True
        )
        self.chart_widget.addItem(self.line_item)
        self.items.append(self.line_item)
        
        # Add label if provided
        if self.label:
            self.label_item = pg.TextItem(
                text=self.label,
                color=self.color,
                anchor=(0.5, 1)
            )
            self.label_item.setPos(self.x_value, 0)
            self.chart_widget.addItem(self.label_item)
            self.items.append(self.label_item)
            
            # Connect line movement to label
            self.line_item.sigPositionChanged.connect(self.update_label_position)
    
    def update_label_position(self):
        """Update label position when line moves"""
        if self.label_item:
            new_x = self.line_item.value()
            self.label_item.setPos(new_x, 0)
            self.x_value = new_x
    
    def serialize(self) -> Dict:
        """Serialize vertical line"""
        return {
            'type': 'vertical_line',
            'x_value': self.x_value,
            'color': self.color,
            'width': self.width,
            'style': self.style,
            'label': self.label
        }


class FibonacciRetracement(DrawingTool):
    """Fibonacci retracement drawing tool"""
    
    def __init__(self, chart_widget):
        super().__init__(chart_widget)
        self.levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        self.colors = ['#ff5252', '#ff9800', '#ffeb3b', '#4caf50', '#2196f3', '#9c27b0', '#ff5252']
        self.end_point = None
        self.fib_lines = []
        self.fib_labels = []
    
    def update_drawing(self, x, y):
        """Update Fibonacci levels as mouse moves"""
        if not self.is_drawing or self.start_point is None:
            return
        
        self.clear_temp()
        
        # Calculate price range
        price_range = y - self.start_point.y()
        
        # Draw Fibonacci levels
        for i, level in enumerate(self.levels):
            y_level = self.start_point.y() + (price_range * level)
            
            # Create line
            line = pg.InfiniteLine(
                pos=y_level,
                angle=0,
                pen=pg.mkPen(self.colors[i % len(self.colors)], width=1, style=Qt.DashLine)
            )
            self.chart_widget.addItem(line)
            self.temp_items.append(line)
            
            # Create label
            label = pg.TextItem(
                text=f"{level:.1%}",
                color=self.colors[i % len(self.colors)],
                anchor=(1, 0.5)
            )
            label.setPos(x, y_level)
            self.chart_widget.addItem(label)
            self.temp_items.append(label)
    
    def finish_drawing(self, x, y):
        """Finish drawing Fibonacci retracement"""
        if not self.is_drawing or self.start_point is None:
            return
        
        self.end_point = QPointF(x, y)
        
        # Clear temporary items
        self.clear_temp()
        
        # Calculate price range
        price_range = y - self.start_point.y()
        
        # Create permanent Fibonacci levels
        for i, level in enumerate(self.levels):
            y_level = self.start_point.y() + (price_range * level)
            
            # Create line
            line = pg.InfiniteLine(
                pos=y_level,
                angle=0,
                pen=pg.mkPen(self.colors[i % len(self.colors)], width=1, style=Qt.DashLine),
                movable=False
            )
            self.chart_widget.addItem(line)
            self.fib_lines.append(line)
            self.items.append(line)
            
            # Create label with price
            label_text = f"{level:.1%} ({y_level:.5f})"
            label = pg.TextItem(
                text=label_text,
                color=self.colors[i % len(self.colors)],
                anchor=(1, 0.5)
            )
            label.setPos(x, y_level)
            self.chart_widget.addItem(label)
            self.fib_labels.append(label)
            self.items.append(label)
        
        super().finish_drawing(x, y)
    
    def serialize(self) -> Dict:
        """Serialize Fibonacci retracement"""
        if self.start_point and self.end_point:
            return {
                'type': 'fibonacci',
                'start': [self.start_point.x(), self.start_point.y()],
                'end': [self.end_point.x(), self.end_point.y()],
                'levels': self.levels
            }
        return {}
    
    def deserialize(self, data: Dict):
        """Deserialize Fibonacci retracement"""
        if 'start' in data and 'end' in data:
            self.start_point = QPointF(data['start'][0], data['start'][1])
            self.end_point = QPointF(data['end'][0], data['end'][1])
            self.levels = data.get('levels', self.levels)
            
            # Recreate the Fibonacci levels
            price_range = self.end_point.y() - self.start_point.y()
            
            for i, level in enumerate(self.levels):
                y_level = self.start_point.y() + (price_range * level)
                
                line = pg.InfiniteLine(
                    pos=y_level,
                    angle=0,
                    pen=pg.mkPen(self.colors[i % len(self.colors)], width=1, style=Qt.DashLine),
                    movable=False
                )
                self.chart_widget.addItem(line)
                self.fib_lines.append(line)
                self.items.append(line)
                
                label_text = f"{level:.1%} ({y_level:.5f})"
                label = pg.TextItem(
                    text=label_text,
                    color=self.colors[i % len(self.colors)],
                    anchor=(1, 0.5)
                )
                label.setPos(self.end_point.x(), y_level)
                self.chart_widget.addItem(label)
                self.fib_labels.append(label)
                self.items.append(label)


class Rectangle(DrawingTool):
    """Rectangle drawing tool for marking zones"""
    
    def __init__(self, chart_widget, color='#4a90e2', alpha=0.3):
        super().__init__(chart_widget)
        self.color = color
        self.alpha = alpha
        self.end_point = None
        self.rect_item = None
    
    def update_drawing(self, x, y):
        """Update rectangle as mouse moves"""
        if not self.is_drawing or self.start_point is None:
            return
        
        self.clear_temp()
        
        # Create temporary rectangle
        x1, x2 = min(self.start_point.x(), x), max(self.start_point.x(), x)
        y1, y2 = min(self.start_point.y(), y), max(self.start_point.y(), y)
        
        # Create filled rectangle using PlotCurveItem
        xs = [x1, x2, x2, x1, x1]
        ys = [y1, y1, y2, y2, y1]
        
        color = QColor(self.color)
        color.setAlpha(int(self.alpha * 255))
        
        rect = pg.PlotCurveItem(
            xs, ys,
            pen=pg.mkPen(self.color, width=2),
            fillLevel=0,
            brush=pg.mkBrush(color)
        )
        self.chart_widget.addItem(rect)
        self.temp_items.append(rect)
    
    def finish_drawing(self, x, y):
        """Finish drawing rectangle"""
        if not self.is_drawing or self.start_point is None:
            return
        
        self.end_point = QPointF(x, y)
        
        # Clear temporary items
        self.clear_temp()
        
        # Create permanent rectangle
        x1, x2 = min(self.start_point.x(), x), max(self.start_point.x(), x)
        y1, y2 = min(self.start_point.y(), y), max(self.start_point.y(), y)
        
        xs = [x1, x2, x2, x1, x1]
        ys = [y1, y1, y2, y2, y1]
        
        color = QColor(self.color)
        color.setAlpha(int(self.alpha * 255))
        
        self.rect_item = pg.PlotCurveItem(
            xs, ys,
            pen=pg.mkPen(self.color, width=2),
            fillLevel=0,
            brush=pg.mkBrush(color)
        )
        self.chart_widget.addItem(self.rect_item)
        self.items.append(self.rect_item)
        
        super().finish_drawing(x, y)
    
    def serialize(self) -> Dict:
        """Serialize rectangle"""
        if self.start_point and self.end_point:
            return {
                'type': 'rectangle',
                'start': [self.start_point.x(), self.start_point.y()],
                'end': [self.end_point.x(), self.end_point.y()],
                'color': self.color,
                'alpha': self.alpha
            }
        return {}


class TextAnnotation(DrawingTool):
    """Text annotation tool"""
    
    def __init__(self, chart_widget, text="", color='#ffffff', font_size=12):
        super().__init__(chart_widget)
        self.text = text
        self.color = color
        self.font_size = font_size
        self.position = None
        self.text_item = None
    
    def create_at_position(self, x, y, text):
        """Create text annotation at position"""
        self.position = QPointF(x, y)
        self.text = text
        
        self.text_item = pg.TextItem(
            text=self.text,
            color=self.color,
            anchor=(0.5, 0.5)
        )
        self.text_item.setPos(x, y)
        self.text_item.setFont(QFont('Arial', self.font_size))
        
        self.chart_widget.addItem(self.text_item)
        self.items.append(self.text_item)
    
    def serialize(self) -> Dict:
        """Serialize text annotation"""
        if self.position:
            return {
                'type': 'text',
                'position': [self.position.x(), self.position.y()],
                'text': self.text,
                'color': self.color,
                'font_size': self.font_size
            }
        return {}


class DrawingToolManager:
    """Manages all drawing tools on the chart"""
    
    def __init__(self, chart_widget):
        self.chart_widget = chart_widget
        self.drawings = []
        self.current_tool = None
        self.drawing_in_progress = None
    
    def start_trend_line(self, x, y):
        """Start drawing a trend line"""
        if self.drawing_in_progress:
            self.finish_current_drawing(x, y)
        
        self.drawing_in_progress = TrendLine(self.chart_widget)
        self.drawing_in_progress.start_drawing(x, y)
    
    def add_horizontal_line(self, y, label=None):
        """Add a horizontal line at y position"""
        line = HorizontalLine(self.chart_widget, y, label=label)
        self.drawings.append(line)
        return line
    
    def add_vertical_line(self, x, label=None):
        """Add a vertical line at x position"""
        line = VerticalLine(self.chart_widget, x, label=label)
        self.drawings.append(line)
        return line
    
    def start_fibonacci(self, x, y):
        """Start drawing Fibonacci retracement"""
        if self.drawing_in_progress:
            self.finish_current_drawing(x, y)
        
        self.drawing_in_progress = FibonacciRetracement(self.chart_widget)
        self.drawing_in_progress.start_drawing(x, y)
    
    def start_rectangle(self, x, y):
        """Start drawing a rectangle"""
        if self.drawing_in_progress:
            self.finish_current_drawing(x, y)
        
        self.drawing_in_progress = Rectangle(self.chart_widget)
        self.drawing_in_progress.start_drawing(x, y)
    
    def add_text(self, x, y, text):
        """Add text annotation"""
        annotation = TextAnnotation(self.chart_widget)
        annotation.create_at_position(x, y, text)
        self.drawings.append(annotation)
        return annotation
    
    def update_drawing(self, x, y):
        """Update current drawing in progress"""
        if self.drawing_in_progress:
            self.drawing_in_progress.update_drawing(x, y)
    
    def finish_current_drawing(self, x, y):
        """Finish the current drawing"""
        if self.drawing_in_progress:
            self.drawing_in_progress.finish_drawing(x, y)
            self.drawings.append(self.drawing_in_progress)
            self.drawing_in_progress = None
    
    def clear_all(self):
        """Clear all drawings"""
        for drawing in self.drawings:
            drawing.remove()
        self.drawings = []
        
        if self.drawing_in_progress:
            self.drawing_in_progress.clear_temp()
            self.drawing_in_progress = None
    
    def remove_drawing(self, drawing):
        """Remove a specific drawing"""
        if drawing in self.drawings:
            drawing.remove()
            self.drawings.remove(drawing)
    
    def save_drawings(self, filename):
        """Save all drawings to file"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'drawings': [d.serialize() for d in self.drawings if d.serialize()]
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_drawings(self, filename):
        """Load drawings from file"""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            self.clear_all()
            
            for drawing_data in data.get('drawings', []):
                drawing_type = drawing_data.get('type')
                
                if drawing_type == 'trend_line':
                    drawing = TrendLine(self.chart_widget)
                elif drawing_type == 'horizontal_line':
                    drawing = HorizontalLine(self.chart_widget, 0)
                elif drawing_type == 'fibonacci':
                    drawing = FibonacciRetracement(self.chart_widget)
                elif drawing_type == 'rectangle':
                    drawing = Rectangle(self.chart_widget)
                elif drawing_type == 'text':
                    drawing = TextAnnotation(self.chart_widget)
                else:
                    continue
                
                drawing.deserialize(drawing_data)
                self.drawings.append(drawing)
                
        except Exception as e:
            print(f"Error loading drawings: {e}")
    
    def restore_items(self):
        """Restore drawing items after chart update"""
        # This would be called after chart data is reloaded
        # to ensure drawings remain visible
        pass