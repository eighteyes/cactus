# q133 — Fix the two new overwrite bugs from the user-monkey pass?

status: retired
act: ask
kind: multi
thread: next
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:41:36.060924+00:00

## Context

Found by cactus-b9's read-only pass (.ai/tests/user-monkey-cactus-cli.md, 41 surprises). Both are in store.py, next to the current undo fix; they queue behind it. The other 39 surprises are untriaged.

## Options

- plansteps — plan --step replaces every step and carries a stale done flag onto the new list  (★●)
- reviewwipe — a second cactus review --pass wipes --run set by the first call  (★●)

## Recommendation

plansteps, reviewwipe — high
both silently lose data the human already saw, and records now persist it

## Answer

plansteps, reviewwipe
answered at: 2026-09-23T04:54:50.554630+00:00
