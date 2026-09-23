# q137 — Which triage batches get fixed next?

status: retired
act: ask
kind: multi
thread: next
parent: q134
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T04:58:17.206137+00:00

## Context

Full table: .ai/tests/user-monkey-triage.md. plan --step append (q136) joins whichever batch runs first. #34 is unverified and gets a repro first. Two findings are design per CLAUDE.md, two already fixed.

## Options

- high — 7 high bugs (no-free, wait orphan, exit 2 clash, off-menu label, empty answer, cleared resurrect, i-typing race)  (★◐)
- medbug — 7 medium bugs (seen choices, wait drops keys, missing-key exits, poke ghost, --db empty/missing dir, tui+monitor)  (★◐)
- medux — 5 medium ux (get hides verdicts, silent empty results, flash expiry, watch header)
- lowux — 15 low ux papercuts

## Recommendation

high, medbug — med
the high bugs corrupt or lose data; the medium bugs break the exit-code contract agents script against

## Answer

high, lowux, medbug, medux
answered at: 2026-09-23T05:08:11.589382+00:00
