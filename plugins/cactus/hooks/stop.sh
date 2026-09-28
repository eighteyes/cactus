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
watching=$(ps -ax -o command= 2>/dev/null | awk -v id="$agent" '{for(i=1;i<NF;i++) if($i=="--agent" && $(i+1)==id){n++; break}} END{print n+0}')
if [ "${open:-0}" -gt 0 ] && [ "$watching" = "0" ]; then
  jq -nc --arg agent "$agent" --argjson open "$open" '{decision:"block",reason:("You have \($open) open Cactus row(s) and no once-loop armed. Run cactus --monitor --json --agent \($agent) --once as a background command, then continue." )}'
fi
