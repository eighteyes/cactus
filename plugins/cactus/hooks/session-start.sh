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
if [ "${enabled:-true}" != "true" ]; then
  printf '%s\n' "Cactus is disabled for this project. \`P\`rojects opens with Shift+P; select it and press \`A\`ctivate."
  exit 0
fi

if [ -n "${HERDR_PANE_ID:-}" ]; then
  if cactus deliver herdr --agent "$agent" >/dev/null 2>&1; then
    printf '%s\n' "Cactus registered herdr delivery for $agent: answers prompt this pane."
  fi
fi

open=$(cactus list -s open --agent "$agent" 2>/dev/null || true)
printf '%s\n' "Cactus is available. Use --agent $agent for every Cactus row."
printf '%s\n' "Cactus mod mode is active: post asks and runs with --no-wait; never arm a background monitor or waiter. Codex has no native live pane or idle-session wake. The frontier hook injects the current inbox on each user turn, including full answers, and auto-clears non-persistent answered/skipped rows. When the next step needs an answer now, block in the foreground: cactus get KEY --wait --timeout 300 --json"
if [ -n "$open" ]; then
  printf '%s\n%s\n' "Open Cactus rows for this Codex session:" "$open"
fi
