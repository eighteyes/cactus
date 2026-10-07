"""
test_store.py — unit tests for cactus.store.Store.

Responsibilities:
- Exercise per-project key numbering and the cursor() change token.
- Exercise answer()'s refusal paths and AlreadyAnswered.
- Exercise persistent (review/plan) rows: born live, repeatably answerable.
- Exercise reopen()'s two paths: withdraw an answer, restore a cleared row.
- Exercise projects()/project_enabled()/set_project_enabled() persistence.
- Exercise projects()'s due_count (open+elaborate, live excluded) and ordering.
- Exercise history(): answered/cleared rows with a verdict, newest first, scoped.
- Exercise ask()'s act/kind shape refusal and Store("")'s empty-path refusal.
"""

from __future__ import annotations

import threading
import time
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

    r1 = store.answer(q.key, project=project, selected=["fail"])
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


def test_projects_due_count_is_open_plus_elaborate_live_excluded(
    store: Store, project: str
) -> None:
    """due_count (q351) is open+elaborate; a live review never counts toward it."""
    open_q = store.ask("open one", project=project, cwd=project, agent=AGENT)
    elaborate_q = store.ask("elaborate me", project=project, cwd=project, agent=AGENT)
    store.elaborate_request(elaborate_q.key, project=project)
    store.ask(
        "review this", project=project, cwd=project, agent=AGENT,
        kind="confirm", act="review", choices=[Choice("pass"), Choice("fail")],
    )

    row = next(r for r in store.projects() if r["project"] == project)
    assert row["open_count"] == 1
    assert row["elaborate_count"] == 1
    assert row["live_count"] == 1
    assert row["due_count"] == 2


def test_projects_ordered_by_due_count_descending(store: Store, project: str, tmp_path: Path) -> None:
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    store.ask("only one due", project=str(quiet), cwd=str(quiet), agent=AGENT)
    for _ in range(3):
        store.ask("busier", project=project, cwd=project, agent=AGENT)

    rows = store.projects()
    assert rows[0]["project"] == project
    assert rows[0]["due_count"] == 3


def test_history_newest_verdict_first_answered_and_cleared_only(
    store: Store, project: str
) -> None:
    answered = store.ask("first", project=project, cwd=project, agent=AGENT)
    store.answer(answered.key, project=project, text="an answer")

    cleared = store.ask("second", project=project, cwd=project, agent=AGENT)
    store.answer(cleared.key, project=project, text="verdict before clearing")
    store.clear(keys=[cleared.key], project=project)

    never_answered = store.ask("third", project=project, cwd=project, agent=AGENT)
    store.clear(keys=[never_answered.key], project=project)

    rows = store.history(project)
    keys = [q.key for q in rows]
    # cleared's answer landed after answered's, so it sorts first; a cleared
    # row with no verdict at all never appears.
    assert keys == [cleared.key, answered.key]
    assert rows[0].status == "cleared"
    assert rows[0].answers[-1].text == "verdict before clearing"


