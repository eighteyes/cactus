# q161 — Where do the project stubs with counts go in the TUI?

status: answered
act: ask
kind: choice
thread: frontier
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T16:42:41.843427+00:00

## Context

Today the TUI shows one project at a time and rotates only through projects with open rows. rail and grouped change the fixed 4-row rail layout.

## Options

- strip — one line under the header, 'cactus 3 · canopy 1 · lucid 2', current highlighted; [ ] still switch  (★◐)
- rail — other projects as one-line stubs in the rail below the current project's rows
- grouped — every project's rows in one rail under per-project headers, no switching

## Recommendation

strip — med
one row, never shifts the rail, keeps the fixed-height invariant

## Answer

strip
answered at: 2026-09-23T16:44:08.864135+00:00
