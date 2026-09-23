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

echo "cactus is installed. Use it for forks, reviews and questions: a fork is \`cactus ask\` with one -c per direction (\`--act steer --chosen\` when one is the default), a review is \`--act review\` plus \`cactus review KEY --run ... --pass ...\`, a question is \`cactus ask\` posted now and collected at the fork. Keep working instead of blocking on AskUserQuestion; load the cactus skill before the first ask."
if [ "$rc" -eq 0 ] && [ -n "$open" ]; then
  echo "Open cactus rows in this project (collect with \`cactus get KEY --json\`):"
  echo "$open"
fi
exit 0
