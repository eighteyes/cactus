# q194 — What does R on a run row record?

status: answered
act: ask
kind: choice
thread: escalate
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T18:12:25.954147+00:00

## Options

- result — R runs it and records approve + exit code + output tail as the answer; n records deny  (★●)
- approve — R only runs it; you still press y to approve

## Recommendation

result — high
the agent is blocked on the result, not the approval; today the output never leaves the TUI

## Answer

result
answered at: 2026-09-23T18:13:12.309311+00:00
