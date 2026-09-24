# q249 — What happens to the tracked .ai/ directory in the public repo?

status: answered
act: ask
kind: choice
thread: publish
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-24T04:47:00.003794+00:00

## Context

Untracking keeps files on disk; history still contains them unless rewritten. Another session is writing demo records (q231–q247) and demo/ right now — those would not be committed either way without a decision.

## Options

- keep — publish .ai/cactus decision records, TODO, plans and triage as-is
- records — keep .ai/cactus only; untrack the rest and gitignore it  (★○)
- none — untrack all of .ai/ and gitignore it

## Recommendation

records — low
decision records show how cactus was built with cactus; TODO and triage notes are internal working files

## Answer

keep
answered at: 2026-09-24T04:47:14.612349+00:00
