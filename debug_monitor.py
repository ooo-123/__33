import time
import threading
import psutil
import os
from collections import deque
from datetime import datetime

class DebugMonitor:
    """
    Performance monitoring and debug metrics for FX GUI application
    """
    
    def __init__(self, enabled=False, report_interval=10):
        self.enabled = enabled
        self.report_interval = report_interval
        
        # Performance counters
        self.data_updates = deque(maxlen=1000)
        self.gui_updates = deque(maxlen=1000)
        self.chart_updates = deque(maxlen=1000)
        self.error_count = 0
        self.start_time = time.time()
        
        # System monitoring
        self.process = psutil.Process(os.getpid())
        
        # Threading
        self.monitor_thread = None
        self.running = False
        
        # Latency tracking
        self.data_latencies = deque(maxlen=100)
        self.gui_latencies = deque(maxlen=100)
        
        if self.enabled:
            self.start_monitoring()
    
    def start_monitoring(self):
        """Start the debug monitoring thread"""
        if not self.enabled or self.running:
            return
            
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("🔍 Debug mode enabled - Performance monitoring started")
    
    def stop_monitoring(self):
        """Stop the debug monitoring thread"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
    
    def record_data_update(self, latency_ms=None):
        """Record a data update event"""
        if not self.enabled:
            return
        current_time = time.time()
        self.data_updates.append(current_time)
        if latency_ms is not None:
            self.data_latencies.append(latency_ms)
    
    def record_gui_update(self, latency_ms=None):
        """Record a GUI update event"""
        if not self.enabled:
            return
        current_time = time.time()
        self.gui_updates.append(current_time)
        if latency_ms is not None:
            self.gui_latencies.append(latency_ms)
    
    def record_chart_update(self):
        """Record a chart update event"""
        if not self.enabled:
            return
        current_time = time.time()
        self.chart_updates.append(current_time)
    
    def record_error(self):
        """Record an error occurrence"""
        if not self.enabled:
            return
        self.error_count += 1
    
    def _calculate_rate(self, events, window_seconds=10):
        """Calculate events per second over the given window"""
        if not events:
            return 0.0
        
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Count events in the last window_seconds
        recent_events = [t for t in events if t >= cutoff_time]
        return len(recent_events) / window_seconds
    
    def _get_average_latency(self, latencies):
        """Calculate average latency in milliseconds"""
        if not latencies:
            return 0.0
        return sum(latencies) / len(latencies)
    
    def _get_system_metrics(self):
        """Get current system performance metrics"""
        try:
            cpu_percent = self.process.cpu_percent()
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # Get system-wide CPU if process CPU is low
            if cpu_percent < 0.1:
                cpu_percent = psutil.cpu_percent()
                
            return {
                'cpu_percent': cpu_percent,
                'memory_mb': memory_mb,
                'threads': self.process.num_threads()
            }
        except Exception:
            return {
                'cpu_percent': 0.0,
                'memory_mb': 0.0,
                'threads': 0
            }
    
    def _monitor_loop(self):
        """Main monitoring loop that prints debug info every interval"""
        while self.running:
            time.sleep(self.report_interval)
            if not self.running:
                break
            self._print_debug_report()
    
    def _print_debug_report(self):
        """Print comprehensive debug report to terminal"""
        current_time = time.time()
        uptime = current_time - self.start_time
        
        # Calculate rates
        data_rate = self._calculate_rate(self.data_updates)
        gui_rate = self._calculate_rate(self.gui_updates)
        chart_rate = self._calculate_rate(self.chart_updates)
        
        # Get latencies
        avg_data_latency = self._get_average_latency(self.data_latencies)
        avg_gui_latency = self._get_average_latency(self.gui_latencies)
        
        # Get system metrics
        system_metrics = self._get_system_metrics()
        
        # Create report
        print("\n" + "="*80)
        print(f"📊 FX GUI DEBUG REPORT - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)
        
        print(f"⏱️  UPTIME: {uptime/60:.1f} minutes")
        print(f"🔄 PERFORMANCE RATES (per second, last 10s):")
        print(f"   • Data Updates:  {data_rate:6.1f} /sec")
        print(f"   • GUI Updates:   {gui_rate:6.1f} /sec")
        print(f"   • Chart Updates: {chart_rate:6.1f} /sec")
        
        print(f"⚡ LATENCY (milliseconds):")
        print(f"   • Avg Data Latency:  {avg_data_latency:6.2f} ms")
        print(f"   • Avg GUI Latency:   {avg_gui_latency:6.2f} ms")
        
        print(f"🖥️  SYSTEM RESOURCES:")
        print(f"   • CPU Usage:    {system_metrics['cpu_percent']:6.1f} %")
        print(f"   • Memory Usage: {system_metrics['memory_mb']:6.1f} MB")
        print(f"   • Threads:      {system_metrics['threads']:6d}")
        
        print(f"⚠️  ERRORS: {self.error_count} total")
        
        # Performance assessment
        if data_rate > 30 and gui_rate > 15:
            status = "🟢 EXCELLENT"
        elif data_rate > 20 and gui_rate > 10:
            status = "🟡 GOOD"
        elif data_rate > 10 and gui_rate > 5:
            status = "🟠 FAIR"
        else:
            status = "🔴 POOR"
        
        print(f"📈 PERFORMANCE STATUS: {status}")
        print("="*80)
    
    def get_current_metrics(self):
        """Get current metrics as a dictionary"""
        if not self.enabled:
            return {}
        
        current_time = time.time()
        uptime = current_time - self.start_time
        
        return {
            'uptime_minutes': uptime / 60,
            'data_rate': self._calculate_rate(self.data_updates),
            'gui_rate': self._calculate_rate(self.gui_updates),
            'chart_rate': self._calculate_rate(self.chart_updates),
            'avg_data_latency': self._get_average_latency(self.data_latencies),
            'avg_gui_latency': self._get_average_latency(self.gui_latencies),
            'error_count': self.error_count,
            **self._get_system_metrics()
        }

# Global debug monitor instance
debug_monitor = None

def init_debug_monitor(enabled=False, report_interval=10):
    """Initialize the global debug monitor"""
    global debug_monitor
    debug_monitor = DebugMonitor(enabled=enabled, report_interval=report_interval)
    return debug_monitor

def get_debug_monitor():
    """Get the global debug monitor instance"""
    global debug_monitor
    return debug_monitor