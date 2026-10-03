# q345 — Codex wake path, given the research

status: answered
act: ask
kind: choice
thread: durability
parent: q344
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-28T05:52:29.071962+00:00

## Context

Research (openai/codex issues 42908, 7084, 4337; hooks docs):
- A Codex background exec's completion is delivered at the NEXT MODEL
  REQUEST. It interrupts an agent that is itself waiting, it does not
  start a turn on an idle session. That matches q342 exactly.
- Codex shell timeout is ~366 s; no timer or idle hook exists; hooks
  are SessionStart/End, Pre/PostToolUse, UserPromptSubmit, Stop,
  PermissionRequest, SubagentStart/Stop.
- No socket or webhook into a running interactive session is
  documented. ACP (Agent Client Protocol) exists; whether it can inject
  a prompt into a running session is unknown.

acp-bridge: the Codex agent in pane w3B:p5 already implemented it here:
ACP form requests become blocked, source=acp rows; wait_response() holds
the ACP request until a cactus answer lands. The wake is the protocol
response itself. Covers the questions Codex asks through ACP; plain
'cactus ask' rows still surface next-turn.

CODEX.md and the Codex hook are being corrected now regardless: they
must not promise that the --once exit wakes Codex.

Default if unanswered: acp-bridge, with next-turn documented as the
fallback for plain rows.

## Options

- acp-bridge — Codex asks through ACP elicitation, cactus holds the protocol request until answered; Codex's own in-flight work in this tree  (★◐)
- next-turn-only — document that Codex learns of answers on your next prompt via the frontier hook; no blocking path
- hold-turn — Codex ends a turn on 'cactus get KEY --wait --timeout 300' in the foreground; ~5 min per hold, Codex shell timeout is ~366 s

## Recommendation

acp-bridge — med
only path with a real wake and it is already half built

## Answer

acp-bridge
answered at: 2026-09-28T05:55:55.253668+00:00
