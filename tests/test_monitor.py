"""
test_monitor.py — behavioral tests for cactus.monitor's --agent JSON stream.

Responsibilities:
- Run `python -m cactus --monitor --json` as a subprocess against the
  scratch database while a second Store instance in the test process drives
  the inbox (ask, answer, clear, reopen, purge).
- Assert the emitted event sequence matches the invariants in CLAUDE.md:
  asked and edited suppression under --agent, reopened on undo, gone on
  purge, verdict on a persistent row, --once exits after the first
  non-asked/non-edited event, and --replay lists the current inbox as
  asked before streaming.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cactus.monitor import run_monitor  # noqa: E402
from cactus.store import Choice, Store  # noqa: E402


def start_monitor(scratch_env: dict[str, str], project: str, *extra_args: str) -> subprocess.Popen:
    """Launch `cactus --monitor --json` as a subprocess against the scratch db."""
    env = {**os.environ, **scratch_env, "PYTHONPATH": str(SRC)}
    argv = [sys.executable, "-m", "cactus", "--monitor", "--json", "--interval", "0.1", *extra_args]
    return subprocess.Popen(
        argv,
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_and_read(proc: subprocess.Popen, timeout: float = 5.0) -> list[dict]:
    """Terminate the subprocess and parse each stdout line as JSON."""
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=timeout)
    events = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def wait_a_tick() -> None:
    # Long enough for the subprocess's 0.1s poll loop to see the change and
    # emit it, short enough to keep the whole file's runtime under ~5s.
    time.sleep(0.3)


def run_unfiltered_once(db_path: str, project: str, **kwargs) -> threading.Thread:
    """Run `run_monitor` in-process with no --agent filter, `once=True`.

    The CLI refuses `--monitor` without `--agent` (humans use --tui/--watch),
    so an unfiltered stream can only be observed by calling the library
    function directly. A sqlite3 connection is unusable outside the thread
    that opened it, so `Store` is opened inside `target`, not shared with the
    test's own `store` fixture; the thread exits on its own once `once=True`
    sees a non-asked event, so no signal to stop it is needed.
    """

    def target() -> None:
        mstore = Store(db_path)
        try:
            run_monitor(mstore, project=project, interval=0.05, once=True, **kwargs)
        finally:
            mstore.close()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


def test_asked_suppressed_under_agent_then_answered(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a")
    try:
        wait_a_tick()
        q = store.ask("mine", project=project, cwd=project, agent="agent-a")
        wait_a_tick()
        store.answer(q.key, project=project, text="done")
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    assert not any(e["event"] == "asked" for e in events)
    answered = [e for e in events if e["event"] == "answered"]
    assert len(answered) == 1
    assert answered[0]["key"] == q.key


def test_other_agents_row_never_emitted(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a")
    try:
        wait_a_tick()
        q = store.ask("theirs", project=project, cwd=project, agent="agent-b")
        wait_a_tick()
        store.answer(q.key, project=project, text="done")
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    assert not any(e.get("key") == q.key for e in events)


def test_cleared_reopened_gone_in_order(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a")
    try:
        wait_a_tick()
        q = store.ask("lifecycle", project=project, cwd=project, agent="agent-a")
        wait_a_tick()
        store.clear(keys=[q.key], project=project)
        wait_a_tick()
        store.reopen(q.key, project=project)
        wait_a_tick()
        store.purge(keys=[q.key], project=project)
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    names = [e["event"] for e in events if e.get("key") == q.key or e.get("ref", "").endswith(q.key)]
    assert names == ["cleared", "reopened", "gone"]


def test_verdict_on_persistent_row_then_undo_reopened(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a")
    try:
        wait_a_tick()
        q = store.ask(
            "review this",
            project=project,
            cwd=project,
            agent="agent-a",
            act="review",
            kind="confirm",
        )
        wait_a_tick()
        store.answer(q.key, project=project, selected=["pass"])
        wait_a_tick()
        store.reopen(q.key, project=project)
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    mine = [e for e in events if e.get("key") == q.key]
    assert not any(e["event"] == "answered" for e in mine)
    assert any(e["event"] == "verdict" for e in mine)
    assert any(e["event"] == "reopened" for e in mine)
    verdict_idx = [i for i, e in enumerate(mine) if e["event"] == "verdict"][0]
    reopened_idx = [i for i, e in enumerate(mine) if e["event"] == "reopened"][0]
    assert verdict_idx < reopened_idx


def test_once_exits_right_after_first_non_asked_event(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a", "--once")
    try:
        wait_a_tick()
        q = store.ask("quick", project=project, cwd=project, agent="agent-a")
        wait_a_tick()
        store.answer(q.key, project=project, text="ok")
        rc = proc.wait(timeout=5.0)
    finally:
        events = stop_and_read(proc)

    assert rc == 0
    assert any(e["event"] == "answered" and e["key"] == q.key for e in events)


def test_replay_emits_current_open_rows_as_asked(scratch_env, project, store):
    q = store.ask("pre-existing", project=project, cwd=project, agent="agent-a")

    proc = start_monitor(scratch_env, project, "--agent", "agent-a", "--replay")
    try:
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    asked = [e for e in events if e["event"] == "asked" and e["key"] == q.key]
    assert len(asked) == 1


def test_files_only_edit_reads_as_edited(scratch_env, project, store, tmp_path, capsys):
    # `files` is in the signature: an edit that changes nothing but the file
    # list must still surface, or the human's board shows stale paths.
    # Unfiltered (no --agent) because `edited` is now suppressed under an
    # agent filter (q334) — see test_edited_suppressed_under_agent below.
    one = tmp_path / "one.txt"
    one.write_text("1")
    two = tmp_path / "two.txt"
    two.write_text("2")
    q = store.ask(
        "look at this", project=project, cwd=project, agent="agent-a",
        files=[str(one)],
    )
    t = run_unfiltered_once(scratch_env["CACTUS_DB"], project, as_json=True)
    time.sleep(0.2)
    store.edit(q.key, agent="agent-a", project=project, files=[str(two)])
    t.join(timeout=5.0)
    assert not t.is_alive()

    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    mine = [e for e in events if e.get("key") == q.key]
    assert any(e["event"] == "edited" for e in mine)


def test_edited_suppressed_under_agent(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a")
    try:
        wait_a_tick()
        q = store.ask("mine", project=project, cwd=project, agent="agent-a")
        wait_a_tick()
        store.edit(q.key, agent="agent-a", project=project, text="mine, edited")
        wait_a_tick()
        store.answer(q.key, project=project, text="done")
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    assert not any(e["event"] == "edited" for e in events)
    answered = [e for e in events if e["event"] == "answered"]
    assert len(answered) == 1
    assert answered[0]["key"] == q.key


def test_once_ignores_edit_under_agent_then_exits_on_answered(scratch_env, project, store):
    proc = start_monitor(scratch_env, project, "--agent", "agent-a", "--once")
    try:
        wait_a_tick()
        q = store.ask("quick", project=project, cwd=project, agent="agent-a")
        wait_a_tick()
        store.edit(q.key, agent="agent-a", project=project, text="quick, edited")
        wait_a_tick()
        # An edit under --agent must not end a --once wait: it is the
        # agent's own action echoed back, not something to end the wait for.
        assert proc.poll() is None
        store.answer(q.key, project=project, text="ok")
        rc = proc.wait(timeout=5.0)
    finally:
        events = stop_and_read(proc)

    assert rc == 0
    assert not any(e["event"] == "edited" for e in events)
    assert any(e["event"] == "answered" and e["key"] == q.key for e in events)


def test_heard_and_responded_stamps_wake_nobody(scratch_env, project, store):
    q = store.ask(
        "check it", project=project, cwd=project, agent="agent-a",
        kind="confirm", act="review", choices=[Choice("pass"), Choice("fail")],
    )
    store.answer(q.key, project=project, selected=["pass"])
    proc = start_monitor(scratch_env, project, "--agent", "agent-a")
    try:
        wait_a_tick()
        store.mark_heard(q.id)
        wait_a_tick()
        store.mark_responded(q.id)
        wait_a_tick()
    finally:
        events = stop_and_read(proc)

    assert not any(e.get("key") == q.key for e in events)


def test_auto_proposal_does_not_change_signature(scratch_env, project, store):
    """A proposal must never wake the asking agent."""
    from cactus.monitor import _signature

    q = store.ask("pick", project=project, cwd=project, agent="a1", kind="choice",
                  choices=[Choice("a"), Choice("b")])
    sig = _signature(store.get(q.key, project=project))
    store.set_auto(q.key, "a", 0.9, "r", project=project)
    assert _signature(store.get(q.key, project=project)) == sig
    store.clear_auto(q.key, project=project)
    assert _signature(store.get(q.key, project=project)) == sig
