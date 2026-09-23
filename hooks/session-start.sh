#!/usr/bin/env bash
# session-start.sh
# Inject a cactus nudge and the project's open-question count at session start.
# Responsibilities:
#   - stay silent when cactus is not installed
#   - print one line telling the agent cactus exists and when to use it
#   - print the open rows for this project so an unanswered thread is not forgotten
set -u
command -v cactus >/dev/null 2>&1 || exit 0

open=$(cactus list -s open 2>/dev/null)
rc=$?

echo "cactus is installed: post questions with \`cactus ask\` and keep working instead of blocking on AskUserQuestion. Load the cactus skill before the first ask; \`cactus --agent-help\` has the syntax."
if [ "$rc" -eq 0 ] && [ -n "$open" ]; then
  echo "Open cactus rows in this project (collect with \`cactus get KEY --json\`):"
  echo "$open"
fi
exit 0
