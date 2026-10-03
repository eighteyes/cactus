# q313 — New project arrives on the board: how should the TUI surface it?

status: answered
act: ask
kind: choice
thread: macapp
agent: dd7e2c75-9a5e-4984-aa99-920e53797a41
cwd: .
asked at: 2026-09-25T20:36:46.429140+00:00

## Context

Probe on a DB backup: a fresh TUI does reach Patches:q1 via ], so the row is on the board. Order today is open_count desc, live_count desc, last_activity desc, and ten projects hold one open row each, so a new project can sit nine taps away with no signal. Nothing announces an arrival outside the current project; the header only counts others. Default if unanswered: both.

## Options

- newest-first — rotation order becomes newest arrival first, so one ] reaches it
- flash-jump — keep order, flash 'new: Patches' in the status bar and bind a key that jumps to the newest project
- both — newest-first order plus the flash  (★◐)

## Recommendation

both — med
order fixes the hunt, flash fixes the not-knowing

## Answer

newest-first
answered at: 2026-09-25T21:52:35.095737+00:00
