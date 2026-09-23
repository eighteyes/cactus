# q227 — Keep e as a bare hotkey in the TUI?

status: answered
act: ask
kind: choice
thread: elaborate
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T21:05:08.094318+00:00

## Context

test_textq.py typed letters without i and now trips e. Real usage presses i first. e opens the input; enter would send the request, escape cancels.

## Options

- keep — e opens an elaborate request on open/live rows  (★◐)
- chord — require a two-key chord, e.g. E (shift) or ge

## Recommendation

keep — med
typing is already an explicit mode (i); a stray e only opens an input that escape cancels

## Answer

keep
answered at: 2026-09-23T21:40:32.533023+00:00
