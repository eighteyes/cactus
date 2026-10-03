# q417 — What didn't hold in the live wake test?

status: answered
act: ask
kind: choice
thread: live-test
agent: a40ce05c-cd77-4a4d-a265-13b5214d0b31
cwd: .
asked at: 2026-10-01T19:32:05.667579+00:00

## Context

q416 reads open, no answer recorded; the backgrounded waiter (since 19:16:08Z) is still alive. Default if unanswered: treat as not-visible and check TUI project filtering.

## Files

- /Users/god/projects/cactus/hooks/pretooluse-wait.sh

## Options

- not-visible — q416 never showed in the TUI
- lost — tapped a/b, row went back to open
- foreground — the 0a block didn't hold somewhere

## Answer

foreground
answered at: 2026-10-01T19:32:21.102094+00:00
