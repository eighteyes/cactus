# q411 — Re-enable the stop hook: which change?

status: answered
act: ask
kind: choice
thread: stop-hook
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T17:24:06.440357+00:00

## Context

Today: hooks/stop-fork.sh exits 0 unless CACTUS_STOP_HOOK=1; the env var is unset everywhere, so it never fires.

The in-flight no-monitor diff already left it one rule: hold a turn that ended without posting an ask.

Codex stop hook (plugins/cactus/hooks/stop.sh) never blocks either way.

Default if unanswered: mine.

## Files

- /Users/god/projects/cactus/hooks/stop-fork.sh

## Options

- mine — set CACTUS_STOP_HOOK=1 in ~/.claude/settings.json env
+ no code change; just you
- other users keep it off  (★○)
- default — flip to on-by-default, CACTUS_STOP_HOOK=0 opts out
+ every agent gets held to post an ask
- code + docs + CLAUDE.md invariant + tests change
- monitor — restore the removed open-rows-no-monitor block too
+ back to pre-diff behavior
- contradicts the no-monitor decision

## Recommendation

mine — low
smallest change; 'I want' reads personal

## Answer

default
answered at: 2026-10-01T17:26:57.675519+00:00
