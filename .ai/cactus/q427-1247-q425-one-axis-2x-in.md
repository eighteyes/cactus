# q427 — q425 'one axis, 2x in parallel': which did you mean?

status: answered
act: ask
kind: choice
thread: ranker
parent: q425
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-01T20:26:06.426146+00:00

## Context

Measured: two apint calls run concurrently fine (~1.3s wall, no rate-limit exit 7). Concurrency stays capped at 2 either way. Default if skipped: per-axis.

## Options

- per-axis — keep reversibility + complexity, one small label call per axis, both at once
+ shows why a row was held (costly · low)
+ built and tested now
- two prompts to tune  (★◐)
- one-risk — one combined label {auto-ok, human}, asked twice at once; both must say auto-ok
+ agreement check catches a flaky model
- no reason beyond 'held'

## Recommendation

per-axis — med

## Answer

per-axis
answered at: 2026-10-01T22:13:19.211506+00:00
