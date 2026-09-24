# q229 — Stopping at the answer-path crash fix; other TUI store calls stay unguarded

status: answered
act: steer
kind: choice
thread: crash
agent: patches-here
cwd: .
asked at: 2026-09-23T21:20:37.049216+00:00

## Context

6545080 catches AlreadyAnswered/ValueError on enter/s/plan notes. Unguarded still: action_clear_focused (store.clear), set_step_done on plan steps, and _finish_run_row catches everything but misreports. None has been seen crashing. Tap harden to widen the fix.

## Options

- stop — ship 6545080 as is; the reported crash is fixed  (doing)
- harden — also guard c (clear), plan step toggle, and run-row approve against rows purged or changed elsewhere

## Answer

stop
answered at: 2026-09-23T21:41:01.297008+00:00
