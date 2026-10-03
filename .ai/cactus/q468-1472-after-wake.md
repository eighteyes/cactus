# q468 — Wake and elaborate both work. What should I build next?

status: answered
act: ask
kind: choice
thread: delivery
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T21:10:04.601491+00:00

## Context

Yes, elaborate works: your hint "does elaborate work" reached this session
through the mod as a wake, and this edit is the reply. The row is open again.

Why env first: the mod loads today only because I copied it into this
session's private mod folder. A restart or fork drops it, as happened once
already. One settings line makes every session load it from ~/ai/mods.

hooks: the cactus hooks still tell agents to wait; the mod overrides that in
the system prompt, so this is cleanup, not a fix.

push: wakes for sessions with no mod (Codex, Grok, Desktop) via herdr or
webhook. Revives the herdr auto-poke q430 removed.

Default if unanswered: env.

## Options

- env — add CLAUDE_CODE_PLUGIN_DIRS=~/ai/mods/cactus-pane to ~/.claude/settings.json
+ the pane and its wake load in every session, forks included
- every session then runs on mod delivery  (★●)
- hooks — make the cactus session-start/Stop hook text mod-aware
+ hooks stop telling mod sessions to wait
- the mod already overrides it in the system prompt
- push — herdr and webhook delivery for sessions without the mod
+ covers Codex/Grok/Desktop
- revives the q430 herdr auto-poke

## Recommendation

env — high
without it the mod dies on the next restart, as it did once already

## Answer

env
answered at: 2026-10-02T21:59:16.569185+00:00
