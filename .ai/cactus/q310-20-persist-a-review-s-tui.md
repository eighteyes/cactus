# q310 — #20: persist a review's TUI run output for the agent?

status: answered
act: ask
kind: choice
thread: user-monkey
agent: patches-um
cwd: .
asked at: 2026-09-25T16:57:08.961481+00:00

## Context

Code comment says review runs are card-only by design. The agent that asked for the review can't see what the human saw.

## Options

- persist — store run_exit/run_tail on review rows too, exposed as result  (★◐)
- leave — by design, card only

## Recommendation

persist — med

## Answer

persist
answered at: 2026-09-25T19:40:02.411046+00:00
