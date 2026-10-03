# q456 — Pane parity: add the 4 missing CLI verbs first?

status: answered
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T18:16:58.772303+00:00

## Context

Scope: row keys only. No project keys, answers view, sky, garden, settings, or v visit.

Already in the CLI, mapped in the pane:
  1-9 pick, y/n, s skip, i/enter text, c/x clear, d dismiss,
  plan step ticks (plan --done/--undone), p poke, f/o file view.

Not in the CLI (the TUI calls Store directly):
  e elaborate, D decompose, u undo of an answer, R run result.

Default if unanswered: cli. Plan grade: B.

## Files

- /Users/god/ai/mods/cactus-pane/hooks/register.tsx
- /Users/god/projects/cactus/src/cactus/cli.py

## Options

- cli — add the verbs to cactus, then full pane parity
+ every TUI key works in the pane
+ CLI stays the only validator
- touches cli.py/store + tests in this repo  (★◐)
- pane — parity with today's CLI only, gaps greyed out
+ mod-only, no repo change
- no e/D, no undo of an answer, R runs but loses result

## Recommendation

cli — med
keeps cli.py the only validator; pane stays thin

## Answer

cli
answered at: 2026-10-02T18:32:10.662129+00:00
