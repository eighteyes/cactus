# q506 — Pick-several on single-choice rows: which surfaces?

status: skipped
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-03T04:53:56.358551+00:00

## Context

Store already accepts it: `cactus answer KEY -s a -s b` on a choice row
records both and kind stays "choice" (probed on a scratch db). The agent
already reads .answer.selected as a list.

Confirm rows (y/n) excluded: two picks there contradict.
The flip lasts for that one answer; the row is not changed.

Default if unanswered: both.

## Options

- pane — m on a choice row in the pane turns its digits into toggles;
enter or g sends all picks
+ mod-only, no repo change
- both — the pane and the cactus TUI (same m key)
+ same behaviour wherever you answer
- TUI change + tests in this repo  (★◐)

## Recommendation

both — med
you answer in both; one key that works everywhere

## Answer

skipped
answered at: 2026-10-03T06:40:39.139689+00:00
