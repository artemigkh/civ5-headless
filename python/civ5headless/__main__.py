"""python -m civ5headless: the c5h command line."""
import sys

if sys.version_info < (3, 11):
    sys.exit(f'c5h needs Python 3.11 or newer; this is {sys.version.split()[0]} ({sys.executable})')

from .cli import main  # noqa: E402

sys.exit(main())
