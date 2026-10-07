# cactus_identity.py
# Shared helpers for the Claude Code hooks: resolve the cactus --agent value, run the cactus CLI, read the payload.
# Responsibilities:
#   - resolve_agent: payload session_id first, then herdr's view of the pane, then CACTUS_AGENT
#   - run: call a program by argv (never a shell) and return (returncode, stdout), or None when it cannot start
#   - project_enabled: false only when `cactus project-status --json` says enabled is false
#   - read_stdin: read the hook payload once, as text
# Imported by the hooks through their own directory on sys.path. Python 3 stdlib only.
#
# Order matters. The payload wins because it is the harness naming its own
# conversation, live at the moment the hook runs. herdr infers the id from the
# transcript file, and at SessionStart after /clear that file does not exist
# yet, so herdr still answers with the previous conversation's id (q327) and
# every row of the new session lands under a dead owner. A hook must read its
# stdin and pass it in, or tier 1 is skipped silently.
#
# Wrong-owner / dead-owner rows trace here. Check: did the hook pass the
# payload text? Is HERDR_PANE_ID set? Does CACTUS_AGENT hold a stale id? Fix a
# session already posting under a dead id with `cactus rehome --agent NEW`.
import json
import os
import shutil
import subprocess
import sys


def read_stdin():
    try:
        return sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def run(argv):
    """Run argv with no shell. Return (returncode, stdout) or None if it cannot start."""
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def parse_json(text):
    """Return the parsed JSON, or None when text is not JSON."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def truthy_value(value):
    """jq's `//` keeps a value unless it is null or false (an empty string stays)."""
    return value is not None and value is not False


def as_text(value):
    """jq -r output for a scalar: strings raw, everything else as JSON."""
    return value if isinstance(value, str) else json.dumps(value)


def project_enabled(extra=()):
    """False only when project-status reports enabled == false; anything else reads as enabled."""
    got = run(["cactus", "project-status", *extra, "--json"])
    if got is None:
        return True
    data = parse_json(got[1])
    return not (isinstance(data, dict) and data.get("enabled") is False)


def _payload_session_id(payload_text):
    if not payload_text:
        return ""
    data = parse_json(payload_text)
    if not isinstance(data, dict):
        return ""
    value = data.get("session_id")
    return as_text(value) if truthy_value(value) else ""


def _herdr_agent(pane):
    # A conversation id is the identity on purpose: it rotates on `claude
    # --resume`, so a stale row goes unowned rather than delivered to whoever
    # sits in the pane next. c100-identity resolves the same tiers; stdout only,
    # its disagreement warning goes to stderr.
    if shutil.which("c100-identity"):
        got = run(["c100-identity", "--resolve"])
        return got[1].rstrip("\n") if got else ""
    got = run(["herdr", "agent", "get", pane])
    if got is None:
        return ""
    data = parse_json(got[1])
    try:
        agent = data["result"]["agent"]
        value = (agent.get("tokens") or {}).get("claude_session_id")
        if not truthy_value(value):
            value = (agent.get("agent_session") or {}).get("value")
    except (KeyError, TypeError, AttributeError):
        return ""
    return as_text(value) if truthy_value(value) else ""


def resolve_agent(payload_text):
    """Return the agent id, or "" when no identity resolves."""
    agent = _payload_session_id(payload_text)
    pane = os.environ.get("HERDR_PANE_ID", "")
    if not agent and pane and shutil.which("herdr"):
        agent = _herdr_agent(pane)
    if not agent:
        agent = os.environ.get("CACTUS_AGENT", "")
    return agent
