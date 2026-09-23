#!/usr/bin/env bash
# session-start.sh
# Inject the required cactus workflow, the agent's identity, and the project's open rows at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - print the five-step workflow every agent follows: monitor, ask, work, act, clear
#   - resolve the --agent value through identity.sh and print it
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
  4 act      on each event as it lands: answered, reopened, cleared
  5 clear    your own rows, by key, once acted on
Blocked by a permission prompt? Post the command instead of stopping: \`cactus run CMD --agent ID\`. The human approves it from the TUI.
Load the cactus skill before the first ask.
EOF
if [ -n "$agent" ]; then
  echo "Your cactus identity for this session: --agent $agent"
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
