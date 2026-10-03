# q457 — Pane look: TUI-style card for the focused row, compact rail above

status: answered
act: steer
kind: choice
thread: mod
parent: q456
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T18:18:07.031813+00:00

## Context

Colour by act (ask/review/plan/data/notify/run), dim live rows, bold key.
Proceeding with card unless redirected.

## Options

- card — focused row expands like the TUI card, others one line
+ context, choice descriptions with green/red marks,
+ recommend + confidence + why, thread/agent, files, plan steps,
+ review verify block, verdict history, sent/heard
- focus tracking needs the ui.focus event  (doing)
- all — every row drawn in full, no focus logic
+ simplest
- long inbox scrolls a lot

## Answer

card
answered at: 2026-10-02T18:32:16.382633+00:00
