# q195 — How much output reaches the agent?

status: answered
act: ask
kind: choice
thread: escalate
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T18:12:26.008409+00:00

## Options

- tail — exit code + last 50 lines in the answer; full output spilled to a file whose path is recorded  (★◐)
- full — whole output in the database

## Recommendation

tail — med
bounded rows; the full log stays one path away

## Answer

tail
answered at: 2026-09-23T18:13:22.535253+00:00
