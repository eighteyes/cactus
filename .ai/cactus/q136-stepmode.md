# q136 — What should a later cactus plan KEY --step X do?

status: retired
act: ask
kind: choice
thread: next
parent: q133
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:55:17.193263+00:00

## Context

Today each call replaces the whole list and carries done flags by position, so a new step at position 1 inherits step 1's tick. Under append, rewriting the list needs a new flag (e.g. --reset-steps).

## Options

- append — add X to the end, keep existing steps and their ticks  (★◐)
- replace — set the list to this call's steps; ticks carry only to steps with identical text

## Recommendation

append — med
the surprising case is a one-step call wiping four steps; append makes that impossible

## Answer

append
answered at: 2026-09-23T04:55:32.287538+00:00
