"""
test_mcp.py — argv-building tests for cactus.mcp's CLI bridge.

Responsibilities:
- Exercise `_argv_for`'s mapping of MCP tool arguments to a cactus argv,
  focused on the `files` field cactus_ask/cactus_edit/cactus_review/
  cactus_plan all accept.
"""

from __future__ import annotations

from cactus.mcp import _argv_for


def test_cactus_ask_files_maps_to_repeated_dash_f() -> None:
    argv = _argv_for("cactus_ask", {"text": "look", "agent": "a", "files": ["x", "y"]})
    assert argv[:3] == ["ask", "look", "--agent"]
    assert "-f" in argv
    fs = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-f"]
    assert fs == ["x", "y"]


def test_cactus_edit_files_maps_to_repeated_dash_f() -> None:
    argv = _argv_for("cactus_edit", {"key": "q1", "agent": "a", "files": ["z"]})
    assert "-f" in argv
    fs = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-f"]
    assert fs == ["z"]


def test_cactus_review_files_maps_to_repeated_dash_f() -> None:
    argv = _argv_for("cactus_review", {"key": "q1", "files": ["a", "b"]})
    fs = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-f"]
    assert fs == ["a", "b"]


def test_cactus_plan_files_maps_to_repeated_dash_f() -> None:
    argv = _argv_for("cactus_plan", {"key": "q1", "files": ["p"]})
    fs = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-f"]
    assert fs == ["p"]
