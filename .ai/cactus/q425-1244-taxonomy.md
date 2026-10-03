# q425 — Ranker taxonomy: what labels gate the AI?

status: answered
act: ask
kind: choice
thread: ranker
parent: q420
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-01T20:16:17.240881+00:00

## Context

Classifier: apint --labels (exit 3 = unavailable -> Haiku via
`claude -p --model haiku`). Ranker also orders the inbox? Say so
in text if wanted. Default: two-axis.

## Options

- two-axis — reversibility {reversible,costly,irreversible} x complexity {low,med,high}; gate = reversible+low
+ matches your ask exactly
- two classify calls  (★◐)
- single — one label {auto-ok, human}
+ one call, simple
- no visibility into why it was held

## Recommendation

two-axis — med
both axes show on the card, so a held row says why

## Answer

one axis, 2x in parallel, don't overload the poor thing
answered at: 2026-10-01T20:22:51.239583+00:00
