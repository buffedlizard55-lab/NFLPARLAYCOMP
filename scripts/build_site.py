#!/usr/bin/env python3
"""CLI wrapper for site builder."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.site_builder import main

if __name__ == "__main__":
    raise SystemExit(main())
