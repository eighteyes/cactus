# q208 — After /clear an agent gets a new identity and loses sight of its rows. Fix how?

status: answered
act: ask
kind: choice
thread: isolation
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T19:40:41.388862+00:00

## Context

Seen live by cactus-b9: after /clear its pane resolved to a new conversation id; rows and monitor stayed on the old one, so the frontier hook shows nothing. Rows already carry pane and session stamps (da2aff8). Needs a store verb (reassign owner, gated to rows stamped with the caller's pane) plus a hook call; TODO has this as the undecided re-home item.

## Options

- rehome — SessionStart moves open/answered rows stamped with this pane + session from the dead identity to the new one  (★◐)
- alias — identity keeps a list of prior ids; frontier, monitor and clear match any of them
- accept — rows stay with the old id; the human re-asks

## Recommendation

rehome — med
rows follow the pane that asked them; one write at session start, no alias bookkeeping in every verb

## Answer

rehome
answered at: 2026-09-23T19:46:33.056510+00:00
