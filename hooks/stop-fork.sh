#!/usr/bin/env bash
# stop-fork.sh
# Stop hook that blocks a turn from ending without posting its next fork to cactus.
# Responsibilities:
#   - stay silent (exit 0) unless CACTUS_STOP_HOOK=1 (opt-in)
#   - stay silent (exit 0) when cactus is not installed or stop_hook_active is true
#   - find the current turn: everything after the last transcript entry that
#     opened it (a genuine human prompt, a task-notification, or a
#     cross-session message), skipping tool_result rows and interruption
#     markers along the way
#   - exempt turns opened by a task-notification or cross-session message,
#     since those are background events, not a human handing off a decision
#   - block (exit 0, emit {"decision":"block","reason":...}) unless the turn
#     already contains a Bash `cactus ask`/`cac ask` invocation or an
#     AskUserQuestion tool_use
#
#   - block when the agent has open rows and no monitor process (q252)
#
# Read-only: one `cactus list` for the agent's open rows; never writes.
set -u

# Opt-in: off unless CACTUS_STOP_HOOK=1.
[ "${CACTUS_STOP_HOOK:-}" = "1" ] || exit 0
command -v cactus >/dev/null 2>&1 || exit 0

input=$(cat)

enabled=$(cactus project status --json 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
[ "${enabled:-true}" = "true" ] || exit 0

# Monitor check (q252): an agent with open rows and no monitor never hears the
# answers. Read-only: one `cactus list` and a process scan.
# shellcheck source=identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/identity.sh"
CACTUS_ID=$(cactus_resolve_agent 2>/dev/null)
CACTUS_OPEN=0
CACTUS_WATCHING=1
if [ -n "$CACTUS_ID" ] && command -v jq >/dev/null 2>&1; then
  CACTUS_OPEN=$(cactus list -s any --agent "$CACTUS_ID" --json 2>/dev/null \
    | jq '[.[] | select(.status == "open" or .status == "live" or .status == "elaborate")] | length' 2>/dev/null)
  CACTUS_WATCHING=$(ps -ax -o command= | grep -F -- "--monitor" \
    | awk -v id="$CACTUS_ID" '{for(i=1;i<NF;i++) if($i=="--agent" && $(i+1)==id){n++; break}} END{print n+0}')
fi
export CACTUS_ID CACTUS_OPEN="${CACTUS_OPEN:-0}" CACTUS_WATCHING

python3 - "$input" <<'PYEOF'
import json
import sys

raw = sys.argv[1]
try:
    hook_input = json.loads(raw)
except Exception:
    sys.exit(0)

if hook_input.get("stop_hook_active"):
    sys.exit(0)

# Checked before the fork rule and on every turn, background ones included:
# a --once waiter that has fired leaves the agent with no monitor at all.
import os
open_rows = int(os.environ.get("CACTUS_OPEN") or 0)
if open_rows > 0 and os.environ.get("CACTUS_WATCHING") == "0":
    agent = os.environ.get("CACTUS_ID", "ID")
    print(json.dumps({"decision": "block", "reason": (
        f"you have {open_rows} open cactus row(s) and no once-loop armed; run "
        f"Bash(command=\"cactus --monitor --json --agent {agent} --once\", "
        "run_in_background=true) now, then stop"
    )}))
    sys.exit(0)

transcript_path = hook_input.get("transcript_path")
if not transcript_path:
    sys.exit(0)

try:
    with open(transcript_path, "r") as f:
        lines = f.readlines()
except OSError:
    sys.exit(0)

# Walk the transcript from the end. Each user-type row is one of:
#   - a tool_result row (message.content is a list of tool_result items) ->
#     part of the ongoing turn, keep scanning backward
#   - an interruption marker (has "interruptedMessageId", or its text is
#     literally "[Request interrupted by user]") -> not a real prompt, keep
#     scanning backward past it
#   - a meta injection (isMeta true, e.g. a Skill's "Base directory for this
#     skill:" header) other than a cross-session message -> not a turn
#     opener, keep scanning backward
#   - a cross-session message (isMeta true, content is a string that starts
#     "Another Claude session sent a message:" and embeds
#     <cross-session-message ...>) -> opens the turn, but not a human prompt
#   - a task-notification (content is a string starting "<task-notification>")
#     -> opens the turn, but not a human prompt
#   - anything else -> a genuine human prompt, opens the turn

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


boundary_idx = None
boundary_kind = None  # "human", "task_notification", "cross_session"

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
        boundary_idx = idx
        boundary_kind = "cross_session"
        break
    if is_meta:
        # other meta injections (skill headers, command wrappers, etc.) are
        # not turn openers; keep looking further back
        continue
    if stripped.startswith("<task-notification>"):
        boundary_idx = idx
        boundary_kind = "task_notification"
        break

    boundary_idx = idx
    boundary_kind = "human"
    break

if boundary_kind in ("task_notification", "cross_session"):
    sys.exit(0)

start = (boundary_idx + 1) if boundary_idx is not None else 0

has_ask = False
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
            has_ask = True
            break
        if name == "Bash":
            command = item.get("input", {}).get("command", "")
            if "cactus ask" in command or "cac ask" in command:
                has_ask = True
                break
    if has_ask:
        break

if has_ask:
    sys.exit(0)

reason = (
    "the turn ended without a fork; post the next directions as one "
    "`cactus ask` with 2-3 `-c` options (or `--act steer --chosen` when one "
    "is the default), `--agent` required, `--recommend` + `--confidence` "
    "when there is a pick; keep `cactus --monitor --json --agent ID` running so "
    "the answer reaches you; then stop"
)
print(json.dumps({"decision": "block", "reason": reason}))
sys.exit(0)
PYEOF
