# q423 — How does cactus run strands-decider (torch, ~500MB, no GGUF/MLX)?

status: answered
act: ask
kind: choice
thread: decider
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-01T20:16:17.098376+00:00

## Context

Repo ships a CLI and an HTTP server. Only v19 is documented;
v19z was not found on HF (agent ○ low conf) - I use v19 unless you
say v19z is real. Default: sidecar.

## Options

- sidecar — `strands-decider serve` on :8000, cactus calls HTTP
+ model stays warm, cactus deps untouched
- a daemon to start  (★●)
- extra — `cactus[decider]` optional dep, load in-process on demand
+ no daemon
- torch in cactus env, cold load each TUI start

## Recommendation

sidecar — high
cactus is dependency-light; a warm server keeps ~150ms

## Answer

sidecar
answered at: 2026-10-01T20:21:57.908688+00:00