def test_history_scoped_to_project(store: Store, project: str, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    other_project = str(other)
    here = store.ask("here", project=project, cwd=project, agent=AGENT)
    store.answer(here.key, project=project, text="ok")
    elsewhere = store.ask("elsewhere", project=other_project, cwd=other_project, agent=AGENT)
    store.answer(elsewhere.key, project=other_project, text="ok")

    assert [q.key for q in store.history(project)] == [here.key]


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


def test_project_panes_distinct_status_filtered_and_skipped(store: Store, project: str) -> None:
    def ask(agent: str, pane: str | None, session: str | None = "s1") -> str:
        return store.ask("q", project=project, cwd=project, agent=agent, kind="text",
                         act="ask", pane=pane, session=session).key

    ask("a1", "w1:p1")
    ask("a1b", "w1:p1")          # same pane again: newest agent wins, one entry
    ask("a2", "w1:p2")
    ask("a3", None)              # unstamped: counted, not reachable
    ask("a5", "w1:p2", "s2")     # same pane id, other herdr session: its own entry
    gone = ask("a4", "w1:p4")
    store.clear(keys=[gone], project=project)  # cleared rows do not count

    reach = store.project_panes(project)

    assert reach["panes"] == [
        {"pane": "w1:p1", "session": "s1", "agent": "a1b", "stale": []},
        {"pane": "w1:p2", "session": "s1", "agent": "a2", "stale": []},
        {"pane": "w1:p2", "session": "s2", "agent": "a5", "stale": []},
    ]
    assert reach["skipped"] == 1


def _live_review(store: Store, project: str, agent: str = "a1"):
    return store.ask(
        "check it", project=project, cwd=project, agent=agent,
        kind="confirm", act="review", choices=[Choice("pass"), Choice("fail")],
    )


def test_heard_state_sent_heard_responded_and_restart(store: Store, project: str) -> None:
    q = _live_review(store, project)
    assert store.get(q.key, project=project).heard_state is None  # no verdict yet

    store.mark_heard(q.id)  # nothing to hear yet
    assert store.get(q.key, project=project).heard_at is None

    store.answer(q.key, project=project, selected=["fail"])
    assert store.get(q.key, project=project).heard_state == "sent"

    store.mark_heard(q.id)
    assert store.get(q.key, project=project).heard_state == "heard"

    store.mark_responded(q.id)
    assert store.get(q.key, project=project).heard_state is None

    # A new verdict restarts at `sent`.
    store.answer(q.key, project=project, selected=["fail"])
    assert store.get(q.key, project=project).heard_state == "sent"


def test_mark_heard_moves_forward_past_latest_verdict_only(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["fail"])
    first = store.mark_heard(q.id)
    stamp, touched = first.heard_at, first.updated_at

    # Already heard past this verdict: no stamp move, no updated_at bump.
    again = store.mark_heard(q.id)
    assert again.heard_at == stamp
    assert again.updated_at == touched

    store.answer(q.key, project=project, selected=["fail"])
    later = store.mark_heard(q.id)
    assert later.heard_at > stamp


def test_mark_heard_bumps_cursor_and_ignores_other_acts(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["fail"])
    before = store.cursor()
    store.mark_heard(q.id)
    assert store.cursor() != before

    ask = store.ask("pick", project=project, cwd=project, agent="a1", kind="choice",
                    choices=[Choice("a")])
    store.answer(ask.key, project=project, selected=["a"])
    store.mark_heard(ask.id)
    assert store.get(ask.key, project=project).heard_at is None
    assert store.get(ask.key, project=project).heard_state is None


def test_heard_columns_do_not_change_monitor_signature(store: Store, project: str) -> None:
    from cactus.monitor import _signature

    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["fail"])
    sig = _signature(store.get(q.key, project=project))
    store.mark_heard(q.id)
    store.mark_responded(q.id)
    assert _signature(store.get(q.key, project=project)) == sig


def test_heard_columns_survive_key_rebuild(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["pass"])
    store.mark_heard(q.id)
    stamp = store.get(q.key, project=project).heard_at
    if store.needs_key_rebuild():
        store._drop_key_uniqueness()
    assert store.get(q.key, project=project).heard_at == stamp


def _auto_row(store: Store, project: str):
    return store.ask("pick one", project=project, cwd=project, agent=AGENT,
                     kind="choice", choices=[Choice("a"), Choice("b")])


def test_set_auto_writes_fields_and_bumps_cursor(store: Store, project: str) -> None:
    q = _auto_row(store, project)
    assert q.as_dict()["auto"] is None
    before = store.cursor()
    got = store.set_auto(q.key, "a", 0.9, "because", project=project)
    assert (got.auto_pick, got.auto_confidence, got.auto_reason) == ("a", 0.9, "because")
    assert got.auto_at is not None
    assert got.as_dict()["auto"] == {
        "pick": "a", "confidence": 0.9, "reason": "because", "at": got.auto_at,
    }
    assert store.cursor() != before
    assert store.set_auto(q.id, "b", 0.5, None).auto_pick == "b"


