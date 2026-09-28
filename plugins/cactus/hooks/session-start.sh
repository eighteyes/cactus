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

open=$(cactus list -s open --agent "$agent" 2>/dev/null || true)
printf '%s\n' "Cactus is available. Use --agent $agent for every Cactus row."
printf '%s\n' "Before the first ask, arm the once-loop as a background command: cactus --monitor --json --agent $agent --once"
printf '%s\n' "It exits on the first event for your rows and wakes you. Re-arm it first thing on every wake, then act. Never run it in the foreground."
if [ -n "$open" ]; then
  printf '%s\n%s\n' "Open Cactus rows for this Codex session:" "$open"
fi
