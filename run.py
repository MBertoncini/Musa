#!/usr/bin/env python
"""Launcher comodo: `python run.py "argomento"` equivale a `python -m musa.cli ...`."""
import sys

from musa.cli import main

if __name__ == "__main__":
    sys.exit(main())
