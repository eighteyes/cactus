#!/usr/bin/env bash
set -u

input=$(cat)
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
agent=$(jq -r '.session_id // empty' <<<"$input")
[ -n "$agent" ] || exit 0

rows=$(cactus list -s any --agent "$agent" --json 2>/dev/null) || exit 0
[ -n "$rows" ] || exit 0
watching=$(ps -ax -o command= 2>/dev/null | awk -v id="$agent" '{for(i=1;i<NF;i++) if($i=="--agent" && $(i+1)==id){n++; break}} END{print n+0}')
jq -r --arg agent "$agent" --arg watching "$watching" '
  [ .[] | select(.status == "elaborate") ] as $elaborate |
  [ .[] | select(.status == "answered") ] as $answered |
  [ .[] | select(.status == "open" or .status == "live") ] as $open |
  ($elaborate + $answered + $open) as $all |
  if ($all | length) == 0 then empty else
    "cactus frontier (--agent \($agent)):",
    ($all[:5][] | "  \(.key) \(.status) \(.word // (.text | .[0:60]))"),
    "  \($elaborate | length) to elaborate, \($answered | length) answered to act on and clear, \($open | length) open",
    (if (($elaborate | length) + ($open | length)) > 0 and $watching == "0" then "  no monitor is running: cactus --monitor --json --agent \($agent)" else empty end)
  end
' <<<"$rows"
