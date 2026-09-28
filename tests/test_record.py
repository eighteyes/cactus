"""
test_record.py — decision-record rendering tests for cactus.record.

Responsibilities:
- Exercise the `## Files` section: present with a row's file list, absent
  without one, and the `## Rewrite` section's `files were:` on an edit.
- Exercise q341's filename scheme: two rows sharing a per-project key never
  collide, and an old-style `q{N}-*.md` is left untouched and never reused.
"""

from __future__ import annotations

import dataclasses

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


def test_record_path_disambiguates_shared_key_by_id(store: Store, tmp_path) -> None:
    """Two rows sharing a per-project key (q166 numbering, or two projects)
    must never land on the same record file (q341)."""
    proj_a = tmp_path / "proj-a"
    proj_b = tmp_path / "proj-b"
    proj_a.mkdir()
    proj_b.mkdir()
    q_a = store.ask("first project's first row", project=str(proj_a), cwd=str(proj_a), agent=AGENT)
    q_b = store.ask("second project's first row", project=str(proj_b), cwd=str(proj_b), agent=AGENT)
    assert q_a.key == q_b.key == "q1"
    assert q_a.id != q_b.id

    path_a = record.write_record(q_a, event="answer")
    path_b = record.write_record(q_b, event="answer")

    assert path_a != path_b
    assert path_a.exists()
    assert path_b.exists()


def test_record_path_ignores_old_style_file(store: Store, project: str) -> None:
    """An old bare `q{N}-*.md` from before q341 is never matched or reused."""
    q = store.ask("shares a key with an old-style file", project=project, cwd=project, agent=AGENT)
    forced = dataclasses.replace(q, key="q7")
    old_dir = record.records_dir(forced.project)
    old_dir.mkdir(parents=True, exist_ok=True)
    old_file = old_dir / "q7-old.md"
    old_file.write_text("# stale pre-q341 record\n")

    new_path = record.write_record(forced, event="answer")

    assert new_path != old_file
    assert old_file.read_text() == "# stale pre-q341 record\n"
    assert new_path.name.startswith(f"q7-{forced.id}-")
