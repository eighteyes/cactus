# q488 — Codex has no live pane and can't start its own turn. Accept the prompt-hook substitute?

status: answered
act: ask
kind: choice
thread: codex-mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-03T01:29:44.262633+00:00

## Context

codex-mod (w3B:p9) interim: "A live rendered Codex pane and a native
start-turn API are not available; Herdr delivery remains the optional
external wake path." It is still building.

The herdr wake already exists (185e58d: cactus deliver herdr; Codex
session-start registers it).

Default if unanswered: accept.

## Options

- accept — on each prompt, a hook injects the workflow + latest answers
and clears answered rows; herdr delivery wakes it from outside
+ uses only what Codex ships today
- no pane; answers land on your next prompt or a herdr poke  (★◐)
- dig — have codex-mod look harder (MCP Apps UI in ChatGPT, app-server API)
+ might find a real pane or a turn API
- may only exist in ChatGPT, not the Codex CLI

## Recommendation

accept — med
herdr delivery already covers the wake; the hook covers instructions and answers

## Answer

accept
answered at: 2026-10-03T01:30:01.468970+00:00
