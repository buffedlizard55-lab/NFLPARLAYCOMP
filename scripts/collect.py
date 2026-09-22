#!/usr/bin/env python3
"""CLI wrapper for the data collector (see engine/collect.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.collect import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
