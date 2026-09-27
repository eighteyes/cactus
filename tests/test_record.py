"""
test_record.py — decision-record rendering tests for cactus.record.

Responsibilities:
- Exercise the `## Files` section: present with a row's file list, absent
  without one, and the `## Rewrite` section's `files were:` on an edit.
"""

from __future__ import annotations

from cactus.store import Question, Store
from cactus import record

AGENT = "t"


def test_render_includes_files_section(store: Store, project: str) -> None:
    q = store.ask(
        "look at this", project=project, cwd=project, agent=AGENT,
        files=["/tmp/a.txt", "/tmp/b.txt"],
    )
    text = record.render(q, event="answer")
    assert "## Files" in text
    assert "- /tmp/a.txt" in text
    assert "- /tmp/b.txt" in text


def test_render_omits_files_section_when_empty(store: Store, project: str) -> None:
    q = store.ask("no files", project=project, cwd=project, agent=AGENT)
    text = record.render(q, event="answer")
    assert "## Files" not in text


def test_render_rewrite_shows_prior_files(store: Store, project: str) -> None:
    q = store.ask(
        "editable", project=project, cwd=project, agent=AGENT,
        files=["/tmp/old.txt"],
    )
    edited = store.edit(q.key, agent=AGENT, project=project, files=["/tmp/new.txt"])
    text = record.render(
        edited, event="edit",
        prior={"text": q.text, "context": q.context, "choices": q.choices, "files": q.files},
    )
    assert "## Rewrite" in text
    assert "files were:" in text
    assert "- /tmp/old.txt" in text
