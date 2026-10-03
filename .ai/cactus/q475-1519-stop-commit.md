# q475 — Commit the Stop hook change on hook tests alone?

status: answered
act: ask
kind: choice
thread: delivery
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T22:04:48.279947+00:00

## Context

Stop hook: silent while this agent has an `open` row in the project (q469).
live/elaborate do not count. Uncommitted in cactus; CLAUDE.md bullet not yet
written (your pending "drop" paragraph move stays out of the commit).

Mod: workflow guide injected on load, ~/ai dfe1f6a.

Default if unanswered: commit.

## Files

- /Users/god/projects/cactus/hooks/stop-fork.sh

## Options

- commit — commit stop-fork.sh + its test + the CLAUDE.md invariant now
+ 44/44 hook tests pass; the change touches only the hook script  (★●)
- suite — run the full pytest suite first (you stopped that run)
+ belt and braces
- several minutes

## Recommendation

commit — high
only the hook script changed and its whole test file passes

## Answer

commit
answered at: 2026-10-02T22:05:06.052415+00:00
