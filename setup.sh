#!/bin/bash
# Setup script for WhatsSpy

set -e

echo "Creating virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing WhatsSpy in editable mode..."
pip install -e .

echo ""
echo "Setup complete! Activate with:"
echo "  source venv/bin/activate"
echo ""
echo "Then run your bot with:"
echo "  python example.py"
