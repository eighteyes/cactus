# q314 — Agent monitor scoped to cwd project: worktree sessions miss their own answers

status: answered
act: ask
kind: choice
thread: macapp
agent: dd7e2c75-9a5e-4984-aa99-920e53797a41
cwd: .
asked at: 2026-09-25T20:36:46.518305+00:00

## Context

Today my cwd drifted into .claude/worktrees/... and every monitor I started there watched only that project, so q302, q303 and q311 answers never woke me. cactus projects also lists 6 .claude/.herdr worktree paths as separate projects. worktree-root also fixes keys: qN numbering and LABEL:qN refs would stay with the repo. Cost of worktree-root: an extra git call at scope time and a one-off rehome of existing worktree rows. Default if unanswered: monitor-all.

## Options

- monitor-all — --monitor --agent ID watches every project; the agent filter already narrows it
- worktree-root — scope.py maps a git worktree to its main repo (git-common-dir), so worktree rows file under the parent project  (★◐)
- as-is — agents must pass --all themselves when in a worktree

## Recommendation

worktree-root — med
fixes monitor, projects list and refs in one place

## Answer

worktree-root
answered at: 2026-09-25T21:53:08.370953+00:00
