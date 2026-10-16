"""
test_shell.py — the viewer resolver and the new-window dispatch in shell.py.

Responsibilities:
- Pin viewer_argv's order: CACTUS_PAGER, the template argument, PAGER, less.
- Pin view_window's CACTUS_VIEW_WINDOW override and its {cmd} line.
"""

from __future__ import annotations

import pytest

from cactus import shell


def test_viewer_order_env_pager_beats_template(monkeypatch):
    monkeypatch.setenv("CACTUS_PAGER", "envp {path}")
    assert shell.viewer_argv("/a b", "glow -p {path}") == ["envp", "/a b"]


def test_viewer_template_beats_pager_and_appends_path(monkeypatch):
    monkeypatch.delenv("CACTUS_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "more")
    assert shell.viewer_argv("/f.md", "glow -p {path}") == ["glow", "-p", "/f.md"]
    assert shell.viewer_argv("/f.md", "glow -p") == ["glow", "-p", "/f.md"]


@pytest.mark.parametrize("template", [None, "", "auto", " AUTO "])
def test_viewer_auto_falls_to_pager_then_less(monkeypatch, template):
    monkeypatch.delenv("CACTUS_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "more")
    assert shell.viewer_argv("/f", template) == ["more", "/f"]
    monkeypatch.delenv("PAGER")
    assert shell.viewer_argv("/f", template) == ["less", "/f"]


def test_view_window_override_gets_the_viewer_line(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("CACTUS_PAGER", "pg {path}")
    monkeypatch.setenv("CACTUS_VIEW_WINDOW", f"sh -c 'printf %s \"$0\" > {out}' {{cmd}}")
    shell.view_window(["/a", "/b c"])
    assert out.read_text() == "pg /a; pg '/b c'"
