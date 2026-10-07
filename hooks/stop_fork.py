#!/usr/bin/env python3
# stop_fork.py
# Stop hook that blocks a turn from ending without posting its next fork to cactus.
# Responsibilities:
#   - stay silent (exit 0) when CACTUS_STOP_HOOK=0 (on by default, q411)
#   - stay silent (exit 0) when cactus is not installed or stop_hook_active is true
#   - find the current turn: everything after the last transcript entry that
#     opened it (a genuine human prompt, a task-notification, or a
#     cross-session message), skipping tool_result rows and interruption
#     markers along the way
#   - exempt turns opened by a task-notification or cross-session message,
#     since those are background events, not a human handing off a decision
#   - stay silent while the agent already has an open row in this project
#     (q469): a fork is waiting on the human, so there is nothing to post.
#     live and elaborate do not count: a standing plan/review would mute
#     the hook for good, and an elaborate row waits on the agent, not the human
#   - block (exit 0, emit {"decision":"block","reason":...}) unless the turn
#     already contains a Bash cactus ask|edit|plan|review (or cac) invocation or an
#     AskUserQuestion tool_use
# Python 3 stdlib only; calls the cactus CLI by argv.
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cactus_identity as ident  # noqa: E402

REASON = (
    "the turn ended without a fork; post the next directions as one "
    "\x60cactus ask\x60 with 2-3 \x60-c\x60 options (or \x60--act steer --chosen\x60 when one "
    "is the default), \x60--agent\x60 required, \x60--recommend\x60 + \x60--confidence\x60 "
    "when there is a pick; post it backgrounded, its exit wakes you (steer/notify/plan/review never wait); then stop"
)


def is_tool_result(content):
    if isinstance(content, list):
        return any(isinstance(i, dict) and i.get("type") == "tool_result" for i in content)
    return False


def as_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text", "")
    return ""


def turn_boundary(lines):
    """Walk the transcript from the end. Each user-type row is one of:
      - a tool_result row (message.content is a list of tool_result items) ->
        part of the ongoing turn, keep scanning backward
      - an interruption marker (has "interruptedMessageId", or its text is
        literally "[Request interrupted by user]") -> not a real prompt, keep
        scanning backward past it
      - a meta injection (isMeta true, e.g. a Skill's "Base directory for this
        skill:" header) other than a cross-session message -> not a turn
        opener, keep scanning backward
      - a cross-session message (isMeta true, content is a string that starts
        "Another Claude session sent a message:" and embeds
        <cross-session-message ...>) -> opens the turn, but not a human prompt
      - a task-notification (content is a string starting "<task-notification>")
        -> opens the turn, but not a human prompt
      - anything else -> a genuine human prompt, opens the turn
    Returns (index, kind) with kind "human", "task_notification" or "cross_session".
    """
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "user":
            continue

        message = entry.get("message", {})
        content = message.get("content")

        if is_tool_result(content):
            continue
        if "interruptedMessageId" in entry:
            continue
        text = as_text(content)
        if text.strip() == "[Request interrupted by user]":
            continue

        is_meta = entry.get("isMeta") is True
        stripped = text.lstrip()

        if is_meta and text.startswith("Another Claude session sent a message:") and "<cross-session-message" in text:
            return idx, "cross_session"
        if is_meta:
            # other meta injections (skill headers, command wrappers, etc.) are
            # not turn openers; keep looking further back
            continue
        if stripped.startswith("<task-notification>"):
            return idx, "task_notification"
        return idx, "human"
    return None, None


def turn_has_fork(lines, start):
    for idx in range(start, len(lines)):
        line = lines[idx].strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = item.get("name")
            if name == "AskUserQuestion":
                return True
            if name == "Bash":
                command = item.get("input", {}).get("command", "")
                # Substring match, not a parse: cac is the user's alias, and
                # the call text anywhere (an echo, a heredoc) counts. MCP
                # cactus_* tool calls do not count; that route blocks.
                if any(f"{b} {v}" in command for b in ("cactus", "cac") for v in ("ask", "edit", "plan", "review")):
                    return True
    return False


def main():
    # On by default (q411); CACTUS_STOP_HOOK=0 opts out.
    if os.environ.get("CACTUS_STOP_HOOK", "1") == "0":
        return 0
    if not shutil.which("cactus"):
        return 0

    raw = ident.read_stdin()

    # No --cwd: the project is the hook process's cwd, which Claude Code sets to
    # the session's. A disabled project never blocks.
    if not ident.project_enabled():
        return 0

    agent = ident.resolve_agent(raw)
    # q469 silence needs an identity. "Hook blocks although I have an open row":
    # check the resolved agent matches the row's owner (cactus get KEY --json),
    # and that the row is in this project; list scopes to the cwd's project.
    if agent:
        got = ident.run(["cactus", "list", "-s", "open", "--agent", agent, "--json"])
        rows = ident.parse_json(got[1]) if got else None
        if isinstance(rows, (list, dict)) and len(rows) > 0:
            return 0

    try:
        hook_input = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(hook_input, dict):
        return 0

    # Set when this Stop already blocked once; blocking again loops the turn.
    if hook_input.get("stop_hook_active"):
        return 0

    transcript_path = hook_input.get("transcript_path")
    if not transcript_path:
        return 0

    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return 0

    boundary_idx, boundary_kind = turn_boundary(lines)
    if boundary_kind in ("task_notification", "cross_session"):
        return 0

    start = (boundary_idx + 1) if boundary_idx is not None else 0
    if turn_has_fork(lines, start):
        return 0

    # CONTRACT: the block is this JSON on stdout with exit 0; every other path
    # above exits 0 with no output, which lets the turn end.
    print(json.dumps({"decision": "block", "reason": REASON}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
