# q504 — cactus-v1-next brings 3 features. Tick the ones to keep.

status: answered
act: ask
kind: multi
thread: wrap
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-03T04:49:25.510206+00:00

## Context

Merge is paused in scratch worktree .claude/worktrees/merge-next; trunk and
the live install are untouched. Conflicts: CLAUDE.md 1, store.py 1 (projects
query: newest_open vs due_count), tui.py 3 (_revised + rail sort).

Unticked features: I drop their code from the merge, keep the branch commit
in history, and say so in the merge message.

Default if unanswered: worktree-root only.

## Files

- /Users/god/projects/cactus/.claude/worktrees/merge-next/src/cactus/scope.py

## Options

- worktree-root — rows asked from a linked worktree file under the main
repo's project (q314); CACTUS_SCOPE=worktree opts out
+ merged with no conflict
- worktree agents stop being their own project  (★◐)
- newest-first — [ ] rotates to the project with the newest open row (q313)
- trunk now ranks projects by due count (q351); two orders to reconcile
- revised — review/plan rows marked "revised" and moved to the rail end
when the agent edits after your verdict (q311)
- overlaps trunk's sent/heard/responded marks (q404-406)
- moving rows breaks the fixed rail (q226)

## Recommendation

worktree-root — med
it merged clean; the other two collide with newer trunk designs

## Answer

newest-first, revised, worktree-root
answered at: 2026-10-03T06:39:36.114076+00:00
