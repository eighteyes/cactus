#!/usr/bin/env bash
# session-start.sh
# Inject the required cactus workflow, the agent's identity, and the project's open rows at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - open with a ready-to-run once-loop command when no monitor runs for this agent
#   - print the five-step workflow every agent follows: monitor, ask, work, act, clear
#   - resolve the --agent value through identity.sh and print it
#   - rehome rows this pane posted under a previous identity (after /clear or --resume)
#   - teach the escape: cactus run when a permission prompt blocks
#   - print the open rows for this project so an unanswered thread is not forgotten
set -u
command -v cactus >/dev/null 2>&1 || exit 0
# Read first: identity.sh takes the session id from this payload.
input=$(cat)

enabled=$(cactus project status --json 2>/dev/null \
  | jq -r 'if .enabled == false then "false" else "true" end' 2>/dev/null)
if [ "${enabled:-true}" != "true" ]; then
  printf '%s\n' "Cactus is disabled for this project. Run \`cactus project activate\` to reactivate it."
  exit 0
fi

# shellcheck source=identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/identity.sh"
agent=$(cactus_resolve_agent)

# Setup comes first: an agent with no monitor never hears its answers (q252).
if [ -n "$agent" ]; then
  watching=$(ps -ax -o command= | grep -F -- "--monitor" \
    | awk -v id="$agent" '{for(i=1;i<NF;i++) if($i=="--agent" && $(i+1)==id){n++; break}} END{print n+0}')
  if [ "$watching" = "0" ]; then
    echo "FIRST, before anything else: arm your cactus once-loop with the Bash tool in the background:"
    echo "  Bash(command=\"cactus --monitor --json --agent $agent --once\", run_in_background=true)"
    echo "It exits on the first event for your rows and wakes you, even hours later on an idle session. Re-arm it first thing on every wake, before acting. Not the Monitor tool: that dies at 30 minutes."
  else
    echo "Your cactus once-loop is armed (--agent $agent)."
  fi
else
  echo "FIRST: choose one stable --agent value for this session and arm \`cactus --monitor --json --agent <that value> --once\` with the Bash tool in the background."
fi

cat <<EOF
cactus is installed. Its workflow is required, not optional:
  1 monitor  arm \`cactus --monitor --json --agent ID --once\` with the Bash tool, run_in_background, before your first ask; --agent is required. It exits on the first event for your rows and wakes you; re-arm it first thing on every wake, then act. Never the Monitor tool: its 30-minute cap leaves the inbox deaf
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
