# q459 — get --wait on review/steer rows: support it, or fix the text that says to?

status: answered
act: ask
kind: choice
thread: wait
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-02T18:54:43.436065+00:00

## Context

Today `cactus get q36 --wait` on a review row raises a raw ValueError
traceback telling you to "watch the monitor stream". The monitor workflow
is gone. The stop-fork hook and CLAUDE.md say "collect those with one
backgrounded cactus get KEY... --wait". Both options also remove the
traceback. Separate: agent-help gets a line that a fresh review is
`ask --act review` (cactus review KEY only updates). Default: refuse.

## Options

- support — get --wait on non-blocking rows returns on the next verdict or status change
+ matches the stop hook and CLAUDE.md (q430)
+ agents can wake on a review verdict
- changes the wait_for_answer contract  (★◐)
- refuse — keep the refusal, exit 1 one-line (no traceback), fix the hook + CLAUDE.md text to say the next-turn frontier collects them
+ smallest change
- no wake for review verdicts

## Recommendation

support — med
the q430 docs already promise it; ai-51 hit the gap today

## Answer

support
answered at: 2026-10-02T20:43:13.521479+00:00