def test_set_auto_refuses_bad_pick_and_non_open(store: Store, project: str) -> None:
    q = _auto_row(store, project)
    with pytest.raises(ValueError):
        store.set_auto(q.key, "zzz", 0.9, None, project=project)
    store.answer(q.key, project=project, selected=["a"])
    with pytest.raises(ValueError):
        store.set_auto(q.key, "a", 0.9, None, project=project)


def test_set_auto_held_row_stamps_without_a_pick(store: Store, project: str) -> None:
    q = _auto_row(store, project)
    got = store.set_auto(q.key, None, 0.9, "costly · low", project=project)
    assert (got.auto_pick, got.auto_confidence) == (None, None)
    assert got.auto_reason == "costly · low"
    assert got.auto_at is not None
    assert got.as_dict()["auto"] is None
    assert store.clear_auto(q.key, project=project).auto_at is None


def test_clear_auto_nulls_all_four(store: Store, project: str) -> None:
    q = _auto_row(store, project)
    store.set_auto(q.key, "a", 0.9, "r", project=project)
    got = store.clear_auto(q.key, project=project)
    assert (got.auto_pick, got.auto_confidence, got.auto_reason, got.auto_at) == (
        None, None, None, None,
    )
    assert got.as_dict()["auto"] is None


def test_edit_clears_auto_only_when_text_or_choices_change(store: Store, project: str) -> None:
    q = _auto_row(store, project)
    store.set_auto(q.key, "a", 0.9, "r", project=project)
    same = store.edit(q.key, agent=AGENT, project=project, context="more")
    assert same.auto_pick == "a"
    text = store.edit(q.key, agent=AGENT, project=project, text="pick again")
    assert text.auto_pick is None
    store.set_auto(q.key, "a", 0.9, "r", project=project)
    chg = store.edit(q.key, agent=AGENT, project=project, choices=[Choice("a"), Choice("c")])
    assert chg.auto_pick is None and chg.auto_at is None


def test_auto_columns_survive_key_rebuild(store: Store, project: str) -> None:
    q = _auto_row(store, project)
    store.set_auto(q.key, "b", 0.7, "r", project=project)
    if store.needs_key_rebuild():
        store._drop_key_uniqueness()
    got = store.get(q.key, project=project)
    assert (got.auto_pick, got.auto_confidence, got.auto_reason) == ("b", 0.7, "r")


# --- wait_for_answer (q459) -------------------------------------------------


def _later(db: str, delay: float, fn) -> "threading.Thread":
    """Run fn(Store) on its own connection after `delay` seconds."""

    def run() -> None:
        time.sleep(delay)
        s = Store(db)
        try:
            fn(s)
        finally:
            s.close()

    t = threading.Thread(target=run)
    t.start()
    return t


def test_wait_returns_on_new_verdict_for_live_review(store: Store, project: str) -> None:
    q = store.ask("check", project=project, cwd=project, agent=AGENT, act="review",
                  kind="confirm", choices=[Choice("pass"), Choice("fail")])
    t = _later(store.path, 0.3, lambda s: s.answer(q.key, project=project, selected=["fail"]))
    got = store.wait_for_answer(q.key, project=project, timeout=10, poll=0.05)
    t.join()
    assert got is not None and got.status == "live" and len(got.answers) == 1


def test_wait_non_blocking_times_out_when_nothing_changes(store: Store, project: str) -> None:
    q = store.ask("fyi", project=project, cwd=project, agent=AGENT, act="notify")
    assert store.wait_for_answer(q.key, project=project, timeout=0.3, poll=0.05) is None


def test_wait_non_blocking_returns_on_clear(store: Store, project: str) -> None:
    q = store.ask("fyi", project=project, cwd=project, agent=AGENT, act="notify")
    t = _later(store.path, 0.3, lambda s: s.clear(keys=[q.key], project=project))
    got = store.wait_for_answer(q.key, project=project, timeout=10, poll=0.05)
    t.join()
    assert got is not None and got.status == "cleared"


