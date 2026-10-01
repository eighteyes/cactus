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

from conftest import needs_project_switch

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


@needs_project_switch
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


def test_ask_file_resolves_relative_path_to_absolute(cli, project):
    import os

    rel = "notes.txt"
    (open(os.path.join(project, rel), "w")).close()

    r = cli("ask", "look at this", "--agent", AGENT_A, "-f", rel, "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["files"] == [os.path.join(project, rel)]


def test_ask_file_missing_exits_1(cli):
    r = cli("ask", "x", "--agent", AGENT_A, "-f", "nope.txt")
    assert r.returncode == 1
    assert "no such file: nope.txt" in r.stderr


def test_ask_file_directory_exits_1(cli, project):
    r = cli("ask", "x", "--agent", AGENT_A, "-f", ".")
    assert r.returncode == 1
    assert "not a file: ." in r.stderr


def test_ask_file_duplicate_exits_1(cli, project):
    import os

    (open(os.path.join(project, "a.txt"), "w")).close()

    r = cli("ask", "x", "--agent", AGENT_A, "-f", "a.txt", "-f", "./a.txt")
    assert r.returncode == 1
    assert "duplicate file:" in r.stderr


def test_edit_file_replaces_whole_list(cli, project):
    import os

    (open(os.path.join(project, "a.txt"), "w")).close()
    (open(os.path.join(project, "b.txt"), "w")).close()

    cli("ask", "x", "--agent", AGENT_A, "-f", "a.txt")
    r = cli("edit", "q1", "--agent", AGENT_A, "-f", "b.txt", "--json")
    assert r.returncode == 0
    doc = json.loads(r.stdout)
    assert doc["files"] == [os.path.join(project, "b.txt")]


def test_get_text_shows_file_line(cli, project):
    import os

    (open(os.path.join(project, "a.txt"), "w")).close()
    cli("ask", "look here", "--agent", AGENT_A, "-f", "a.txt")

    r = cli("get", "q1")
    assert r.returncode == 0
    assert os.path.join(project, "a.txt") in r.stdout
    assert "file" in r.stdout


def test_agent_help_uses_next_turn_collection_not_monitor(cli):
    r = cli("--agent-help")
    assert r.returncode == 0
    assert "-f PATH" in r.stdout
    assert "next turn" in r.stdout
    assert "--monitor" not in r.stdout


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
    cli("ask", "pick", "--agent", AGENT_A, "-c", "a", "-c", "b")
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
    cli("ask", "which?", "-c", "a: sum\n+ good\n- bad", "-c", "b", "--agent", AGENT_A)
    r = cli("get", "q1")
    assert "1) a" in r.stdout
    assert "✓ good" in r.stdout
    assert "✗ bad" in r.stdout
    raw = json.loads(cli("get", "q1", "--json").stdout)[0]
    assert "+ good" in raw["choices"][0]["description"]
