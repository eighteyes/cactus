"""
test_store.py — unit tests for cactus.store.Store.

Responsibilities:
- Exercise per-project key numbering and the cursor() change token.
- Exercise answer()'s refusal paths and AlreadyAnswered.
- Exercise persistent (review/plan) rows: born live, repeatably answerable.
- Exercise reopen()'s two paths: withdraw an answer, restore a cleared row.
- Exercise projects()/project_enabled()/set_project_enabled() persistence.
- Exercise ask()'s act/kind shape refusal and Store("")'s empty-path refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cactus.store import AlreadyAnswered, Choice, Store

from conftest import AGENT, needs_project_switch


def test_ask_keys_per_project(store: Store, project: str, tmp_path: Path) -> None:
    """Each project numbers its own keys from q1."""
    q1 = store.ask("first question", project=project, cwd=project, agent=AGENT)
    assert q1.key == "q1"

    other = tmp_path / "other-proj"
    other.mkdir()
    other_project = str(other)
    q2 = store.ask("first in another project", project=other_project, cwd=other_project, agent=AGENT)
    # Per-project numbering (q166): a fresh database rebuilds UNIQUE(project,
    # key) up front, so a second project also starts at q1. If a database
    # were still pre-migration, this would instead read q2 (global numbering).
    assert q2.key == "q1"


def test_cursor_changes_on_ask_answer_and_purge(store: Store, project: str) -> None:
    """cursor() moves after ask, after answer, and after purging a non-newest row."""
    c0 = store.cursor()

    q1 = store.ask("q one", project=project, cwd=project, agent=AGENT)
    c1 = store.cursor()
    assert c1 != c0

    q2 = store.ask("q two", project=project, cwd=project, agent=AGENT)
    c2 = store.cursor()
    assert c2 != c1

    store.answer(q1.key, project=project, text="an answer")
    c3 = store.cursor()
    assert c3 != c2

    # Purging q1 (not the newest row) leaves max(id) and max(updated_at)
    # pointing at q2, so only the row count in the cursor's third element
    # catches the deletion.
    store.purge(keys=[q1.key], project=project)
    c4 = store.cursor()
    assert c4 != c3


def test_answer_refuses_off_menu_label(store: Store, project: str) -> None:
    q = store.ask(
        "pick one", project=project, cwd=project, kind="choice",
        choices=[Choice("a"), Choice("b")], agent=AGENT,
    )
    with pytest.raises(ValueError):
        store.answer(q.key, project=project, selected=["c"])


def test_answer_refuses_empty_answer(store: Store, project: str) -> None:
    q = store.ask("say something", project=project, cwd=project, agent=AGENT)
    with pytest.raises(ValueError):
        store.answer(q.key, project=project)


def test_answer_refuses_free_text_when_disallowed(store: Store, project: str) -> None:
    q = store.ask(
        "pick one", project=project, cwd=project, kind="choice",
        choices=[Choice("a"), Choice("b")], allow_free=False, agent=AGENT,
    )
    with pytest.raises(ValueError):
        store.answer(q.key, project=project, text="free text nobody asked for")


def test_answer_refuses_cleared_row(store: Store, project: str) -> None:
    q = store.ask("clear me", project=project, cwd=project, agent=AGENT)
    store.clear(keys=[q.key], project=project)
    with pytest.raises(ValueError):
        store.answer(q.key, project=project, text="too late")


def test_answer_refuses_selected_on_choiceless_row(store: Store, project: str) -> None:
    q = store.ask(
        "a plan", project=project, cwd=project, act="plan", kind="text", agent=AGENT,
    )
    with pytest.raises(ValueError):
        store.answer(q.key, project=project, selected=["x"])


def test_already_answered_on_one_shot_row(store: Store, project: str) -> None:
    q = store.ask("say something", project=project, cwd=project, agent=AGENT)
    store.answer(q.key, project=project, text="first answer")
    with pytest.raises(AlreadyAnswered):
        store.answer(q.key, project=project, text="second answer")


def test_review_row_born_live_and_repeatably_answerable(store: Store, project: str) -> None:
    q = store.ask(
        "does it pass", project=project, cwd=project, act="review", kind="confirm", agent=AGENT,
    )
    assert q.status == "live"

    r1 = store.answer(q.key, project=project, selected=["pass"])
    assert r1.status == "live"
    r2 = store.answer(q.key, project=project, selected=["fail"])
    assert r2.status == "live"

    assert len(r2.answers) == 2
    assert r2.answer is not None
    assert r2.answer.selected == ["fail"]


def test_reopen_answered_one_shot_deletes_answer(store: Store, project: str) -> None:
    q = store.ask("say something", project=project, cwd=project, agent=AGENT)
    store.answer(q.key, project=project, text="an answer")
    reopened = store.reopen(q.key, project=project)
    assert reopened.status == "open"
    assert reopened.answer is None
    assert reopened.answers == []


def test_reopen_cleared_persistent_row_restores_live(store: Store, project: str) -> None:
    q = store.ask(
        "plan it", project=project, cwd=project, act="plan", kind="text", agent=AGENT,
    )
    store.answer(q.key, project=project, text="verdict one")
    store.clear(keys=[q.key], project=project)
    restored = store.reopen(q.key, project=project)
    assert restored.status == "live"
    # A cleared restore never touched the answers log.
    assert len(restored.answers) == 1


@needs_project_switch
def test_projects_lists_cleared_project_with_settings_row(store: Store, project: str) -> None:
    q = store.ask("only question", project=project, cwd=project, agent=AGENT)
    store.clear(keys=[q.key], project=project)
    store.set_project_enabled(project, False)

    rows = {r["project"]: r for r in store.projects()}
    assert project in rows
    assert rows[project]["enabled"] == 0

    # Default enabled True for a project nobody has touched with
    # set_project_enabled.
    assert store.project_enabled("/nowhere/unseen/project") is True


@needs_project_switch
def test_set_project_enabled_persists_across_store_instances(
    store: Store, project: str
) -> None:
    store.set_project_enabled(project, False)
    second = Store(store.path)
    try:
        assert second.project_enabled(project) is False
    finally:
        second.close()


def test_ask_refuses_kind_not_in_act_shape(store: Store, project: str) -> None:
    with pytest.raises(ValueError):
        store.ask(
            "notify only takes text", project=project, cwd=project,
            act="notify", kind="choice", choices=[Choice("a")], agent=AGENT,
        )


def test_store_empty_path_raises() -> None:
    with pytest.raises(ValueError):
        Store("")


def test_ask_with_files_roundtrips(store: Store, project: str) -> None:
    q = store.ask(
        "look at this", project=project, cwd=project, agent=AGENT,
        files=["/tmp/a.txt", "/tmp/b.txt"],
    )
    assert q.files == ["/tmp/a.txt", "/tmp/b.txt"]

    got = store.get(q.key, project=project)
    assert got is not None
    assert got.files == ["/tmp/a.txt", "/tmp/b.txt"]
    assert got.as_dict()["files"] == ["/tmp/a.txt", "/tmp/b.txt"]


def test_ask_without_files_is_empty_list(store: Store, project: str) -> None:
    q = store.ask("no files here", project=project, cwd=project, agent=AGENT)
    assert q.files == []
    assert q.as_dict()["files"] == []


def test_edit_files_replace_keep_and_clear(store: Store, project: str) -> None:
    q = store.ask(
        "editable", project=project, cwd=project, agent=AGENT,
        files=["/tmp/a.txt"],
    )
    # None keeps the existing list.
    kept = store.edit(q.key, agent=AGENT, project=project, text="editable now")
    assert kept.files == ["/tmp/a.txt"]

    # A list replaces the whole thing.
    replaced = store.edit(q.key, agent=AGENT, project=project, files=["/tmp/c.txt"])
    assert replaced.files == ["/tmp/c.txt"]

    # An empty list clears it.
    cleared = store.edit(q.key, agent=AGENT, project=project, files=[])
    assert cleared.files == []


def test_set_files_replaces_and_refuses_cleared_row(store: Store, project: str) -> None:
    q = store.ask("plan it", project=project, cwd=project, act="plan", kind="text", agent=AGENT)
    updated = store.set_files(q.key, ["/tmp/plan.md"], project=project)
    assert updated.files == ["/tmp/plan.md"]

    store.clear(keys=[q.key], project=project)
    with pytest.raises(ValueError):
        store.set_files(q.key, ["/tmp/plan.md"], project=project)
