# q429 — Uncommitted edits in tui/poke/cli/monitor/hooks: whose, and can I build on them?

status: answered
act: ask
kind: choice
thread: decider
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-01T20:37:01.327059+00:00

## Context

8 test_tui failures: tui.py imports poke_webhook_if_mapped, gone from
poke.py. 2 more expect wait-by-default text. Not from this task.
Done and green on my side: rank.py, decide.py, store auto_* columns.
Default if unanswered: wait.

## Options

- build-on — they are yours/finished; I edit tui.py on top, commit only my hunks
+ no waiting
- my commit sits on a half-staged tree
- wait — another agent is mid-edit; I hold the TUI step until it commits
+ no collisions
- TUI work stalls

## Answer

build-on
answered at: 2026-10-01T22:14:50.695999+00:00
