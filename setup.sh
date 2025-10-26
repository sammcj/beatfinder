#!/bin/bash
# BeatFinder setup script

set -e

echo "Setting up BeatFinder..."

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found"
    exit 1
fi

# Install dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo ""
    echo "✓ Setup complete!"
    echo ""
    echo "Next steps:"
    echo "1. Get a Last.fm API key from: https://www.last.fm/api/account/create"
    echo "2. Edit .env and add your LASTFM_API_KEY"
    echo "3. Run: python3 beatfinder.py"
else
    echo ".env already exists, skipping..."
    echo ""
    echo "✓ Dependencies installed!"
fi
