"""
__init__.py — package entry point for cactus.

Responsibilities:
- Expose the package version.
- Re-export the store types that the CLI, TUI, and watch feed share.
"""

from .store import Answer, Choice, Question, Store, default_db_path

__version__ = "0.2.0"
__all__ = ["Answer", "Choice", "Question", "Store", "default_db_path", "__version__"]
