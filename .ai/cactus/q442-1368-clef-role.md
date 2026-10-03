# q442 — clef-flash: what role does it take in the auto-decider?

status: answered
act: ask
kind: choice
thread: decider
parent: q439
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .ai/plan/auto-decider
asked at: 2026-10-02T03:22:40.373905+00:00

## Context

clef-flash: 9B, Apache-2.0, same question schema as strands-decider
(state + noul/choice/score, calibrated probabilities). Runs local via
transformers or community MLX 4/8-bit, or remote on Workers AI
(@cf/cloudflare/clef, ~39ms). Remote sends row text to Cloudflare.
○ The M3 latency figure the agent found matches strands exactly; treat
as unverified. Same schema = backend option is a thin adapter.
q439 serve: `cactus decider` starts whichever wins. Default: backend.

## Options

- replace — clef-flash replaces strands-decider as the picker
+ one model to run
- drops the decider client just built
- backend — add it as a second picker; a setting chooses which
+ compare both on real rows
- two clients to keep up
- ranker — use it for the reversibility/complexity classify step, not the pick
+ may beat apint 2-5s
- ranker was just tuned on apint

## Answer

backend
answered at: 2026-10-02T05:51:28.613436+00:00
