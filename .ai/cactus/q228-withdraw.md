# q228 — Should a withdrawn elaborate request read differently from an agent's edit on the monitor?

status: answered
act: ask
kind: choice
thread: elaborate
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T21:05:08.148505+00:00

## Context

Today the monitor diffs polls; u withdrawing a request and an agent's edit produce the same row change.

## Options

- split — add a withdrawn event (needs a marker on the row, not a pure diff)  (★◐)
- same — both read as edited

## Recommendation

split — med
an agent told edited will look for a rewrite that never happened

## Answer

split
answered at: 2026-09-23T21:40:53.677838+00:00
