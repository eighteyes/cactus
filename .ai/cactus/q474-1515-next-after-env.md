# q474 — Mod loads everywhere now. Next: hooks cleanup or push modes?

status: answered
act: ask
kind: choice
thread: delivery
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T21:59:58.961312+00:00

## Context

Done: env line in ~/.claude/settings.json; mod commits ~/ai 4c9fa13..6f1a6db;
CLI verbs cactus 559811d.

Default if unanswered: hooks.

## Options

- hooks — Stop hook accepts an open row this agent owns; session-start
text skips wait advice when the mod is loaded
+ ends the per-turn nag (q469) you have hit four times today
- touches hooks/stop-fork.sh, identity, hook tests  (★●)
- push — herdr and webhook wakes for sessions without the mod
+ Codex/Grok/Desktop get woken
- revives the q430 herdr auto-poke

## Recommendation

hooks — high
the Stop hook nags every turn even with forks open

## Answer

hooks
answered at: 2026-10-02T22:00:46.761410+00:00
