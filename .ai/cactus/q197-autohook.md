# q197 — Should a PermissionDenied hook post the denied command to cactus run itself?

status: answered
act: ask
kind: choice
thread: escalate
parent: q196
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T18:14:00.646872+00:00

## Context

Per the Claude Code hooks docs (reported by a docs agent, unverified by me): PermissionDenied fires on auto-mode denials with tool_name, tool_input, denial_reason; it cannot inject context to the model, but a hook can run any command. The agent learns the row exists through its monitor or the frontier hook (q149). Lives in the plugin's hooks.json (cactus-b9's).

## Options

- auto — the hook posts cactus run with the denied command, reason and cwd; one row per tool_use_id  (★◐)
- teach — no hook; agents post cactus run themselves, per the docs

## Recommendation

auto — med
escalation then survives an agent that forgets the rule; you still decide on R

## Answer

auto
answered at: 2026-09-23T18:14:36.267606+00:00
