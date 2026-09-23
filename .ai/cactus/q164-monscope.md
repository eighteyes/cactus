# q164 — Should cactus --monitor require --agent?

status: answered
act: ask
kind: choice
thread: isolation
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T16:45:50.736820+00:00

## Context

Unfiltered today in: your global CLAUDE.md (fixed just now), session-start.sh, skills/cactus/SKILL.md step 1. The courier agent filters by thread without --agent and would pass its owner's id.

## Options

- require — --monitor refuses without --agent; humans use --tui/--watch  (★◐)
- docs — keep it optional; fix the hook, skill and CLAUDE.md to pass --agent

## Recommendation

require — med
three instruction sites already drifted to the unfiltered form; a refusal cannot drift

## Answer

require
answered at: 2026-09-23T16:51:04.946788+00:00
