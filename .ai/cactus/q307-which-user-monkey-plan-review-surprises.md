# q307 — Which user-monkey plan/review surprises should I fix?

status: answered
act: ask
kind: multi
thread: user-monkey
agent: patches-um
cwd: .
asked at: 2026-09-25T16:56:10.310561+00:00

## Context

Report: .ai/tests/user-monkey-cactus-plan-review.md. 20 surprises, each with repro + file:line.

## Options

- high — #1 enter-to-type, #3 list hides live, #7 review text drops  (★◐)
- destructive — #10 reset-steps wipes, #2 bogus label, #14 cleared still editable  (★◐)
- labels — #9 yes/no vs pass/fail, #8 verdict notes, #5/#6 undo feedback
- rest — low-sev polish #4 #11-13 #15-20

## Recommendation

high, destructive — med

## Answer

destructive, high, labels, rest
answered at: 2026-09-25T16:56:50.337278+00:00
