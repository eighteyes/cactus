#!/usr/bin/env bash
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
jq -e '.stop_hook_active != true' >/dev/null <<<"$input" || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

open=$(cactus list -s any --agent "$agent" --json 2>/dev/null \
  | jq '[.[] | select(.status == "open" or .status == "live" or .status == "elaborate")] | length' 2>/dev/null || printf '0')
watching=$(ps -ax -o command= 2>/dev/null | awk -v id="$agent" '{for(i=1;i<NF;i++) if($i=="--agent" && $(i+1)==id){n++; break}} END{print n+0}')
if [ "${open:-0}" -gt 0 ] && [ "$watching" = "0" ]; then
  jq -nc --arg agent "$agent" --argjson open "$open" '{decision:"block",reason:("You have \($open) open Cactus row(s) without a monitor. Start cactus --monitor --json --agent \($agent), then continue." )}'
fi
