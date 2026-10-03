# q336 — Stop hooks are opt-in now (CACTUS_STOP_HOOK=1), with docs and tests updated. How do I commit?

status: answered
act: ask
kind: choice
thread: stop-hook
agent: 975d7f07-aec8-4df7-bc84-5495c430bdfd
cwd: .
asked at: 2026-09-27T19:05:38.285881+00:00

## Context

Suite green. My files: CLAUDE.md, README.md, hooks/stop-fork.sh, plugins/cactus/hooks/stop.sh, plugins SKILL.md, skills/cactus/{CLAUDE,CODEX}.md, tests/test_hooks.py. README, both stop scripts, plugins SKILL.md and CLAUDE.md already had someone's uncommitted edits. src/cactus/{mcp,monitor,record,shell}.py changed since ae340e0, so an agent is active here.

## Options

- mine-whole — commit my 8 files whole, including any foreign edits already in them
- hold — leave it uncommitted, since another agent is mid-edit in this tree  (★◐)

## Recommendation

hold — med

## Answer

mine-whole
answered at: 2026-09-27T19:06:26.513419+00:00
