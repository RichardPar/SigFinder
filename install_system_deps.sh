#!/bin/bash
# Install system dependencies for SigFinder

echo "Installing system dependencies for SigFinder..."

# Qt6 libraries needed by PyQt6
sudo apt-get update
sudo apt-get install -y \
    libxcb-cursor0 \
    libqt6qml6 \
    python3-pyqt6.qtqml \
    qml-qt6

# Additional libraries that might be needed
sudo apt-get install -y \
    libxcb-xinerama0 \
    libxkbcommon-x11-0

echo "System dependencies installed successfully!"
echo ""
echo "Now install Python packages with:"
echo "  pip install -r requirements.txt"
