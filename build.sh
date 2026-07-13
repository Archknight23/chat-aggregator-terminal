#!/usr/bin/env bash
# Build standalone executable for current platform
# Requires: Python 3.11+, Node.js 18+, pip, npm

set -e

echo "[1/5] Creating virtual environment..."
python -m venv .venv
source .venv/bin/activate

echo "[2/5] Installing Python dependencies..."
pip install --upgrade pip
pip install -e ".[dev]"
pip install pyinstaller

echo "[3/5] Installing Node.js dependencies..."
npm install

echo "[4/5] Building Python executable with PyInstaller..."
pyinstaller --clean chat_aggregator.spec

echo "[5/5] Verifying build..."
if [ -f "dist/chat-aggregator" ]; then
    echo "✓ Executable built: dist/chat-aggregator"
    echo ""
    echo "Distribution contents:"
    echo "  - dist/chat-aggregator (Python TUI executable)"
    echo "  - server/ (Node.js backend - run with 'npm run server')"
    echo "  - package.json, pyproject.toml (for source installs)"
    echo ""
    echo "To test locally:"
    echo "  cd dist && ./chat-aggregator"
    echo ""
    echo "Note: The Node.js backend still requires Node.js 18+ at runtime."
    echo "Users can either:"
    echo "  1. Install Node.js and run 'npm install && npm run server' alongside the executable"
    echo "  2. Use the source install method (pip install -e .)"
else
    echo "✗ Build failed - dist/chat-aggregator not found"
    exit 1
fi
