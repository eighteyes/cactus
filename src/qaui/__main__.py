"""
__main__.py — `python -m qaui` entry point.

Responsibilities:
- Hand argv to the CLI and propagate its exit code.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
