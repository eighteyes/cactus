#!/usr/bin/env bash
# session-start.sh
# Codex SessionStart hook: tell the session its cactus identity and the mod-mode rules.
# Responsibilities:
#   - exit 0 silently when cactus, jq or a session_id is missing (never break session start)
#   - announce a disabled project and stop there
#   - inside herdr, register herdr delivery so an answer prompts this pane
#   - print the --agent id, the mod-mode rules, and this session's open rows
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
# Codex's session_id is the owner id; every row this session posts carries it.
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

# A failed project-status reads as enabled: a broken check must not hide cactus.
hook_cwd=$(jq -r '.cwd // empty' <<<"$input")
enabled=$(cactus project-status --json --cwd "${hook_cwd:-$PWD}" 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
if [ "${enabled:-true}" != "true" ]; then
  printf '%s\n' "Cactus is disabled for this project. \`P\`rojects opens with Shift+P; select it and press \`A\`ctivate."
  exit 0
fi

# Codex has no idle wake, so delivery is the only push an answer gets (q462).
# Outside herdr there is no pane to prompt; registration is skipped, not faked.
# Writes only this agent's entry in the delivery map; a failure prints nothing
# and leaves the session on the frontier hook alone.
if [ -n "${HERDR_PANE_ID:-}" ]; then
  if cactus deliver herdr --agent "$agent" >/dev/null 2>&1; then
    printf '%s\n' "Cactus registered herdr delivery for $agent: answers prompt this pane."
  fi
fi

open=$(cactus list -s open --agent "$agent" 2>/dev/null || true)
# Mod mode (50938fc): Codex has no idle wake, so a waiter wakes nobody; asks post --no-wait
# and the frontier hook carries answers in on the next user turn.
printf '%s\n' "Cactus is available. Use --agent $agent for every Cactus row."
printf '%s\n' "Cactus mod mode is active: post asks and runs with --no-wait; never arm a background monitor or waiter. Codex has no native live pane or idle-session wake. The frontier hook injects the current inbox on each user turn, including full answers, and auto-clears non-persistent answered/skipped rows. When the next step needs an answer now, block in the foreground: cactus get KEY --wait --timeout 300 --json"
if [ -n "$open" ]; then
  printf '%s\n%s\n' "Open Cactus rows for this Codex session:" "$open"
fi
