# q450 — Which cactus mod shape first?

status: answered
act: ask
kind: multi
thread: mod
agent: 362c090b-e4f1-42bc-99a1-8936f5cd4f74
cwd: .
asked at: 2026-10-02T15:52:27.584753+00:00

## Context

Mod = Claude Code plugin of function hooks, hot-reloads this session.
All read via `cactus feed --json --here` on a timer ($.clock + $.process).

Default if unanswered: status + band, scoped to this session agent.

## Options

- status — status line "cactus 3 open · 1 answered"
+ tiny, always visible
- counts only, no text  (★◐)
- band — row above prompt naming answered rows to pick up
+ shows what woke, by key and verdict
- eats a line when busy  (★◐)
- pane — live side pane, inbox with answer buttons
+ answer without leaving Claude Code
- needs 144 cols unasked; dupes the TUI
- gate — hook refusing turn end with unread answers
+ agent never misses a verdict
- overlaps the Stop hook already shipped

## Recommendation

status, band — med
cheapest visible win; pane duplicates the TUI

## Answer

pane
answered at: 2026-10-02T15:53:35.982082+00:00
