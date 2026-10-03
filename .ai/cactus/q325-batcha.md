# q325 — Commit the hint-row work, or leave it in the tree?

status: answered
act: ask
kind: choice
agent: orc2-patches
cwd: .
asked at: 2026-09-26T06:16:30.530725+00:00

## Context

Branch cactus-v1 already has someone else's work in flight: store.py staged, cli.py staged+dirty. My change is tui.py only. Committing tui.py alone leaves their staged store.py untouched but interleaves history.

## Options

- commit tui.py only — leave their staged work alone
- leave it dirty — you or the other agent commits it  (★◐)
- new branch — branch off and commit there

## Recommendation

leave it dirty — med
another agent is mid-work on this branch; interleaving is their call not mine

## Answer

leave it dirty
answered at: 2026-09-26T06:19:25.436715+00:00
