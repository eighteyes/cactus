"""
test_tradeoffs.py — tests for the pro/con parser in tradeoffs.py.

Responsibilities:
- Pin the split rules: `+ `/`- ` lines are marks, the rest is the summary.
"""

from cactus.tradeoffs import split


def test_no_marks_is_unchanged():
    assert split("existing IdP") == ("existing IdP", [])


def test_mixed_summary_and_marks():
    s, m = split("existing IdP\n+ tenant ready\n- couples us to uptime")
    assert s == "existing IdP"
    assert m == [(True, "tenant ready"), (False, "couples us to uptime")]


def test_leading_whitespace_still_marks():
    assert split("  + indented\n\t- tabbed") == ("", [(True, "indented"), (False, "tabbed")])


def test_dash_without_space_is_summary():
    assert split("-fast\n+x") == ("-fast +x", [])
    assert split("-") == ("-", [])


def test_empty_and_none():
    assert split("") == ("", [])
    assert split(None) == ("", [])
