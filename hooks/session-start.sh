#!/usr/bin/env bash
# session-start.sh
# Inject the required cactus workflow, the agent's identity, and the project's open rows at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - print the five-step workflow every agent follows: monitor, ask, work, act, clear
#   - resolve the --agent value through identity.sh and print it
#   - rehome rows this pane posted under a previous identity (after /clear or --resume)
#   - teach the two escapes: --once when Monitor's cap expires, cactus run when a permission prompt blocks
#   - print the open rows for this project so an unanswered thread is not forgotten
set -u
command -v cactus >/dev/null 2>&1 || exit 0

# shellcheck source=identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/identity.sh"
agent=$(cactus_resolve_agent)

cat <<EOF
cactus is installed. Its workflow is required, not optional:
  1 monitor  start \`cactus --monitor --json --agent ID\` with the Monitor tool before your first ask; --agent is required. When Monitor's 30-minute cap expires, run \`cactus --monitor --json --agent ID --once\` in the background (it exits on the first event that is not asked); go back to Monitor once the user is active again
  2 ask      post every decision the human makes to \`cactus ask\`, not to chat or AskUserQuestion; one -c per direction, --recommend when you have a pick, --agent on every row
  3 work     do everything the answer does not block
  4 act      on each event as it lands: answered, elaborate (rewrite the row with \`cactus edit KEY --agent ID --context ...\`), reopened, cleared
  5 clear    your own rows, by key, once acted on
Blocked by a permission prompt? Post the command instead of stopping: \`cactus run CMD --agent ID\`. The human approves it from the TUI.
Load the cactus skill before the first ask.
EOF
if [ -n "$agent" ]; then
  echo "Your cactus identity for this session: --agent $agent"
  # A /clear or --resume rotates the conversation id. Rows this pane posted
  # under the old id are still stamped with the pane and herdr session, so
  # move them onto the new id; exit 1 (no stamps) and count 0 are both silent.
  moved=$(cactus rehome --agent "$agent" --json 2>/dev/null | jq -r '.rehomed // .count // 0' 2>/dev/null)
  if [ "${moved:-0}" != "0" ]; then
    echo "Rehomed $moved row(s) from this pane's previous identity onto --agent $agent."
  fi
else
  echo "No herdr session resolved. Choose one stable --agent value for this session and pass it on every ask and clear."
fi

open=$(cactus list -s open 2>/dev/null)
rc=$?
if [ "$rc" -eq 0 ] && [ -n "$open" ]; then
  echo "Open cactus rows in this project (collect with \`cactus get KEY --json\`):"
  echo "$open"
fi
exit 0
