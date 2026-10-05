# q509 — Drift it found but did not fix: skill docs. Fix now?

status: answered
act: ask
kind: choice
thread: docs
agent: 0f4be69e-67e5-485b-a467-0d31810683ad
cwd: .
asked at: 2026-10-03T05:16:48.302419+00:00

## Context

Breaks-user: WEBHOOK_SETUP says add authorization next to `deliver webhook`;
deliver replaces the whole entry, so auth vanishes (cli.py:1320).
Misleads: herdr target is the pane not the agent id; herdr entries DO auto-poke;
CODEX.md never mentions mod mode or frontier auto-clear (5-row cap).
Cosmetic: Stop hook q469 silence missing in skill CLAUDE.md.

## Files

- /Users/god/projects/cactus/skills/cactus/WEBHOOK_SETUP.md
- /Users/god/projects/cactus/skills/cactus/CODEX.md
- /Users/god/projects/cactus/skills/cactus/CLAUDE.md

## Options

- fix — rewrite the stale lines in WEBHOOK_SETUP, CODEX, skill CLAUDE.md
+ one breaks users: `cactus deliver webhook` drops a hand-set authorization  (★●)
- later — leave it, file it in .ai/TODO.md

## Recommendation

fix — high
agents read these files and follow them

## Answer

fix
answered at: 2026-10-03T07:20:58.894392+00:00
