# q536 — How should pane (CLI) answers drop a seed in the garden?

status: answered
act: ask
kind: choice
thread: garden
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-05T04:35:38.068169+00:00

## Context

Today a seed drops only when a TUI key answers: _field_drop in tui.py, in
that TUI's own World; landings save to the shared garden.json.
Pane, web board and agent-side answers all go through `cactus answer`.

Default if unanswered: queue.

## Files

- /Users/god/projects/cactus/src/cactus/garden.py

## Options

- queue — cactus answer adds a pending seed to garden.json; the first TUI
that sees it claims it under a file lock and drops it
+ exactly once, even with two TUIs open
+ a seed waits if no TUI is running
- a lock + a pending count in the garden file  (★◐)
- watch — every running TUI drops a seed when it sees an answer arrive
that it did not make
+ no file change
- two TUIs open = two seeds per answer (shared garden)
- no TUI running = seed lost

## Recommendation

queue — med
the garden is shared, so a seed must be dropped once, by one TUI

## Answer

queue
answered at: 2026-10-05T04:36:22.913587+00:00
