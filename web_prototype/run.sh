#!/bin/bash
# Quick start script for BeatFinder web prototype

set -e

echo "🎵 BeatFinder Web Prototype"
echo "============================"
echo ""

# Check if Flask is installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Installing Flask..."
    pip3 install -q -r requirements.txt
    echo "✅ Flask installed"
    echo ""
fi

echo "🚀 Starting server on http://localhost:5001"
echo "   Press Ctrl+C to stop"
echo ""

python3 app.py
