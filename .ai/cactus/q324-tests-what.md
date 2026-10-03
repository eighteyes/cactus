# q324 — Tests for which thing?

status: answered
act: ask
kind: choice
thread: poke
agent: 83155dd4-270a-444a-bf43-8d9e8a6dfa37
cwd: .
asked at: 2026-09-26T06:00:44.717688+00:00

## Context

CLAUDE.md: no test suite, verification is .ai/tmp scripts against a scratch DB.
The jq inversion in the projects hooks shipped because no hook test exists.

## Options

- poke — one stripped-PATH script for the fallback
- projects — hook smoke tests for the enable/ignore switch  (★◐)
- repo — start a real suite; today it is throwaway scripts by design

## Recommendation

projects — med
the one place a missing test already bit

## Answer

repo
answered at: 2026-09-26T06:19:17.843057+00:00