def test_wait_snapshot_ignores_verdicts_before_the_wait(store: Store, project: str) -> None:
    q = store.ask("check", project=project, cwd=project, agent=AGENT, act="review",
                  kind="confirm", choices=[Choice("pass"), Choice("fail")])
    store.answer(q.key, project=project, selected=["pass"])
    assert store.wait_for_answer(q.key, project=project, timeout=0.3, poll=0.05) is None


def test_edit_does_not_end_wait_on_open_blocking_row(store: Store, project: str) -> None:
    q = store.ask("pick", project=project, cwd=project, agent=AGENT,
                  choices=[Choice("a"), Choice("b")])
    t = _later(store.path, 0.2, lambda s: s.edit(q.key, agent=AGENT, project=project, context="more"))
    assert store.wait_for_answer(q.key, project=project, timeout=1.0, poll=0.05) is None
    t.join()
    assert store.get(q.key, project=project).context == "more"


def test_ask_with_site_roundtrips(store: Store, project: str) -> None:
    q = store.ask("look", project=project, cwd=project, agent=AGENT, site="https://example.com/x")
    assert q.site == "https://example.com/x"
    got = store.get(q.key, project=project)
    assert got.site == "https://example.com/x"
    assert got.as_dict()["site"] == "https://example.com/x"


def test_ask_without_site_is_none(store: Store, project: str) -> None:
    q = store.ask("no site", project=project, cwd=project, agent=AGENT)
    assert q.site is None
    assert q.as_dict()["site"] is None


def test_edit_site_replace_keep_and_clear(store: Store, project: str) -> None:
    q = store.ask(
        "editable", project=project, cwd=project, agent=AGENT,
        site="https://a.example",
    )
    kept = store.edit(q.key, agent=AGENT, project=project, text="editable now")
    assert kept.site == "https://a.example"

    replaced = store.edit(q.key, agent=AGENT, project=project, site="https://b.example")
    assert replaced.site == "https://b.example"

    cleared = store.edit(q.key, agent=AGENT, project=project, site="")
    assert cleared.site is None


def _backdate(store: Store, key: str, hours: float) -> None:
    """Write `updated_at` directly, `hours` in the past, in `_now()`'s format."""
    from datetime import datetime, timedelta, timezone

    then = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="microseconds")
    store.conn.execute("UPDATE questions SET updated_at = ? WHERE key = ?", (then, key))


