# q374 — Commit the project-poke work in its worktree? The dev agent's git calls were refused by a hook, so it's uncommitted.

status: answered
act: ask
kind: choice
thread: sublists
agent: ddd377dd-f47a-4a88-8a04-417e8b3f2561
cwd: .
asked at: 2026-09-28T20:59:41.541842+00:00

## Context

6 files, +175/-3. 135 tests pass (I re-ran). Deviations: poke() gains webhook=False for herdr-only; project_panes returns {panes, skipped}. Path: .claude/worktrees/agent-af162965a45403988

## Options

- commit — I commit on branch worktree-agent-af162965a45403988, no push  (★●)
- hold — leave it uncommitted for you to inspect

## Recommendation

commit — high

## Answer

commit
answered at: 2026-09-28T21:00:36.919932+00:00
