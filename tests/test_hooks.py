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
- Check both Stop hooks stay silent unless CACTUS_STOP_HOOK=1.
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
    # The Stop hooks are opt-in; the suite exercises them switched on.
    env["CACTUS_STOP_HOOK"] = "1"
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
    assert "--monitor" in start.stdout

    asked = cli("ask", "pick a lane", "--agent", agent, "-c", "left", "-c", "right", cwd=project)
    assert asked.returncode == 0
    key = asked.stdout.strip()
    assert key

    frontier = run_hook(ROOT_HOOKS / "frontier.sh", {"cwd": project}, hook_env, project)
    assert key in frontier.stdout

    stop = run_hook(ROOT_HOOKS / "stop-fork.sh", {}, hook_env, project)
    assert "block" in stop.stdout

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
    assert "--monitor" in start.stdout

    asked = cli("ask", "pick a lane", "--agent", agent, "-c", "left", "-c", "right", cwd=project)
    assert asked.returncode == 0
    key = asked.stdout.strip()
    assert key

    frontier = run_hook(CODEX_HOOKS / "frontier.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert key in frontier.stdout

    stop = run_hook(CODEX_HOOKS / "stop.sh", {"session_id": agent, "cwd": project}, hook_env, project)
    assert "block" in stop.stdout

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


def test_stop_hooks_are_opt_in(cli, hook_env, project):
    """Open rows, no monitor: a turn both Stop hooks would hold, if switched on."""
    cli("project", "activate", cwd=project)
    agent = "stop-optin-1"
    assert cli("ask", "pick a lane", "--agent", agent, "-c", "left", "-c", "right", cwd=project).returncode == 0

    off = {k: v for k, v in hook_env.items() if k != "CACTUS_STOP_HOOK"}
    off["CACTUS_AGENT"] = agent
    payload = {"session_id": agent, "cwd": project}
    for script in (ROOT_HOOKS / "stop-fork.sh", CODEX_HOOKS / "stop.sh"):
        assert run_hook(script, payload, off, project).stdout.strip() == ""
        on = run_hook(script, payload, dict(off, CACTUS_STOP_HOOK="1"), project)
        assert "block" in on.stdout

