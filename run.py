#!/usr/bin/env python3
"""
run.py — Project root entry point.

Usage:
    python run.py

The actual main() lives in src/main.py to keep the root clean and
to allow PyInstaller to bundle the app correctly.
"""

import sys
import os

# Make sure the project root is on sys.path when double-clicked or
# run from a different working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import main

if __name__ == "__main__":
    main()
