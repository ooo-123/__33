# FX GUI Standalone Package

This is a complete standalone package for the FX Trading GUI application with real-time price monitoring, chart analysis, and voice announcements.

## 📦 Package Contents

### Core Python Files
- `gui_graph.py` - Main GUI application
- `fx.py` - FX pricing engine with Bloomberg/WebSocket/Simulation support
- `pricefeed_with_failover.py` - WebSocket price feed with automatic failover
- `debug_monitor.py` - Performance and debug monitoring
- `pip_value_calculator.py` - Pip value calculations
- `trade_calculator.py` - Trade calculator widget

### Chart Analysis Components
- `chart_analysis_widget.py` - Advanced charting with technical indicators
- `chart_cache_manager.py` - Chart data caching
- `chart_drawing_tools.py` - Drawing tools for chart analysis
- `data_fetcher_process.py` - Data fetching for charts

### Market Indicators
- `market_bias_manager.py` - Market bias indicator management
- `super_trend_manager.py` - Super trend indicator management

### Data Files
- `data/spreads/` - Spread matrices for different markets
- `data/market_bias/` - Market bias state data
- `data/super_trend/` - Super trend state data

### Voice Announcements (Optional)
- `voice/voice_announcer_v3.py` - Voice announcement system
- `voice/sounds/` - MP3 files for price announcements

### Simulation Support
- `simulation/` - Fallback simulation mode when Bloomberg/WebSocket unavailable

## 🚀 Quick Start

### Option 1: Using the run script (Recommended)
```bash
./run.sh
```

### Option 2: Manual setup
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python gui_graph.py
```

## 📋 Requirements

- Python 3.8 or higher
- All dependencies listed in `requirements.txt`

### Core Dependencies
- PyQt5 - GUI framework
- pyqtgraph - Real-time plotting
- pglive - Live plotting widgets
- numpy & pandas - Data processing
- pygame - Voice announcements (optional)

### Optional Dependencies
- blpapi - Bloomberg Terminal integration (if available)
- websockets - WebSocket price feeds

## 🎯 Features

### Data Sources
The application supports multiple data sources with automatic failover:
1. **Bloomberg Terminal** - Direct integration if available
2. **WebSocket** - Real-time price feeds
3. **Simulation** - Fallback mode with simulated prices

### Key Features
- Real-time FX price monitoring
- Interactive chart analysis with drawing tools
- Market bias and super trend indicators
- Voice price announcements
- Trade calculator
- Multiple spread matrix options
- Cross-currency calculations

## 🔧 Configuration

### Voice Speed
Adjust voice announcement speed:
```bash
python gui_graph.py --voice-speed 1.5
```

### Data Source
The application automatically detects available data sources and falls back as needed:
- Bloomberg Terminal → WebSocket → Simulation

## 📊 Usage

1. **Select Currency Pair**: Use the dropdown or type directly (e.g., EURUSD)
2. **View Prices**: Real-time bid/offer prices update automatically
3. **Chart Analysis**: Click "📈 Chart Analysis" for advanced charting
4. **Market Indicators**: View market bias and super trend indicators
5. **Trade Calculator**: Click "💱 Trade Calc" for position sizing
6. **Voice Announcements**: Toggle voice for audio price updates

## 🛠️ Troubleshooting

### Bloomberg Not Available
The application will automatically fall back to WebSocket or Simulation mode.

### Voice Not Working
Ensure pygame is installed: `pip install pygame`

### Missing Dependencies
Run: `pip install -r requirements.txt`

## 📝 Notes

- The application maintains state in `data/` subdirectories
- All spread matrices are pre-configured
- Voice files are included for major currencies
- Chart analysis includes technical indicators and drawing tools

## 🔄 Transferring to Another Machine

1. Copy the entire `Standalone/` directory
2. Install Python 3.8+
3. Run `./run.sh` or install dependencies manually
4. Launch the application

The package is completely self-contained and will work on any machine with Python installed.