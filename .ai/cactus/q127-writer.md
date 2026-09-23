# q127 — Who writes the decision record?

status: retired
act: ask
kind: choice
thread: decisionlog
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:14:04.231475+00:00

## Context

store means the TUI process writes into <project>/.ai/cactus/ using the row's recorded project root, even when the TUI runs from elsewhere. It fails soft (warn, keep the answer) if the directory is not writable.

## Options

- store — cactus writes it on every answer, from any surface  (★◐)
- agent — the asking agent writes it when it acts on the answer
- verb — cactus log KEY, called by the agent; also backfills

## Recommendation

store — med
the only option that cannot be forgotten; agents already skip steps

## Answer

store
answered at: 2026-09-23T04:14:34.570964+00:00
