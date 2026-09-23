# q131 — Next for cactus-v1?

status: retired
act: ask
kind: choice
thread: next
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:24:56.148782+00:00

## Context

Both sessions are idle; tree clean except .ai/TODO.md. Backfill writes records for older rows in every project with cactus rows, not just this one.

## Options

- tag — local tag v1 on cactus-v1, no push
- backfill — write records for rows answered before 254e2d3
- stale — fix test_recommend_plan.py, still asserting close-on-enter  (★◐)

## Recommendation

stale — med
a red throwaway test hides the next real regression; tag after it passes

## Answer

stale — lets clean up too
answered at: 2026-09-23T04:29:47.055908+00:00
