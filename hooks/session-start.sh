#!/usr/bin/env bash
# session-start.sh
# Inject the required cactus workflow, the agent's identity, and the project's open rows at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - print the workflow every agent follows: ask, wait (backgrounded), work, inspect, clear
#   - resolve the --agent value through identity.sh and print it
#   - rehome rows this pane posted under a previous identity (after /clear or --resume)
#   - teach the escape: wait on the denied hook's cactus run row, post one only when none exists
#   - print the open rows for this project so an unanswered thread is not forgotten
set -u
command -v cactus >/dev/null 2>&1 || exit 0
# Read first: identity.sh takes the session id from this payload.
input=$(cat)

enabled=$(cactus project-status --json 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
if [ "${enabled:-true}" != "true" ]; then
  printf '%s\n' "Cactus is disabled for this project. Run \`cactus project activate\` to reactivate it."
  exit 0
fi

# shellcheck source=identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/identity.sh"
agent=$(cactus_resolve_agent)

cat <<EOF
cactus is installed. Its workflow is required, not optional:
  1 ask      post every decision the human makes to \`cactus ask\`, not to chat or AskUserQuestion; one -c per direction, --recommend LABEL --confidence L when you have a pick, -f for every file the question is about, --agent on every row
  2 wait     a blocking ask (ask, run) waits for the human by default. Post it as ONE backgrounded command (Bash run_in_background); its exit is your wake-up. No monitor. --no-wait posts and returns; steer/notify/review/plan/data never wait
  2b work    do everything the answer does not block while it waits
  3 inspect  on your next turn, the frontier lists answered/elaborated rows. Read every review/plan row with \`cactus get KEY --agent ID\` (that tells the human you heard); after acting on its verdict, respond with \`cactus plan|review|edit KEY --agent ID\`
  4 clear    your own rows, by key, once acted on
Blocked by a permission prompt? Do not stop. In auto mode the PermissionDenied hook already posted the command as a \`cactus run\` row in thread denied: find it with \`cactus list -s open -t denied --agent ID\` and wait on it with one backgrounded \`cactus get KEY --wait --agent ID\`. Post \`cactus run CMD --agent ID\` (backgrounded) yourself only when no such row exists. The human approves it from the TUI.
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
  echo "Open cactus rows in this project (collect with \`cactus get KEY --agent ID --json\`):"
  echo "$open"
fi
exit 0
