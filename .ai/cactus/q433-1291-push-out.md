# q433 — q430 wait-only: removing push wake, keeping q412/q414 + docs

status: answered
act: steer
kind: choice
thread: no-monitor
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T22:35:12.710090+00:00

## Context

Proceeding with targeted now; tap revert to switch before I commit.

## Files

- /Users/god/projects/cactus/src/cactus/poke.py
- /Users/god/projects/cactus/hooks/session-start.sh

## Options

- targeted — hand-edit out wake_owner; poke back to webhook-only; docs say the backgrounded wait is the wake
+ keeps courier deletion, q414, stragglers fixes
+ leaves the other session's tui.py edits alone
- more edits than a revert  (doing)
- revert — git revert c3db875, then redo q414 and the courier deletion
+ exact undo
- conflicts with uncommitted tui.py/test_tui.py work

## Answer

targeted
answered at: 2026-10-01T22:41:26.369375+00:00
