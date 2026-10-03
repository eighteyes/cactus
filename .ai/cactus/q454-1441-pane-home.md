# q454 — Where should cactus-pane live so it survives restarts?

status: skipped
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T18:14:09.148691+00:00

## Context

dev-mods is keyed by session id; the fork to e76df619 dropped it (your N).
Copied it to this session's folder; 4 tests pass. Enable hot reload when asked, then /cactus-pane.

Default if unanswered: repo.

## Options

- repo — commit it under mods/cactus-pane in this repo
+ versioned with cactus, ships beside the plugin
- needs --plugin-dir or a plugin.json entry to load  (★◐)
- devmods — keep copying into each session's dev-mods folder
+ hot reload while iterating
- lost on every new session or fork, like just now

## Recommendation

repo — med
dev-mods is per-session; this already bit once

## Answer

skipped
answered at: 2026-10-02T18:15:11.897143+00:00
