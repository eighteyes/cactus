# q332 — Path handling at ask time?

status: answered
act: steer
kind: choice
thread: file
agent: 433c9778-c5d1-4246-a98e-904c8b772309
cwd: .
asked at: 2026-09-27T18:45:14.896083+00:00

## Context

The TUI runs from any directory, so a relative path stored verbatim only
works if the TUI joins it to the row's cwd. Absolute at ask time is what --run
already assumes. Refusing a missing file matches the other ask refusals
(empty text, dup labels). Default if unanswered: abs-refuse.

## Options

- abs-refuse — resolve to absolute against cwd, refuse a missing file (exit 1)  (doing)
- abs-allow — resolve absolute, allow missing; TUI flashes 'missing' on open
- verbatim — store as given, resolve against row cwd when opened

## Answer

abs-refuse
answered at: 2026-09-27T18:50:34.677687+00:00
