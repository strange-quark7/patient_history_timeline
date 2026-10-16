"""Entry point for the frozen engine that ships inside the desktop app (see scripts/freeze.py)."""

import sys

from medtimeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
