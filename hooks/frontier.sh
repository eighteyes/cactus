#!/usr/bin/env bash
# frontier.sh
# UserPromptSubmit hook: inject this agent's cactus frontier as context on every prompt.
# Responsibilities:
#   - stay silent when cactus is not installed, no identity resolves, or the agent has no rows
#   - list the agent's rows awaiting elaboration first, then answered-but-not-cleared (acted-on backlog), then open
#   - cap the listing at FRONTIER_MAX rows, key and gist each, and close with one counts line
set -u
command -v cactus >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
# Read first: identity.sh takes the session id from this payload.
input=$(cat)

enabled=$(cactus project-status --json 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
[ "${enabled:-true}" = "true" ] || exit 0

# shellcheck source=identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/identity.sh"
agent=$(cactus_resolve_agent)
[ -n "$agent" ] || exit 0

FRONTIER_MAX="${CACTUS_FRONTIER_MAX:-5}"

rows=$(cactus list -s any --agent "$agent" --json 2>/dev/null) || exit 0
[ -n "$rows" ] || exit 0

# Gist: --word when set, else the first 60 characters of the question.
# Answered rows carry their verdict so the agent can act without a get.
jq -r --argjson max "$FRONTIER_MAX" '
  def gist: (.word // (.text | .[0:60]));
  def verdict:
    if .answer == null then ""
    elif .answer.skipped then " -> skipped"
    else " -> " + ((.answer.selected // []) | join(",")) + (if .answer.text then " " + (.answer.text | .[0:40]) else "" end)
    end;
  def hint: if .status == "elaborate" then " " + (.elaborate // "(eli5)") else "" end;
  [ .[] | select(.status == "elaborate") ] as $more
  | [ .[] | select(.status == "answered") ] as $done
  | [ .[] | select(.status == "open" or .status == "live") ] as $open
  | (($more | length) + ($done | length) + ($open | length)) as $total
  | if $total == 0 then empty else
      "cactus frontier (--agent \($agent)):",
      ( ($more + $done + $open)[:$max][]
        | "  \(.key) \(.status)\(hint) \(gist)\(verdict)" ),
      (if $total > $max then "  ... \($total - $max) more: cactus list -s any --agent \($agent)" else empty end),
      "  \($more | length) to elaborate (cactus edit KEY --agent ID --context ...), \($done | length) answered to act on and clear, \($open | length) open"
    end
' --arg agent "$agent" <<<"$rows"
exit 0
