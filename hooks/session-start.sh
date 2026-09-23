#!/usr/bin/env bash
# session-start.sh
# Inject the required cactus workflow, the agent's identity, and the project's open rows at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - print the five-step workflow every agent follows: monitor, ask, work, act, clear
#   - resolve this pane's claude session token through herdr and print the --agent value to pass
#   - print the open rows for this project so an unanswered thread is not forgotten
set -u
command -v cactus >/dev/null 2>&1 || exit 0

agent=""
if [ -n "${HERDR_PANE_ID:-}" ] && command -v herdr >/dev/null 2>&1; then
  # The pane's declared claude session token, else herdr's own session value.
  # A conversation id is the identity on purpose: it rotates on `claude
  # --resume`, so a stale row goes unowned rather than delivered to whoever
  # sits in the pane next. c100-identity resolves the same tiers; stdout only,
  # its disagreement warning goes to stderr.
  if command -v c100-identity >/dev/null 2>&1; then
    agent=$(c100-identity --resolve 2>/dev/null)
  else
    agent=$(herdr agent get "$HERDR_PANE_ID" 2>/dev/null \
      | jq -r '.result.agent | (.tokens.claude_session_id // .agent_session.value) // empty' 2>/dev/null)
  fi
fi
if [ -z "$agent" ] && [ -n "${CACTUS_AGENT:-}" ]; then
  agent="$CACTUS_AGENT"
fi

cat <<EOF
cactus is installed. Its workflow is required, not optional:
  1 monitor  start \`cactus --monitor --json\` in the background before your first ask; keep it running while any row of yours is open
  2 ask      post every decision the human makes to \`cactus ask\`, not to chat or AskUserQuestion; one -c per direction, --recommend when you have a pick, --agent on every row
  3 work     do everything the answer does not block
  4 act      on each event as it lands: answered, reopened, cleared
  5 clear    your own rows, by key, once acted on
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
