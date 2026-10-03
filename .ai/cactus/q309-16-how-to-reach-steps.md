# q309 — #16: how to reach steps 10+ in the TUI?

status: answered
act: ask
kind: choice
thread: user-monkey
agent: patches-um
cwd: .
asked at: 2026-09-25T16:57:08.867753+00:00

## Context

Buffer adds latency to every single-digit toggle. Cursor conflicts with j/k row movement. Cap is honest and cheap.

## Options

- buffer — digits buffer ~0.5s, so 1 then 2 = step 12 (1 alone still fires after the pause)
- cursor — j/k-style step cursor inside the card, space toggles
- cap — leave 1-9; card says 'steps 10+ via CLI'  (★○)

## Recommendation

cap — low

## Answer

buffer
answered at: 2026-09-25T19:39:50.175287+00:00
