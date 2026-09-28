#!/usr/bin/env bash
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

hook_cwd=$(jq -r '.cwd // empty' <<<"$input")
enabled=$(cactus project-status --json --cwd "${hook_cwd:-$PWD}" 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
[ "${enabled:-true}" = "true" ] || exit 0

rows=$(cactus list -s any --agent "$agent" --json 2>/dev/null) || exit 0
[ -n "$rows" ] || exit 0
jq -r --arg agent "$agent" '
  [ .[] | select(.status == "elaborate") ] as $elaborate |
  [ .[] | select(.status == "answered") ] as $answered |
  [ .[] | select(.status == "open" or .status == "live") ] as $open |
  ($elaborate + $answered + $open) as $all |
  if ($all | length) == 0 then empty else
    "cactus frontier (--agent \($agent)):",
    ($all[:5][] | "  \(.key) \(.status) \(.word // (.text | .[0:60]))"),
    "  \($elaborate | length) to elaborate, \($answered | length) answered to act on and clear, \($open | length) open",
    (if ($open | length) > 0 then "  Codex has no wake-up from idle: answers surface here on your next turn. If the next step needs one now, block: cactus get KEY --wait --timeout 300 --json" else empty end)
  end
' <<<"$rows"
