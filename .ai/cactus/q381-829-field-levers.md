# q381 — Field v6: what shape are the levers?

status: answered
act: steer
kind: choice
thread: field
agent: 6104f97f-6932-4d73-9242-9d2c2ddd509a
cwd: .
asked at: 2026-09-28T22:48:57.778814+00:00

## Context

File path ~/.config/cactus/sky.toml, CACTUS_SKY overrides it, and "cactus sky --dump"
writes the current defaults there to start from. Proceeding with file; the overlay can
follow once the constants settle.

## Options

- file — every sky constant in one TOML file, hot-reloaded by the running TUI every 2 s; edit, save, watch  (doing)
- keys — a tuning overlay in the TUI (T) with j/k to pick a constant and h/l to nudge it, written back to the same file
- both — the file plus the overlay

## Answer

both
answered at: 2026-09-28T22:55:42.027368+00:00
