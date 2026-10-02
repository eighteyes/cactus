"""
test_cli.py — CLI-surface behavior tests for cactus, driven as subprocesses.

Responsibilities:
- Exercise the verbs and flag refusals documented in cli.py and CLAUDE.md's
  Invariants section, one small test per behavior.
- Assert exit codes and the one stderr/stdout line that matters for each case,
  never internal store state directly.
- Use the `cli` fixture (scratch CACTUS_DB, inert CACTUS_POKE, CACTUS_RECORDS=0)
  and the `project` fixture from conftest.py exclusively.
"""

from __future__ import annotations

import json

import pytest
from conftest import needs_project_switch

AGENT_A = "agent-a"
AGENT_B = "agent-b"


def test_ask_without_agent_needs_agent(cli):
    r = cli("ask", "x", "-c", "a", "-c", "b")
    assert r.returncode == 1
    assert "needs --agent" in r.stderr


def test_ask_json_and_get_json_roundtrip(cli):
    r = cli("ask", "--no-wait", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A, "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["key"] == "q1"

    r2 = cli("get", "q1", "--json")
    assert r2.returncode == 0
    rows = json.loads(r2.stdout)
    assert isinstance(rows, list)
    assert rows[0]["key"] == "q1"


def test_json_flag_before_and_after_verb(cli):
    cli("ask", "--no-wait", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A)

    r_before = cli("--json", "get", "q1")
    assert r_before.returncode == 0
    json.loads(r_before.stdout)

    r_after = cli("get", "q1", "--json")
    assert r_after.returncode == 0
    json.loads(r_after.stdout)


def test_ask_notify_with_choices_refused(cli):
    r = cli("ask", "heads up", "--act", "notify", "-c", "a", "--agent", AGENT_A)
    assert r.returncode == 1
    assert "collects text only" in r.stderr


def test_ask_timeout_with_no_wait_refused(cli):
    r = cli("ask", "x", "--agent", AGENT_A, "--no-wait", "--timeout", "1")
    assert r.returncode == 1
    assert "--timeout needs a waiting row" in r.stderr


def test_ask_waits_by_default_and_times_out_exit_2(cli):
    r = cli("ask", "x", "-c", "a", "-c", "b", "--agent", AGENT_A, "--timeout", "0.5")
    assert r.returncode == 2
    assert r.stdout.splitlines()[0] == "q1"  # key printed before the block
    assert "timed out waiting for q1" in r.stderr


def test_ask_wait_flag_is_a_noop_still_accepted(cli):
    r = cli("ask", "x", "--agent", AGENT_A, "--wait", "--timeout", "0.5")
    assert r.returncode == 2


def test_ask_default_wait_returns_when_answered(cli, scratch_env, project):
    import os, subprocess, sys, time
    from conftest import SRC
    env = {**os.environ, **scratch_env, "PYTHONPATH": str(SRC)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "cactus", "ask", "pick", "-c", "a", "-c", "b",
         "--agent", AGENT_A, "--timeout", "30", "--json"],
        cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stderr.readline().strip() == "q1"  # key out before the block
        assert proc.poll() is None
        assert cli("answer", "q1", "-s", "a").returncode == 0
        out, _ = proc.communicate(timeout=20)
    finally:
        proc.kill()
    assert proc.returncode == 0
    doc = json.loads(out)
    assert doc["key"] == "q1" and doc["status"] == "answered"


def test_ask_no_wait_returns_at_once(cli):
    r = cli("ask", "x", "--agent", AGENT_A, "--no-wait", timeout=10)
    assert r.returncode == 0
    assert r.stdout.strip() == "q1"


def test_ask_no_block_never_waits(cli):
    r = cli("ask", "x", "-c", "a", "-c", "b", "--agent", AGENT_A, "--no-block", timeout=10)
    assert r.returncode == 0
    assert r.stdout.strip() == "q1"


def test_non_blocking_acts_never_wait(cli):
    cases = [
        ("steer", ["--chosen", "a", "-c", "a", "-c", "b"]),
        ("notify", []),
        ("review", []),
        ("plan", []),
        ("data", ["-c", "one: body"]),
    ]
    for act, extra in cases:
        r = cli("ask", f"{act} row", "--act", act, "--agent", AGENT_A, *extra, timeout=10)
        assert r.returncode == 0, (act, r.stderr)
        assert r.stdout.strip().startswith("q")


def test_run_waits_by_default_and_times_out_exit_2(cli):
    r = cli("run", "echo hi", "--agent", AGENT_A, "--timeout", "0.5")
    assert r.returncode == 2
    assert r.stdout.splitlines()[0] == "q1"


def test_run_accepts_wait_timeout_and_no_wait(cli):
    assert cli("run", "echo hi", "--agent", AGENT_A, "--wait", "--timeout", "0.5").returncode == 2
    r = cli("run", "echo hi", "--agent", AGENT_A, "--no-wait", timeout=10)
    assert r.returncode == 0
    r = cli("run", "echo hi", "--agent", AGENT_A, "--no-wait", "--timeout", "1")
    assert r.returncode == 1
    assert "--timeout needs a waiting row" in r.stderr


def test_ask_steer_wait_refused_never_blocks(cli):
    r = cli(
        "ask", "which way", "--act", "steer", "--chosen", "a",
        "-c", "a", "-c", "b", "--agent", AGENT_A, "--wait",
    )
    assert r.returncode == 1
    assert "--wait needs a blocking row" in r.stderr


def test_get_missing_key_exits_3(cli):
    r = cli("get", "q99")
    assert r.returncode == 3
    assert r.stderr.strip() != ""


def test_list_empty_project_exits_3_no_match(cli):
    r = cli("list")
    assert r.returncode == 3
    assert "cactus: no match" in r.stderr


def test_answer_flow_invalid_label_then_ok_then_already_answered(cli):
    cli("ask", "--no-wait", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A)

    r_bad = cli("answer", "q1", "-s", "zzz")
    assert r_bad.returncode == 1
    assert "choices are" in r_bad.stderr

    r_ok = cli("answer", "q1", "-s", "a")
    assert r_ok.returncode == 0

    r_again = cli("answer", "q1", "-s", "a")
    assert r_again.returncode == 3


def test_clear_ownership_then_reopen_restores_answered(cli):
    cli("ask", "--no-wait", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A)
    cli("answer", "q1", "-s", "a")

    r_wrong_owner = cli("clear", "q1", "--agent", AGENT_B)
    assert r_wrong_owner.returncode == 1
    assert "do not own" in r_wrong_owner.stderr

    r_clear = cli("clear", "q1", "--agent", AGENT_A)
    assert r_clear.returncode == 0

    r_reopen = cli("reopen", "q1", "--agent", AGENT_A)
    assert r_reopen.returncode == 0

    r_get = cli("get", "q1", "--json")
    assert r_get.returncode == 0
    rows = json.loads(r_get.stdout)
    assert rows[0]["status"] == "answered"


@needs_project_switch
def test_project_disable_blocks_ask_and_run_then_reactivate(cli, project):
    r_status = cli("project", "status", "--json")
    assert r_status.returncode == 0
    assert json.loads(r_status.stdout)["enabled"] is True

    r_ignore = cli("project", "ignore", "--json")
    assert r_ignore.returncode == 0
    assert json.loads(r_ignore.stdout)["enabled"] is False

    r_ask = cli("ask", "--no-wait", "x", "--agent", AGENT_A)
    assert r_ask.returncode == 1
    assert "cactus project activate" in r_ask.stderr

    r_run = cli("run", "--no-wait", "echo hi", "--agent", AGENT_A)
    assert r_run.returncode == 1
    assert "cactus project activate" in r_run.stderr

    r_activate = cli("project", "activate", "--json")
    assert r_activate.returncode == 0
    assert json.loads(r_activate.stdout)["enabled"] is True

    r_ask_ok = cli("ask", "--no-wait", "x", "--agent", AGENT_A)
    assert r_ask_ok.returncode == 0

    r_status_other = cli("project", "status", "--json", "--cwd", project)
    assert r_status_other.returncode == 0
    assert json.loads(r_status_other.stdout)["project"] == project


def test_monitor_without_agent_needs_agent(cli):
    r = cli("--monitor")
    assert r.returncode == 1
    assert "needs --agent" in r.stderr


def test_tui_and_watch_together_refused(cli):
    r = cli("--tui", "--watch")
    assert r.returncode == 1
    assert "mutually exclusive" in r.stderr


def test_feed_always_json_even_without_flag(cli):
    cli("ask", "--no-wait", "x", "--agent", AGENT_A)
    r = cli("feed")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert "questions" in doc


def test_ask_file_resolves_relative_path_to_absolute(cli, project):
    import os

    rel = "notes.txt"
    (open(os.path.join(project, rel), "w")).close()

    r = cli("ask", "--no-wait", "look at this", "--agent", AGENT_A, "-f", rel, "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["files"] == [os.path.join(project, rel)]


def test_ask_file_missing_exits_1(cli):
    r = cli("ask", "--no-wait", "x", "--agent", AGENT_A, "-f", "nope.txt")
    assert r.returncode == 1
    assert "no such file: nope.txt" in r.stderr


def test_ask_file_directory_exits_1(cli, project):
    r = cli("ask", "--no-wait", "x", "--agent", AGENT_A, "-f", ".")
    assert r.returncode == 1
    assert "not a file: ." in r.stderr


def test_ask_file_duplicate_exits_1(cli, project):
    import os

    (open(os.path.join(project, "a.txt"), "w")).close()

    r = cli("ask", "--no-wait", "x", "--agent", AGENT_A, "-f", "a.txt", "-f", "./a.txt")
    assert r.returncode == 1
    assert "duplicate file:" in r.stderr


def test_edit_file_replaces_whole_list(cli, project):
    import os

    (open(os.path.join(project, "a.txt"), "w")).close()
    (open(os.path.join(project, "b.txt"), "w")).close()

    cli("ask", "--no-wait", "x", "--agent", AGENT_A, "-f", "a.txt")
    r = cli("edit", "q1", "--agent", AGENT_A, "-f", "b.txt", "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["files"] == [os.path.join(project, "b.txt")]


def test_get_text_shows_file_line(cli, project):
    import os

    (open(os.path.join(project, "a.txt"), "w")).close()
    cli("ask", "--no-wait", "look here", "--agent", AGENT_A, "-f", "a.txt")

    r = cli("get", "q1")
    assert r.returncode == 0
    assert os.path.join(project, "a.txt") in r.stdout
    assert "file" in r.stdout


def test_agent_help_waits_backgrounded_and_never_pushes(cli):
    r = cli("--agent-help")
    assert r.returncode == 0
    assert "-f PATH" in r.stdout
    assert "its exit is your wake-up" in r.stdout
    assert "woken by the answer itself" not in r.stdout
    assert "arm in the background" not in r.stdout


def test_review_file_replaces_and_keeps(cli, project):
    import os

    (open(os.path.join(project, "spec.md"), "w")).close()
    (open(os.path.join(project, "spec2.md"), "w")).close()

    cli("ask", "review this", "--act", "review", "--agent", AGENT_A)
    r1 = cli("review", "q1", "-f", "spec.md", "--json")
    assert r1.returncode == 0
    assert json.loads(r1.stdout)["files"] == [os.path.join(project, "spec.md")]

    # Omitting -f keeps the existing list.
    r2 = cli("review", "q1", "--pass", "looks good", "--json")
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["files"] == [os.path.join(project, "spec.md")]

    # A missing file refuses before anything else is written.
    r3 = cli("review", "q1", "-f", "nope.md")
    assert r3.returncode == 1
    assert "no such file: nope.md" in r3.stderr


def test_plan_file_replaces_and_keeps(cli, project):
    import os

    (open(os.path.join(project, "plan.md"), "w")).close()

    cli("ask", "make a plan", "--act", "plan", "--agent", AGENT_A)
    r1 = cli("plan", "q1", "-f", "plan.md", "--json")
    assert r1.returncode == 0
    assert json.loads(r1.stdout)["files"] == [os.path.join(project, "plan.md")]

    # Omitting -f keeps the existing list.
    r2 = cli("plan", "q1", "--step", "a", "--json")
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["files"] == [os.path.join(project, "plan.md")]

    r3 = cli("plan", "q1", "-f", "nope.md")
    assert r3.returncode == 1
    assert "no such file: nope.md" in r3.stderr


def test_plan_done_and_undone_same_step_refused_and_reset_needs_step(cli):
    cli("ask", "make a plan", "--act", "plan", "--agent", AGENT_A)

    r_steps = cli("plan", "q1", "--step", "a", "--step", "b")
    assert r_steps.returncode == 0

    r_clash = cli("plan", "q1", "--done", "1", "--undone", "1")
    assert r_clash.returncode == 1
    assert "both name step" in r_clash.stderr

    r_reset = cli("plan", "q1", "--reset-steps")
    assert r_reset.returncode == 1
    assert "--reset-steps needs at least one --step" in r_reset.stderr


def test_sky_dump_refuses_an_existing_file_without_force(cli, scratch_env):
    first = cli("sky", "--dump")
    assert first.returncode == 0
    assert "wrote defaults" in first.stdout
    second = cli("sky", "--dump")
    assert second.returncode == 1
    assert "exists" in second.stderr and "--force" in second.stderr
    forced = cli("sky", "--dump", "--force")
    assert forced.returncode == 0


def test_garden_prints_path_and_clear_removes_file(cli, scratch_env):
    from pathlib import Path

    empty = cli("garden")
    assert empty.returncode == 0
    assert "empty" in empty.stdout

    path = Path(scratch_env["CACTUS_DB"]).parent / "garden.json"
    path.write_text('{"version": 1, "drops": 3, "cells": [[1, 0, 0]]}', encoding="utf-8")

    present = cli("garden")
    assert present.returncode == 0
    assert str(path) in present.stdout
    assert "1 cells" in present.stdout
    assert "3 drops" in present.stdout

    cleared = cli("garden", "--clear")
    assert cleared.returncode == 0
    assert "cleared" in cleared.stdout
    assert not path.exists()

    again = cli("garden", "--clear")
    assert again.returncode == 0
    assert "nothing to clear" in again.stdout


def _heard_review(cli, agent=AGENT_A):
    assert cli("ask", "check it", "--act", "review", "--agent", agent).returncode == 0
    assert cli("answer", "q1", "-s", "pass").returncode == 0


def _heard_state(store, project, key="q1"):
    return store.get(key, project=project).heard_state


def test_get_agent_owner_marks_heard(cli, store, project):
    _heard_review(cli)
    assert _heard_state(store, project) == "sent"
    r = cli("get", "q1", "--agent", AGENT_A, "--json")
    assert r.returncode == 0
    assert json.loads(r.stdout)  # output unchanged: still the row JSON
    assert _heard_state(store, project) == "heard"


def test_get_non_owner_and_bare_get_do_not_mark_heard(cli, store, project):
    _heard_review(cli)
    assert cli("get", "q1", "--agent", "someone-else").returncode == 0
    assert _heard_state(store, project) == "sent"
    assert cli("get", "q1").returncode == 0
    assert _heard_state(store, project) == "sent"


def test_get_agent_ignores_non_review_plan_rows(cli, store, project):
    cli("ask", "--no-wait", "pick", "--agent", AGENT_A, "-c", "a", "-c", "b")
    cli("answer", "q1", "-s", "a")
    assert cli("get", "q1", "--agent", AGENT_A).returncode == 0
    assert store.get("q1", project=project).heard_at is None


def test_plan_review_edit_with_owner_agent_mark_responded(cli, store, project):
    _heard_review(cli)
    cli("get", "q1", "--agent", AGENT_A)
    assert _heard_state(store, project) == "heard"
    assert cli("review", "q1", "--agent", AGENT_A, "--look-at", "x").returncode == 0
    assert _heard_state(store, project) is None

    cli("answer", "q1", "-s", "fail")
    assert _heard_state(store, project) == "sent"
    assert cli("edit", "q1", "--agent", AGENT_A, "--context", "more").returncode == 0
    assert _heard_state(store, project) is None

    cli("ask", "the plan", "--act", "plan", "--agent", AGENT_A)
    cli("answer", "q2", "looks fine")
    assert _heard_state(store, project, "q2") == "sent"
    assert cli("plan", "q2", "--agent", AGENT_A, "--step", "one").returncode == 0
    assert _heard_state(store, project, "q2") is None


def test_plan_review_without_matching_agent_do_not_mark_responded(cli, store, project):
    _heard_review(cli)
    assert cli("review", "q1", "--look-at", "x").returncode == 0
    assert _heard_state(store, project) == "sent"
    assert cli("review", "q1", "--agent", "someone-else", "--look-at", "y").returncode == 1
    assert _heard_state(store, project) == "sent"


def test_text_render_shows_tradeoff_marks_on_choice_rows(cli):
    cli("ask", "--no-wait", "which?", "-c", "a: sum\n+ good\n- bad", "-c", "b", "--agent", AGENT_A)
    r = cli("get", "q1")
    assert "1) a" in r.stdout
    assert "✓ good" in r.stdout
    assert "✗ bad" in r.stdout
    raw = json.loads(cli("get", "q1", "--json").stdout)[0]
    assert "+ good" in raw["choices"][0]["description"]


def test_agent_help_waits_on_the_denied_hook_row(cli):
    r = cli("--agent-help")
    assert "-t denied" in r.stdout
    assert "cactus get KEY --wait" in r.stdout


def test_answer_never_pokes_an_unmapped_owner(cli, scratch_env, project, tmp_path):
    # q430: auto-poke on answer is webhook-only; CACTUS_POKE is ignored here.
    log = tmp_path / "wake.log"
    script = tmp_path / "wake.sh"
    script.write_text(f'#!/bin/sh\necho "$1|$2" >> {log}\n')
    script.chmod(0o755)
    scratch_env["CACTUS_POKE"] = f"{script} {{agent}} {{message}}"
    cli("ask", "--no-wait", "pick", "--agent", AGENT_A, "-c", "x", "-c", "y")
    assert cli("answer", "q1", "-s", "x").returncode == 0
    assert not log.exists()


def test_version_flag_prints_package_version(cli):
    from cactus import __version__
    r = cli("--version")
    assert r.returncode == 0
    assert r.stdout.strip() == f"cactus {__version__}"


# ---- decider ----------------------------------------------------------------

_STUB_SERVER = '''\
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''


@pytest.fixture
def decider_env(tmp_path, monkeypatch):
    """A free port, an inert stub server command, and the URL pointing at it."""
    import socket
    import sys

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    script = tmp_path / "stub_server.py"
    script.write_text(_STUB_SERVER)
    monkeypatch.setenv("CACTUS_DECIDER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("CACTUS_DECIDER_CMD", f"{sys.executable} {script} {{port}}")
    monkeypatch.delenv("CACTUS_DECIDER_BACKEND", raising=False)
    return tmp_path


def _wait_up(cli, want_exit: int) -> None:
    import time

    for _ in range(50):
        if cli("decider", "status").returncode == want_exit:
            return
        time.sleep(0.1)
    raise AssertionError(f"decider never reached status exit {want_exit}")


def test_decider_start_status_stop(cli, decider_env):
    assert cli("decider", "status").returncode == 3
    assert cli("decider", "stop").returncode == 3
    started = cli("decider", "start", "--json")
    assert started.returncode == 0, started.stderr
    info = json.loads(started.stdout)
    assert info["backend"] == "strands" and info["pid"]
    assert (decider_env / "decider-strands.pid").read_text().strip() == str(info["pid"])
    try:
        _wait_up(cli, 0)
        status = json.loads(cli("decider", "status", "--json").stdout)
        assert status["up"] is True and status["pid"] == info["pid"]
        assert status["log"].endswith("decider-strands.log")
        again = cli("decider", "start")
        assert again.returncode == 0 and "already running" in again.stdout
    finally:
        stopped = cli("decider", "stop")
    assert stopped.returncode == 0
    assert not (decider_env / "decider-strands.pid").exists()
    _wait_up(cli, 3)
    assert cli("decider", "stop").returncode == 3


def test_decider_start_missing_binary_refuses(cli, monkeypatch):
    monkeypatch.delenv("CACTUS_DECIDER_CMD", raising=False)
    monkeypatch.delenv("CACTUS_DECIDER_BACKEND", raising=False)
    monkeypatch.setenv("CACTUS_DECIDER_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("PATH", "/nonexistent")
    r = cli("decider", "start")
    assert r.returncode == 1
    assert "pip install strands-decider" in r.stderr


# ---- human verbs: elaborate, undo, exec ---------------------------------


def _row(cli, key="q1"):
    return json.loads(cli("get", key, "--json").stdout)[0]


def test_elaborate_hint_then_withdraw_restores_status(cli):
    cli("ask", "--no-wait", "pick", "-c", "a", "-c", "b", "--agent", AGENT_A)
    r = cli("elaborate", "q1", "say more", "--json")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "elaborate"
    assert _row(cli)["elaborate"] == "say more"
    w = cli("elaborate", "q1", "--withdraw", "--json")
    assert w.returncode == 0
    assert json.loads(w.stdout)["status"] == "open"
    assert cli("elaborate", "q1", "--withdraw").returncode == 1


def test_elaborate_decompose_stores_instruction(cli):
    from cactus.store import DECOMPOSE_INSTRUCTION

    cli("ask", "--no-wait", "big", "-c", "a", "-c", "b", "--agent", AGENT_A)
    assert cli("elaborate", "q1", "--decompose").returncode == 0
    assert _row(cli)["elaborate"] == DECOMPOSE_INSTRUCTION.format(key="q1")


def test_elaborate_refusals_and_missing_key(cli):
    cli("ask", "--no-wait", "big", "-c", "a", "-c", "b", "--agent", AGENT_A)
    assert cli("elaborate", "q1", "hint", "--decompose").returncode == 1
    assert cli("elaborate", "q1", "hint", "--withdraw").returncode == 1
    assert cli("elaborate", "q1").returncode == 0
    again = cli("elaborate", "q1")
    assert again.returncode == 1 and "elaborate" in again.stderr
    miss = cli("elaborate", "q99")
    assert miss.returncode == 3 and len(miss.stderr.strip().splitlines()) == 1
    assert cli("elaborate", "q99", "--withdraw").returncode == 3


def test_undo_withdraws_answer(cli):
    cli("ask", "--no-wait", "pick", "-c", "a", "-c", "b", "--agent", AGENT_A)
    assert cli("undo", "q1").returncode == 1  # open: nothing to undo
    cli("answer", "q1", "-s", "a")
    r = cli("undo", "q1", "--json")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "open"
    assert cli("answer", "q1", "-s", "b").returncode == 0


def test_undo_refuses_cleared_and_missing(cli):
    cli("ask", "--no-wait", "pick", "-c", "a", "-c", "b", "--agent", AGENT_A)
    cli("answer", "q1", "-s", "a")
    cli("clear", "q1", "--agent", AGENT_A)
    r = cli("undo", "q1")
    assert r.returncode == 1 and "cactus reopen q1 --agent ID" in r.stderr
    miss = cli("undo", "q99")
    assert miss.returncode == 3 and len(miss.stderr.strip().splitlines()) == 1


def test_undo_live_review_withdraws_only_newest_verdict(cli):
    cli("ask", "check", "--act", "review", "--no-wait", "--agent", AGENT_A)
    cli("answer", "q1", "-s", "fail")
    cli("answer", "q1", "-s", "pass")
    assert cli("undo", "q1").returncode == 0
    row = _row(cli)
    assert row["status"] == "live"
    assert row["answer"]["selected"] == ["fail"]
    assert cli("undo", "q1").returncode == 0
    assert cli("undo", "q1").returncode == 1  # no verdict left


def test_exec_run_row_records_result_and_approve(cli):
    cli("run", "--no-wait", "echo hi", "--agent", AGENT_A)
    r = cli("exec", "q1")
    assert r.returncode == 0
    assert "hi" in r.stdout
    row = _row(cli)
    assert row["status"] == "answered"
    assert row["answer"]["selected"] == ["approve"]
    assert row["result"]["exit"] == 0
    assert any("hi" in line for line in row["result"]["tail"])


def test_exec_nonzero_command_still_exits_zero(cli):
    cli("run", "--no-wait", "echo oops; exit 3", "--agent", AGENT_A)
    assert cli("exec", "q1").returncode == 0
    assert _row(cli)["result"]["exit"] == 3


def test_exec_review_row_records_result_without_answering(cli):
    cli("ask", "check", "--act", "review", "--no-wait", "--agent", AGENT_A)
    cli("review", "q1", "--run", "echo hi")
    r = cli("exec", "q1", "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["result"]["exit"] == 0
    assert doc["answer"] is None
    assert doc["status"] == "live"
    assert "hi" in r.stderr  # live output moves to stderr under --json


def test_exec_refusals_and_missing_key(cli):
    cli("ask", "check", "--act", "review", "--no-wait", "--agent", AGENT_A)
    no_cmd = cli("exec", "q1")
    assert no_cmd.returncode == 1 and "no command" in no_cmd.stderr
    miss = cli("exec", "q99")
    assert miss.returncode == 3 and len(miss.stderr.strip().splitlines()) == 1
