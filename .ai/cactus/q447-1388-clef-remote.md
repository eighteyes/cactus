# q447 — clef-flash runs local only; the Workers AI route is left out

status: answered
act: steer
kind: choice
thread: decider
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .ai/plan/auto-decider
asked at: 2026-10-02T05:52:10.847941+00:00

## Context

Building now: the clef backend, a TUI setting to switch backends, and
`cactus decider start/status/stop`. A tap on add-remote adds the Cloudflare
route as a follow-up.

## Options

- local-only — transformers/MLX on this Mac, row text stays here
+ nothing leaves the machine  (doing)
- add-remote — also a Workers AI backend (@cf/cloudflare/clef)
+ ~39ms, no local 9B load
- sends row text to Cloudflare; needs an API token

## Answer

local-only
answered at: 2026-10-02T06:11:19.076605+00:00
