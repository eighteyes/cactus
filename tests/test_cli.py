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

AGENT_A = "agent-a"
AGENT_B = "agent-b"


def test_ask_without_agent_needs_agent(cli):
    r = cli("ask", "x", "-c", "a", "-c", "b")
    assert r.returncode == 1
    assert "needs --agent" in r.stderr


def test_ask_json_and_get_json_roundtrip(cli):
    r = cli("ask", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A, "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["key"] == "q1"

    r2 = cli("get", "q1", "--json")
    assert r2.returncode == 0
    rows = json.loads(r2.stdout)
    assert isinstance(rows, list)
    assert rows[0]["key"] == "q1"


def test_json_flag_before_and_after_verb(cli):
    cli("ask", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A)

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


def test_ask_wait_without_timeout_is_fine_but_no_timeout_without_wait(cli):
    r = cli("ask", "x", "--agent", AGENT_A, "--timeout", "1")
    assert r.returncode == 1
    assert "--timeout needs --wait" in r.stderr


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
    cli("ask", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A)

    r_bad = cli("answer", "q1", "-s", "zzz")
    assert r_bad.returncode == 1
    assert "choices are" in r_bad.stderr

    r_ok = cli("answer", "q1", "-s", "a")
    assert r_ok.returncode == 0

    r_again = cli("answer", "q1", "-s", "a")
    assert r_again.returncode == 3


def test_clear_ownership_then_reopen_restores_answered(cli):
    cli("ask", "pick one", "-c", "a", "-c", "b", "--agent", AGENT_A)
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


def test_project_disable_blocks_ask_and_run_then_reactivate(cli, project):
    r_status = cli("project", "status", "--json")
    assert r_status.returncode == 0
    assert json.loads(r_status.stdout)["enabled"] is True

    r_ignore = cli("project", "ignore", "--json")
    assert r_ignore.returncode == 0
    assert json.loads(r_ignore.stdout)["enabled"] is False

    r_ask = cli("ask", "x", "--agent", AGENT_A)
    assert r_ask.returncode == 1
    assert "cactus project activate" in r_ask.stderr

    r_run = cli("run", "echo hi", "--agent", AGENT_A)
    assert r_run.returncode == 1
    assert "cactus project activate" in r_run.stderr

    r_activate = cli("project", "activate", "--json")
    assert r_activate.returncode == 0
    assert json.loads(r_activate.stdout)["enabled"] is True

    r_ask_ok = cli("ask", "x", "--agent", AGENT_A)
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
    cli("ask", "x", "--agent", AGENT_A)
    r = cli("feed")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert "questions" in doc


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
