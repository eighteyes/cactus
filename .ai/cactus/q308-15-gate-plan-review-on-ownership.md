# q308 — #15: gate plan/review on ownership?

status: answered
act: ask
kind: choice
thread: user-monkey
agent: patches-um
cwd: .
asked at: 2026-09-25T16:57:08.774743+00:00

## Context

Today any caller can tick another agent's steps. Required matches clear/reopen/edit but breaks every existing 'cactus plan qN --step' call in skills/docs.

## Options

- optional — --agent optional; refuse only when given and it mismatches the owner  (★◐)
- required — --agent required, gated like clear/edit (breaks existing agent calls + docs)
- leave — no gate; document that plan/review are open to any caller

## Recommendation

optional — med

## Answer

optional
answered at: 2026-09-25T19:39:31.306734+00:00
