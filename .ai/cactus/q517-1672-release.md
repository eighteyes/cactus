# q517 — Release path for cactus 0.3.0?

status: answered
act: ask
kind: choice
thread: release
agent: 0f4be69e-67e5-485b-a467-0d31810683ad
cwd: .
asked at: 2026-10-03T19:32:52.823163+00:00

## Context

Gaps: 40 commits since v0.2.0 (Oct 1), 28 unpushed; no CI; no CHANGELOG;
version still 0.2.0 (Codex plugin stamped 0.2.0+codex.20261003...); only branch
is cactus-v1, no main; cactus-pane mod not in repo; foreign uncommitted edits in
hooks/permission-denied.sh + plugins/cactus/hooks/permission-request.sh;
stray a.txt and a screenshot in skills/cactus/.

## Options

- productionize — run /productionize on the repo
+ full hardening pass
- big, many agents
- checklist — I do the short list: bump 0.3.0, CHANGELOG, CI pytest, tag
+ fixes the real gaps only  (★◐)

## Recommendation

checklist — med
tests pass; the gaps are release plumbing, not code

## Answer

productionize
answered at: 2026-10-05T00:23:16.352668+00:00
