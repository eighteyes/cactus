# q460 — Should the pane mod wake this session when its rows get answered?

status: answered
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T19:01:32.174771+00:00

## Context

A mod can: $.prompt.submit (starts a turn, framed as from the plugin),
$.session.append (user-role row, no turn), $.session.send (message another
session), prompt.compose (edit the system prompt), tool.call (deny/rewrite).

The mod polls feed every 3s and knows $.session.id(), which equals --agent.

CLI verbs committed: 559811d (541 tests, 0 failures).

Default if unanswered: wake, mod-only, behind a setting.

## Options

- wake — mod submits a framed prompt when this session's row is answered
+ no backgrounded cactus get --wait per ask
+ works on an idle session, no 60-min timeout
- only where the mod is loaded; Codex/Desktop keep waits  (★◐)
- note — mod appends a row the model reads on its next turn, no wake
+ cannot interrupt anything
- an idle session still sleeps through the answer
- stay — keep wait-only (q430); the pane stays a reader
+ one mechanism everywhere

## Recommendation

wake — med
replaces the wait dance in exactly the host it runs in

## Answer

wake — chat: mod is one of four delivery modes (mod, background wait, herdr injection, webhook)
answered at: 2026-10-02T20:40:19.897519+00:00
