# q338 — Monitor dies at the 30-min cap. Replace the Monitor tool with what?

status: answered
act: ask
kind: choice
thread: durability
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-27T23:22:07.205991+00:00

## Context

The killer is Monitor's 30-min cap, a harness limit cactus cannot change.
When the turn has ended nobody re-arms it, so the inbox goes deaf.

once-loop: one process per agent, exits on the first non-asked event,
the exit re-invokes the agent, the agent spawns the next one. Covers
review/plan verdicts and elaborate, which per-row --wait does not.
Open question: whether background Bash outlives 30 min. A 35-min
sleep probe is running now (task b496aj6hf).

per-row: same durability, N processes, and --wait returns only when a
one-shot row leaves open/elaborate, so persistent rows need a new verb.

keep: no code; the gap stays.

Recommend once-loop (med). Default if unanswered: once-loop, after the
probe passes.

## Options

- once-loop — background Bash 'cactus --monitor --once' as the primary wake-up, respawn after each event
- per-row — background 'cactus get KEY --wait' per open row; needs a new watch verb for review/plan
- keep — Monitor tool, re-arm on expiry, accept the gap when the agent's turn has ended

## Answer

i think bash background lasts max 5 mins. there is a persistent setting somewhere in one of the tools.
answered at: 2026-09-27T23:24:03.568903+00:00
