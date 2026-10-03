# q311 — Review row revised after a verdict: how should the TUI show it?

status: answered
act: ask
kind: choice
thread: macapp
parent: q306
agent: dd7e2c75-9a5e-4984-aa99-920e53797a41
cwd: .
asked at: 2026-09-25T16:57:36.701299+00:00

## Context

set_review already bumps updated_at, so the card text does refresh; nothing says it changed. Derivable with no schema change: q.updated_at > q.answer.created_at. The monitor already tells the agent (sidecar signature); only the human is blind. Applies to plan steps and edit too. Lands on cactus-v1, not macapp. Default if unanswered: mark.

## Options

- mark — rail kind-line and card gain 'revised' when updated_at is newer than the latest verdict  (★●)
- mark-flash — the mark, plus a one-time status-bar flash when the revision lands, same pattern as plan-done
- as-is — silent text swap is fine

## Recommendation

mark — high
zero schema, one comparison, stays visible until the next verdict

## Answer

mark and resort to end of list
answered at: 2026-09-25T19:39:01.031581+00:00
