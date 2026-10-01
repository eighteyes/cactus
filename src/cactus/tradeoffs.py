# tradeoffs.py
# Pure parser for pro/con marks inside a choice description.
#
# Responsibilities:
#   - split a description into a summary and (is_pro, text) marks
#   - a line whose left-stripped text starts "+ " is a pro, "- " a con
#   - touch no store, no UI; callers decide how to render

from __future__ import annotations


def split(description: str | None) -> tuple[str, list[tuple[bool, str]]]:
    """Return (summary, marks). Non-mark lines join with a space as the summary."""
    summary: list[str] = []
    marks: list[tuple[bool, str]] = []
    for line in (description or "").splitlines():
        s = line.lstrip()
        if s.startswith("+ ") or s.startswith("- "):
            marks.append((s[0] == "+", s[2:].strip()))
        elif line.strip():
            summary.append(line.strip())
    return " ".join(summary), marks
