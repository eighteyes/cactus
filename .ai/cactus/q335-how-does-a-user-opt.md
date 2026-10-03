# q335 — How does a user opt back in?

status: answered
act: ask
kind: choice
thread: stop-hook
agent: 975d7f07-aec8-4df7-bc84-5495c430bdfd
cwd: .
asked at: 2026-09-27T19:03:49.408876+00:00

## Context

env: one line per script, same shape as the existing project-enabled gate, no schema change. unregister: cleanest default, but opting in means hand-editing settings. project: most granular, but needs a store column and a CLI verb.

## Options

- env — registered but exits 0 unless CACTUS_STOP_HOOK=1  (★◐)
- unregister — drop from hooks.json; README shows how to add it by hand
- project — a per-project cactus setting, off unless enabled

## Recommendation

env — med

## Answer

env
answered at: 2026-09-27T19:04:11.541161+00:00
