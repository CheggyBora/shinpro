#!/bin/bash

echo "========================================"
echo "  Tire Shop Management System"
echo "========================================"
echo ""
echo "Starting application..."
echo ""

python3 main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to start application!"
    echo ""
    echo "Possible reasons:"
    echo "1. Python 3 is not installed"
    echo "2. Libraries not installed (run: pip3 install -r requirements.txt)"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi
