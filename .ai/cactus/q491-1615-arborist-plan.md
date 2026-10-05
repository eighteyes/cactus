# q491 — Branch plan: tick each action you approve

status: answered
act: ask
kind: multi
thread: wrap
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-03T04:28:30.211198+00:00

## Context

Trunk: cactus-v1 (no main/master; only remote branch). Local 10 ahead of
origin, 0 behind. LIVE INSTALL: cactus is editable from this checkout, so any
merge runs in a scratch worktree and fast-forwards after.

branch            behind ahead conflict  state
macapp               111   0    -       merged
worktree-agent-a5db   97   0    -       merged
wait-default          33   0    -       merged
worktree-root        107   1   yes      conflict (scope.py linked-worktree root)
newest-first         107   1   yes      conflict (TUI rotate newest first)
revised-marker       112   1   yes      conflict (TUI revised marker)
cactus-v1-next       107   6   yes      conflict, contains the three above

None of the 4 unique commits are on trunk; none look superseded.
Stash@{0} "pre-wait-default in-flight edits" holds the same two
permission-hook edits now loose in the tree; left alone.
Unticked = keep. Deletes use -d, never -D.

## Options

- del-macapp — delete macapp + its worktree (fully merged, 0 ahead)  (★●)
- del-a5db — delete worktree-agent-a5db895c3a84322cc + worktree (merged)  (★●)
- del-wait — delete wait-default + its worktree (merged, 0 ahead)  (★●)
- resolve-next — start a session to merge cactus-v1-next (6 ahead,
conflicts) in a scratch worktree; it carries worktree-root,
newest-first and revised-marker
- 107 commits behind; conflicts in scope.py, tui.py

## Recommendation

del-macapp, del-a5db, del-wait — high
merged branches contribute nothing; the conflicts need a real session

## Answer

del-a5db, del-macapp, del-wait — yea
answered at: 2026-10-03T04:29:48.774385+00:00
