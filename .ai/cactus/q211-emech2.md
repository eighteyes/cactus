# q211 — Not today: no verb edits a posted row's text, context or choices. The spec adds one. Which shape?

status: answered
act: ask
kind: choice
thread: elaborate
parent: q206
agent: 24400027-88f9-4355-a682-fe8b9a598105
cwd: .
asked at: 2026-09-23T19:46:22.049316+00:00

## Context

All three rewrite the same row in place (same key, answers untouched, updated_at bumped so the TUI redraws). They differ only in how your hint travels to the agent and what the board shows meanwhile. Today the only editable fields after posting are review blocks and plan steps; question text/context/choices are frozen at ask. Default if unanswered: status.

## Options

- status — 'e' flips the row to status elaborate; agent runs 'cactus elaborate KEY --context ...' which rewrites the row in place and flips it back to open  (★●)
- child — 'e' posts a child row carrying your hint; agent rewrites the parent in place, child clears itself
- verdict — your hint lands in the row's answers log; row stays open; agent rewrites in place

## Recommendation

status — high
in-place edit, visible waiting state, one row

## Answer

can the verb be edit, not elaborate?
answered at: 2026-09-23T19:47:23.710742+00:00
