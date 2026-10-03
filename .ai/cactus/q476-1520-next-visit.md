# q476 — Visit fixed (c0dad68), toggles in (148e3cd). Restart TUIs, then?

status: answered
act: steer
kind: choice
thread: show-toggles
agent: 0f4be69e-67e5-485b-a467-0d31810683ad
cwd: .
asked at: 2026-10-02T22:05:20.793932+00:00

## Context

Root cause: a pane id is per herdr session; a TUI outside herdr or in another
session got agent_not_found. Both running TUIs (10592, 53499) hold old code.
Nothing pushed.

## Options

- verify — restart TUIs, press v on a row from another session
+ confirms the fix where it broke  (doing)
- www — check the web board poke button against the same session fix
+ www.py got the same session pass-through, untested live

## Answer

verify
answered at: 2026-10-02T23:01:51.967446+00:00
