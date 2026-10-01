"""
test_hooks.py — exercises the Claude Code and Codex plugin hook scripts end to end.

Responsibilities:
- Build a `cactus` shim on PATH that runs this checkout's CLI against a
  scratch database, and an environment with real HERDR_* identity stripped.
- Drive each hook script (`hooks/*.sh` for Claude Code, `plugins/cactus/hooks/*.sh`
  for Codex) with `bash script.sh` and JSON on stdin, the way the real host does.
- Check the disabled-project path is silent (or says so) for every hook, the
  enabled path produces the documented output, and a project disabled with
  `cactus project ignore` is not read as enabled by a stray jq `false` value.
- Check both Stop hooks are on by default and silent with CACTUS_STOP_HOOK=0.
- Check the PreToolUse wait guard blocks a foreground waiting ask/run and
  allows run_in_background, --no-wait, non-waiting acts and unrelated commands.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import needs_project_switch

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
ROOT_HOOKS = REPO / "hooks"
CODEX_HOOKS = REPO / "plugins" / "cactus" / "hooks"

pytestmark = [
    pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not on PATH"),
    needs_project_switch,
]


@pytest.fixture
def hook_env(tmp_path: Path, scratch_env: dict[str, str]) -> dict[str, str]:
    """Base environment for running a hook subprocess: shimmed cactus on PATH,
    the scratch db/poke/records vars, no herdr identity, and no CACTUS_AGENT
    unless a test adds one."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "cactus"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m cactus "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    for key in list(env):
        if key.startswith("HERDR_") or key == "CACTUS_AGENT":
            env.pop(key, None)
    env.update(scratch_env)
    env["PYTHONPATH"] = str(SRC)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    # permission-denied.sh dedupes tool_use_id through a state file under
    # $XDG_STATE_HOME; scope it to this test so a run never dedupes against
    # (or pollutes) the developer's real ~/.local/state/cactus.
    env["XDG_STATE_HOME"] = str(tmp_path / "xdg-state")
    # The Stop hooks are on by default (q411); the suite runs them that way.
    env.pop("CACTUS_STOP_HOOK", None)
    return env


def run_hook(script: Path, payload: dict, env: dict[str, str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def list_all(cli, project: str) -> list[dict]:
    proc = cli("list", "-s", "any", "--json", cwd=project)
    if not proc.stdout.strip():
        return []
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# Root plugin (Claude Code): hooks/*.sh, identity via CACTUS_AGENT/herdr
# --------------------------------------------------------------------------


def test_root_disabled_project_is_silent(cli, hook_env, project):
    cli("project", "ignore", cwd=project)

    start = run_hook(ROOT_HOOKS / "session-start.sh", {"cwd": project}, hook_env, project)
    assert "disabled" in start.stdout
    assert "cactus project activate" in start.stdout

    frontier = run_hook(ROOT_HOOKS / "frontier.sh", {"cwd": project}, hook_env, project)
    assert frontier.stdout.strip() == ""

    stop = run_hook(ROOT_HOOKS / "stop-fork.sh", {}, hook_env, project)
    assert stop.stdout.strip() == ""

    denied_env = dict(hook_env)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "tool_use_id": "tool-1",
        "denial_reason": "test",
        "cwd": project,
    }
    denied = run_hook(ROOT_HOOKS / "permission-denied.sh", payload, denied_env, project)
    assert denied.stdout.strip() == ""
    assert list_all(cli, project) == []


def test_root_enabled_project(cli, hook_env, project):
    cli("project", "activate", cwd=project)
    agent = "root-session-1"
    hook_env = dict(hook_env, CACTUS_AGENT=agent)

    start = run_hook(ROOT_HOOKS / "session-start.sh", {"cwd": project}, hook_env, project)
    assert "--monitor" not in start.stdout
    assert "next turn" in start.stdout

    asked = cli("ask", "--no-wait", "pick a lane", "--agent", agent, "-c", "left", "-c", "right", cwd=project)
    assert asked.returncode == 0
    key = asked.stdout.strip()
    assert key

    frontier = run_hook(ROOT_HOOKS / "frontier.sh", {"cwd": project}, hook_env, project)
    assert key in frontier.stdout

    stop = run_hook(ROOT_HOOKS / "stop-fork.sh", {}, hook_env, project)
    assert stop.stdout.strip() == ""

    before = list_all(cli, project)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /tmp/whatever"},
        "tool_use_id": "tool-2",
        "denial_reason": "auto-mode denied it",
        "cwd": project,
    }
    denied = run_hook(ROOT_HOOKS / "permission-denied.sh", payload, hook_env, project)
    assert denied.returncode == 0
    after = list_all(cli, project)
    assert len(after) == len(before) + 1
    new_rows = [r for r in after if r["key"] not in {r2["key"] for r2 in before}]
    assert len(new_rows) == 1
    assert new_rows[0]["act"] == "run"


