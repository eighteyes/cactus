# q334 — Which stop hook goes off-by-default?

status: answered
act: ask
kind: choice
thread: stop-hook
agent: 975d7f07-aec8-4df7-bc84-5495c430bdfd
cwd: .
asked at: 2026-09-27T19:03:49.296928+00:00

## Context

Both are registered in their hooks.json under Stop right now.

## Options

- claude — hooks/stop-fork.sh — blocks a turn that ends with no cactus ask, and blocks when there are open rows but no monitor
- codex — plugins/cactus/hooks/stop.sh — the open-rows-without-a-monitor check only
- both

## Answer

both
answered at: 2026-09-27T19:03:54.445219+00:00
