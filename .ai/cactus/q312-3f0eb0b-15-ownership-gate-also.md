# q312 — 3f0eb0b (#15 ownership gate) also swept in another agent's uncommitted long-question warning in cli.py. Split it out?

status: answered
act: ask
kind: choice
thread: user-monkey
agent: patches-um
cwd: .
asked at: 2026-09-25T19:42:59.522875+00:00

## Context

Not pushed. HEAD is local-only. The warning adds _warn_long_question (80 cols, 3 lines) to cli.py.

## Options

- split — soft-reset, recommit #15 only, leave the warning uncommitted for its owner  (★●)
- keep — leave the warning in 3f0eb0b

## Recommendation

split — high

## Answer

split
answered at: 2026-09-25T19:45:18.664449+00:00
