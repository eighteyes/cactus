# q547 — Space can't differ from enter in a pane. Which navigation?

status: answered
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-05T05:06:29.512438+00:00

## Context

A Button press carries no key: space and enter are the same press, and
hotkeys are one digit or lowercase letter, so space cannot be bound.

All three drop the debug log and the focus-steering code.

Default if unanswered: enter2.

## Files

- /Users/god/projects/cactus/.ai/tmp/pane-nav.log

## Options

- enter2 — arrows walk focus natively (no steering, no auto-open); enter on a
closed question opens it, enter on the open one sends
+ closest to space-opens / enter-sends
- arrows also stop on card buttons
- jk — j/k move between questions; arrows/tab walk buttons natively; enter sends
+ predictable; matches the TUI  (★◐)
- list — question list as one Select (up/down native), enter opens, g sends

## Recommendation

jk — med
stops fighting the engine; list is the only real up/down but costs enter

## Answer

enter2
answered at: 2026-10-05T05:15:17.965201+00:00
