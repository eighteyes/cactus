#!/usr/bin/env bash
set -u

# Opt-in: off unless CACTUS_STOP_HOOK=1.
[ "${CACTUS_STOP_HOOK:-}" = "1" ] || exit 0
input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
jq -e '.stop_hook_active != true' >/dev/null <<<"$input" || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

hook_cwd=$(jq -r '.cwd // empty' <<<"$input")
enabled=$(cactus project-status --json --cwd "${hook_cwd:-$PWD}" 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
[ "${enabled:-true}" = "true" ] || exit 0

open=$(cactus list -s any --agent "$agent" --json 2>/dev/null \
  | jq '[.[] | select(.status == "open" or .status == "live" or .status == "elaborate")] | length' 2>/dev/null || printf '0')
# Codex has no wake-up from idle (q342), so there is no monitor to demand and
# a block here would repeat on every stop. Open rows are the normal state
# between turns: the frontier hook lists them on the next prompt.
[ "${open:-0}" -gt 0 ] || exit 0
exit 0
