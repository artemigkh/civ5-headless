"""Tests of the civ5headless package (platform workstream): python -m unittest discover -s tests

The package is imported from python/ in this checkout when it is not installed.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / 'python') not in sys.path:
    sys.path.insert(0, str(REPO / 'python'))