def test_stale_boundary_env_override_and_status(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cactus.store import stale_hours

    monkeypatch.delenv("CACTUS_STALE_HOURS", raising=False)
    assert stale_hours() == 24
    q = store.ask("idle", project=project, cwd=project, agent=AGENT)
    assert not store.get(q.key, project=project).stale()
    assert store.get(q.key, project=project).as_dict()["stale"] is False

    _backdate(store, q.key, 23.5)
    assert not store.get(q.key, project=project).stale()
    _backdate(store, q.key, 24.5)
    got = store.get(q.key, project=project)
    assert got.stale()
    assert got.as_dict()["stale"] is True
    assert got.as_dict()["idle_hours"] == 24.5
    assert got.idle_label() == "24h"

    _backdate(store, q.key, 60)
    assert store.get(q.key, project=project).idle_label() == "2d"

    # Any touch resets the clock.
    store.edit(q.key, agent=AGENT, project=project, text="idle, edited")
    assert not store.get(q.key, project=project).stale()

    # The env var moves the threshold; invalid values fall back to 24.
    _backdate(store, q.key, 3)
    monkeypatch.setenv("CACTUS_STALE_HOURS", "2")
    assert store.get(q.key, project=project).stale()
    for bad in ("", "soon", "0", "-5", "nan"):
        monkeypatch.setenv("CACTUS_STALE_HOURS", bad)
        assert stale_hours() == 24

    # Retired and answered rows never read stale.
    monkeypatch.setenv("CACTUS_STALE_HOURS", "1")
    _backdate(store, q.key, 100)
    store.clear(keys=[q.key], project=project)
    _backdate(store, q.key, 100)
    assert not store.get(q.key, project=project).stale()


def test_projects_stale_count_and_pane_stale_keys(store: Store, project: str) -> None:
    old = store.ask("old", project=project, cwd=project, agent="a1", pane="w1:p1", session="s1")
    store.ask("new", project=project, cwd=project, agent="a2", pane="w1:p2", session="s1")
    _backdate(store, old.key, 50)

    row = next(r for r in store.projects() if r["project"] == project)
    assert row["stale_count"] == 1
    panes = {p["pane"]: p["stale"] for p in store.project_panes(project)["panes"]}
    assert panes == {"w1:p1": [old.key], "w1:p2": []}


# ---- pass closes a review row (q601) ----------------------------------------


def test_pass_closes_review_row_and_keeps_the_verdict(store: Store, project: str) -> None:
    q = _live_review(store, project)
    r = store.answer(q.key, project=project, selected=["pass"])
    assert r.status == "cleared" and r.closed_by_pass
    assert r.answer is not None and r.answer.selected == ["pass"]
    again = store.get(q.key, project=project)
    assert again.status == "cleared" and len(again.answers) == 1


def test_fail_text_and_skip_leave_review_live(store: Store, project: str) -> None:
    q = _live_review(store, project)
    assert store.answer(q.key, project=project, selected=["fail"]).status == "live"
    assert store.answer(q.key, project=project, text="needs work").status == "live"
    r = store.answer(q.key, project=project, skipped=True)
    assert r.status == "live" and not r.closed_by_pass


def test_pass_only_closes_review_rows(store: Store, project: str) -> None:
    data = store.ask("d", project=project, cwd=project, agent="a1", kind="choice",
                     act="data", choices=[Choice("pass", "body")])
    assert store.answer(data.key, project=project, selected=["pass"]).status == "live"
    plain = store.ask("p", project=project, cwd=project, agent="a1", kind="choice",
                      choices=[Choice("pass"), Choice("fail")])
    r = store.answer(plain.key, project=project, selected=["pass"])
    assert r.status == "answered" and not r.closed_by_pass


def test_pass_after_fail_closes_and_undo_uncovers_the_fail(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["fail"])
    store.answer(q.key, project=project, selected=["pass"])
    r = store.reopen(q.key, project=project, withdraw_pass=True)
    assert r.status == "live" and not r.closed_by_pass
    assert [a.selected for a in r.answers] == [["fail"]]


def test_undo_of_pass_withdraws_the_verdict_and_goes_live(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["pass"])
    r = store.reopen(q.key, project=project, withdraw_pass=True)
    assert r.status == "live" and r.answers == [] and r.last_change is None
    # Exactly the state before the pass: it can be passed again.
    assert store.answer(q.key, project=project, selected=["pass"]).status == "cleared"


def test_plain_reopen_of_pass_closed_row_keeps_the_verdict(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["pass"])
    r = store.reopen(q.key, project=project)
    assert r.status == "live" and len(r.answers) == 1 and not r.closed_by_pass


def test_ordinary_clear_is_not_a_pass_and_withdraw_flag_is_ignored(store: Store, project: str) -> None:
    q = _live_review(store, project)
    store.answer(q.key, project=project, selected=["fail"])
    store.clear(keys=[q.key], project=project)
    assert not store.get(q.key, project=project).closed_by_pass
    r = store.reopen(q.key, project=project, withdraw_pass=True)
    assert r.status == "live" and len(r.answers) == 1


def test_wait_returns_when_pass_closes_a_live_review(store: Store, project: str) -> None:
    q = _live_review(store, project)
    t = _later(store.path, 0.3, lambda s: s.answer(q.key, project=project, selected=["pass"]))
    got = store.wait_for_answer(q.key, project=project, timeout=10, poll=0.05)
    t.join()
    assert got is not None and got.status == "cleared" and got.answer.selected == ["pass"]
