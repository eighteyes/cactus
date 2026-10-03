# q420 — Ranker 'another thread': which kind?

status: answered
act: steer
kind: choice
thread: ranker
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-01T20:14:01.002582+00:00

## Context

Ranker = scores each row for reversibility/complexity; only low-risk,
reversible rows get an AI decision (your follow-up). Research agents still
running on strands-decider, apint, TUI. Default if untouched: cactus-thread.

## Options

- cactus-thread — ranker forks posted under cactus thread `ranker`, I drive both
+ one context, decisions stay linked
- my context carries both designs  (doing)
- agent-session — spawn a separate agent that owns the ranker design
+ parallel, isolated
- two agents to reconcile at the seam

## Answer

agent-session
answered at: 2026-10-01T20:17:12.586636+00:00
