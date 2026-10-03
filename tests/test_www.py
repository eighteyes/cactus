"""
test_www.py — the web board's card renders a row's site as a safe link.
"""

from __future__ import annotations

from cactus.www import PAGE


def test_card_renders_site_as_escaped_blank_link() -> None:
    assert 'target="_blank" rel="noopener"' in PAGE
    # Only http(s) becomes a link, and the href is attribute-escaped.
    assert "/^https?:" in PAGE
    assert '.replace(/"/g, "&quot;")' in PAGE
    assert "esc(q.site)" in PAGE
