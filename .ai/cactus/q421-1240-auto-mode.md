# q421 — Auto decider: what does it do once the ranker passes a row?

status: answered
act: ask
kind: choice
thread: decider
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-01T20:16:16.975262+00:00

## Context

Pipeline: ranker classifies (apint, Haiku fallback) -> gate on
reversible+low risk -> strands-decider picks label+confidence.
Risky/irreversible rows never get an AI decision.

strands-decider: 72% acc, 0.9+ conf ~95% right, ~150ms on M3.
Default if unanswered: propose.

## Options

- propose — fill recommend+why+confidence; you press A to accept
+ nothing answers without a keypress
- every row still needs you
- auto-answer — low-risk reversible + confidence>=0.9 answers itself
+ truly automatic
- answers land unseen; undo only before agent reads
- hybrid — propose always, auto-answer only past a settings toggle
+ starts safe, opt in later
- two paths to build and test  (★◐)

## Recommendation

hybrid — med
matches 'only decide non-risky' and starts with you in control

## Answer

propose
answered at: 2026-10-01T20:17:46.816506+00:00
