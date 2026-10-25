"""Tests of the verification suite (c5h verify): python -m unittest discover -s tests

The package is imported from python/ in this checkout when it is not installed; the fakes (fakegame, fake_session)
are imported from this folder.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for p in (REPO / 'python', HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
