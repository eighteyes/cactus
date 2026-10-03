# q469 — Stop hook nags even with q468 open; folding that into the hooks option

status: answered
act: steer
kind: choice
thread: delivery
parent: q468
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T21:11:13.811885+00:00

## Context

stop-fork.sh only counts asks posted this turn, so a turn that rewrote
or waits on an open fork still gets blocked. Proceeding as fold.

## Options

- fold — treat it as part of q468's hooks option
+ Stop hook should accept an open row this agent already posted  (doing)
- now — fix the Stop hook before anything else

## Answer

now — fhook should onlyfire if no questions are open.
answered at: 2026-10-02T21:59:58.963345+00:00