def test_root_ignore_not_fooled_by_false(cli, hook_env, project):
    cli("project", "activate", cwd=project)
    cli("project", "ignore", cwd=project)

    status = cli("project", "status", "--json", cwd=project)
    info = json.loads(status.stdout)
    assert info["enabled"] is False

    agent = "root-session-2"
    hook_env = dict(hook_env, CACTUS_AGENT=agent)

    assert run_hook(ROOT_HOOKS / "session-start.sh", {"cwd": project}, hook_env, project).stdout.count(
        "disabled"
    ) >= 1
    assert run_hook(ROOT_HOOKS / "frontier.sh", {"cwd": project}, hook_env, project).stdout.strip() == ""
    assert run_hook(ROOT_HOOKS / "stop-fork.sh", {}, hook_env, project).stdout.strip() == ""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo nope"},
        "tool_use_id": "tool-3",
        "denial_reason": "test",
        "cwd": project,
    }
    denied = run_hook(ROOT_HOOKS / "permission-denied.sh", payload, hook_env, project)
    assert denied.stdout.strip() == ""
    assert list_all(cli, project) == []


# --------------------------------------------------------------------------
# Codex plugin: plugins/cactus/hooks/*.sh, identity via session_id in payload
# --------------------------------------------------------------------------


def test_codex_disabled_project_is_silent(cli, hook_env, project):
    cli("project", "ignore", cwd=project)
    agent = "codex-session-1"

    start = run_hook(CODEX_HOOKS / "session-start.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert "disabled" in start.stdout

    frontier = run_hook(CODEX_HOOKS / "frontier.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert frontier.stdout.strip() == ""

    stop = run_hook(CODEX_HOOKS / "stop.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert stop.stdout.strip() == ""

    payload = {
        "session_id": agent,
        "tool_input": {"command": "echo hi", "description": "test"},
        "cwd": project,
    }
    req = run_hook(CODEX_HOOKS / "permission-request.sh", payload, hook_env, project)
    assert req.stdout.strip() == ""
    assert list_all(cli, project) == []


def test_codex_enabled_project(cli, hook_env, project):
    cli("project", "activate", cwd=project)
    agent = "codex-session-2"

    start = run_hook(CODEX_HOOKS / "session-start.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    # Codex has no wake-up from idle (q342): the hook must not tell it to arm
    # a monitor, and must name the foreground block for an answer it needs now.
    assert "--monitor" not in start.stdout
    assert "--wait" in start.stdout

    asked = cli("ask", "--no-wait", "pick a lane", "--agent", agent, "-c", "left", "-c", "right", cwd=project)
    assert asked.returncode == 0
    key = asked.stdout.strip()
    assert key

    frontier = run_hook(CODEX_HOOKS / "frontier.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert key in frontier.stdout

    stop = run_hook(CODEX_HOOKS / "stop.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert stop.stdout.strip() == ""  # never blocks on Codex (q342)

    before = list_all(cli, project)
    payload = {
        "session_id": agent,
        "tool_input": {"command": "rm -rf /tmp/whatever", "description": "needs approval"},
        "cwd": project,
    }
    req = run_hook(CODEX_HOOKS / "permission-request.sh", payload, hook_env, project)
    assert req.returncode == 0
    body = json.loads(req.stdout)
    new_key = body["hookSpecificOutput"]["decision"]["message"]
    after = list_all(cli, project)
    assert len(after) == len(before) + 1
    new_rows = [r for r in after if r["key"] not in {r2["key"] for r2 in before}]
    assert len(new_rows) == 1
    assert new_rows[0]["act"] == "run"
    assert new_rows[0]["key"] in new_key


def test_codex_ignore_not_fooled_by_false(cli, hook_env, project):
    cli("project", "activate", cwd=project)
    cli("project", "ignore", cwd=project)

    status = cli("project-status", "--json", "--cwd", project, cwd=project)
    info = json.loads(status.stdout)
    assert info["enabled"] is False

    agent = "codex-session-3"

    assert "disabled" in run_hook(
        CODEX_HOOKS / "session-start.sh", {"session_id": agent, "cwd": project}, hook_env, project
    ).stdout
    assert run_hook(
        CODEX_HOOKS / "frontier.sh", {"session_id": agent, "cwd": project}, hook_env, project
    ).stdout.strip() == ""
    assert run_hook(
        CODEX_HOOKS / "stop.sh", {"session_id": agent, "cwd": project}, hook_env, project
    ).stdout.strip() == ""
    payload = {
        "session_id": agent,
        "tool_input": {"command": "echo nope", "description": "test"},
        "cwd": project,
    }
    req = run_hook(CODEX_HOOKS / "permission-request.sh", payload, hook_env, project)
    assert req.stdout.strip() == ""
    assert list_all(cli, project) == []


def test_stop_hooks_do_not_require_monitor(cli, hook_env, project):
    """Open rows are normal between turns; neither Stop hook demands a monitor."""
    cli("project", "activate", cwd=project)
    agent = "stop-optin-1"
    assert cli("ask", "--no-wait", "pick a lane", "--agent", agent, "-c", "left", "-c", "right", cwd=project).returncode == 0

    on = dict(hook_env, CACTUS_AGENT=agent)
    payload = {"session_id": agent, "cwd": project}
    script = ROOT_HOOKS / "stop-fork.sh"
    assert run_hook(script, payload, on, project).stdout.strip() == ""
    # The Codex Stop hook never blocks for open rows: collection happens on the
    # next turn, so a block would repeat on every stop.
    script = CODEX_HOOKS / "stop.sh"
    assert run_hook(script, payload, on, project).stdout.strip() == ""


def _transcript(tmp_path: Path, *assistant_content: dict) -> str:
    """One human prompt followed by one assistant message, as JSONL."""
    path = tmp_path / "transcript.jsonl"
    rows = [
        {"type": "user", "message": {"content": "do the thing"}},
        {"type": "assistant", "message": {"content": list(assistant_content)}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


def test_stop_hook_on_by_default_holds_a_turn_without_an_ask(hook_env, project, tmp_path):
    env = dict(hook_env)
    script = ROOT_HOOKS / "stop-fork.sh"
    bare = {"cwd": project, "transcript_path": _transcript(tmp_path, {"type": "text", "text": "done"})}
    held = run_hook(script, bare, env, project)
    assert json.loads(held.stdout)["decision"] == "block"
    assert run_hook(script, bare, dict(env, CACTUS_STOP_HOOK="0"), project).stdout.strip() == ""

    asked = {"cwd": project, "transcript_path": _transcript(
        tmp_path, {"type": "tool_use", "name": "Bash", "input": {"command": "cactus ask hi --agent a"}})}
    assert run_hook(script, asked, env, project).stdout.strip() == ""


# --------------------------------------------------------------------------
# PreToolUse wait guard: a waiting cactus ask/run must run in the background
# --------------------------------------------------------------------------


def _wait_guard(cmd: str, hook_env, project, **tool_input) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd, **tool_input}, "cwd": project}
    return run_hook(ROOT_HOOKS / "pretooluse-wait.sh", payload, hook_env, project)


@pytest.mark.parametrize("cmd", [
    "cactus ask 'pick' -c a -c b --agent x",
    "cactus ask 'sure?' --confirm --agent x --timeout 600",
    "cactus run 'make deploy' --agent x",
    "K=$(cactus ask 'pick' --agent x)",
    "cd /tmp && cactus ask 'pick' --agent x --wait",
])
def test_wait_guard_blocks_foreground_wait(cmd, hook_env, project):
    r = _wait_guard(cmd, hook_env, project)
    assert r.returncode == 2
    assert "run_in_background: true" in r.stderr


@pytest.mark.parametrize("cmd", [
    "cactus ask 'pick' -c a -c b --agent x --no-wait",
    "cactus ask 'pick' --agent x --no-block",
    "cactus ask 'going' --act steer --chosen a -c a -c b --agent x",
    "cactus ask 'fyi' --act notify --agent x",
    "cactus ask 'v' --act review --agent x",
    "cactus ask 'p' --act plan --agent x",
    "cactus run 'make deploy' --agent x --no-wait",
    "cactus get q1 --wait",
    "cactus list",
    "ls -la",
    "git commit -m 'cactus ask is now default-wait'",
])
def test_wait_guard_allows_non_waiting_and_unrelated(cmd, hook_env, project):
    r = _wait_guard(cmd, hook_env, project)
    assert r.returncode == 0
    assert r.stderr == "" and r.stdout == ""


def test_wait_guard_allows_background_wait(hook_env, project):
    r = _wait_guard("cactus ask 'pick' --agent x", hook_env, project, run_in_background=True)
    assert r.returncode == 0
    assert r.stderr == ""


def test_wait_guard_ignores_other_tools(hook_env, project):
    payload = {"tool_name": "Write", "tool_input": {"command": "cactus ask x"}}
    assert run_hook(ROOT_HOOKS / "pretooluse-wait.sh", payload, hook_env, project).returncode == 0


def test_wait_guard_is_registered_on_bash():
    cfg = json.loads((ROOT_HOOKS / "hooks.json").read_text())
    entry = cfg["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    assert "pretooluse-wait.sh" in entry["hooks"][0]["command"]
