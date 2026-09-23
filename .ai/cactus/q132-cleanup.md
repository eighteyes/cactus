# q132 — Clean up what?

status: retired
act: ask
kind: multi
thread: next
parent: q131
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:30:27.877691+00:00

## Context

Stale test fixed: test_recommend_plan.py 17/0. .ai/TODO.md is cactus-b9's untracked file. dupe and undo touch tui.py, monitor.py and store.py.

## Options

- dupe — monitor emits answered twice for a TUI steer answer (TODO finding)  (★◐)
- undo — cactus reopen cannot restore a cleared review/plan row; q121–q123 were lost (TODO finding)  (★◐)
- tmp — prune .ai/tmp throwaways, keep the test_* regression scripts
- todo — tick the stale-test item and fold .ai/TODO.md into tracked docs

## Recommendation

dupe, undo — med
both are live bugs that lose or distort decisions, which the records now make permanent

## Answer

dupe, tmp, todo, undo
answered at: 2026-09-23T04:32:48.431398+00:00
