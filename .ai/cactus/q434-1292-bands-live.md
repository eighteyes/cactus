# q434 — Bands after restarting the TUI at fps 30: do you see them change?

status: answered
act: ask
kind: choice
thread: sky
agent: 275c9c71-be9e-42e8-a2ed-98fbafe29278
cwd: .
asked at: 2026-10-01T22:36:23.579627+00:00

## Context

Your sky.toml was last written by pre-67b6906 code (no band_evolve line, '16-step' comment), and fps fell back to 6. Restart: q, then cactus --tui; T, engine panel, fps 30; clouds panel band_evolve 5 to check it churns within a minute.

## Options

- yes — they evolve; leave band_evolve where it feels right  (★◐)
- faint — they change but too subtly; raise the default band_evolve
- no — still static after a restart; I dig in with a live probe

## Recommendation

yes — med
sky.toml shows the running TUI predates 67b6906

## Answer

faint
answered at: 2026-10-01T22:41:59.176930+00:00
