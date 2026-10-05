# q556 — Left/right to open/collapse the card: probe first?

status: answered
act: ask
kind: choice
thread: pane-ux
parent: q555
agent: 091b69f0-072f-4f53-a412-b8f0d0706c99
cwd: .
asked at: 2026-10-05T05:25:47.515167+00:00

## Context

Last round found the engine hands arrows to the mod only as a focus step with no direction, and hotkeys only take one digit or lowercase letter. That was tested on up/down. Left/right weren't tested on their own: they may arrive as the same directionless step, or not at all. The probe is a temporary log of every person focus event (origin, element, any extra fields); you press left and right a few times in the pane, and I read the log. If they carry no direction, left/right can't be told apart from up/down and the answer is no.

## Options

- probe — Add the temporary focus log, you press left/right, I report.  (★●)
- skip — Take the earlier finding as covering left/right; no.

## Recommendation

probe — high

## Answer

probe
answered at: 2026-10-05T05:28:37.050733+00:00
