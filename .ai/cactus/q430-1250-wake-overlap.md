# q430 — Push wake and wait-by-default both landed: keep which?

status: answered
act: ask
kind: choice
thread: no-monitor
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T20:41:55.669002+00:00

## Context

Another session committed bfeb844/b75bacc (blocking asks wait by default; PreToolUse refuses a foreground wait) while I built push (c3db875, your q413 pick).

The backgrounded ask exits on answer and wakes the agent; push also prompts the pane. Same answer, two wakes.

Default if unanswered: both.

## Files

- /Users/god/projects/cactus/hooks/pretooluse-wait.sh
- /Users/god/projects/cactus/src/cactus/poke.py

## Options

- both — keep c3db875 push and bfeb844 wait-by-default
+ wakes even outside herdr with no extra step
- herdr agents get two wakes per answer
- push-only — revert bfeb844 + b75bacc (ask returns at once again)
+ one wake, no PreToolUse guard
- non-herdr agents must arm the once-loop  (★○)
- wait-only — revert c3db875 push (keep docs cleanup)
+ one mechanism everywhere
- every blocking ask must be backgrounded

## Recommendation

push-only — low
one wake per answer; you picked push in q413

## Answer

wait-only
answered at: 2026-10-01T22:16:44.088431+00:00
