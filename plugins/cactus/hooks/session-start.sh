#!/usr/bin/env bash
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

open=$(cactus list -s open --agent "$agent" 2>/dev/null || true)
printf '%s\n' "Cactus is available. Use --agent $agent for every Cactus row."
printf '%s\n' "Before the first ask, start: cactus --monitor --json --agent $agent"
if [ -n "$open" ]; then
  printf '%s\n%s\n' "Open Cactus rows for this Codex session:" "$open"
fi
