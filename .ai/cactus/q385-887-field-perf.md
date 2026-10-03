# q385 — Cactus field: is it fast enough now?

status: retired
act: review
kind: confirm
thread: field
agent: 275c9c71-be9e-42e8-a2ed-98fbafe29278
cwd: .
asked at: 2026-09-29T02:43:40.224189+00:00

## Files

- /Users/god/projects/cactus/.ai/plan/cactus-field/cactus-field-v6f-perf.md

## Options

- pass
- fail

## Verdicts

look at: CPU of the cactus --tui process in top or Activity Monitor while idle and while a seed falls; the feel of keypresses
run: cactus sky --bench && cactus --tui
pass: bench mean frame under ~6 ms; the TUI process idles under a few percent of a core; keys respond at once; T shows fps and sky_engine levers, and sky_engine=texture brings back the field-best look
fail: the process still pins a core, keys lag, or the fluid sky looks different from before this pass
then: say which engine you prefer and what fps feels right

- 2026-09-29T04:23:32.551495+00:00: skipped
- 2026-09-29T18:29:09.797253+00:00: skipped
