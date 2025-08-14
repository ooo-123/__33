#!/bin/bash

# FX GUI Standalone Runner
# This script runs the FX GUI application

echo "🚀 Starting FX GUI Application..."
echo "================================"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Check if virtual environment exists, create if not
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/upgrade pip
pip install --upgrade pip > /dev/null 2>&1

# Install requirements if needed
echo "📦 Checking dependencies..."
pip install -q -r requirements.txt

# Run the GUI application
echo "✅ Launching GUI..."
echo "================================"
python gui_graph.py "$@"

# Deactivate virtual environment on exit
deactivate