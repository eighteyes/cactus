# q463 — Folding the edit-ends-wait bug (q442 wait exited early) into the q459 fix

status: answered
act: steer
kind: choice
thread: wait
agent: c76b762b-8158-4265-88cd-22d09a712233
cwd: .
asked at: 2026-10-02T20:43:52.900034+00:00

## Context

A get --wait on open q442 exited 0 with no output right after I ran
`cactus edit` on it. Not confirmed yet; the agent writes a test first.

## Options

- fold-in — same agent tests and fixes it, one commit
+ same code path  (doing)
- separate — its own commit after q459
+ cleaner history

## Answer

fold-in
answered at: 2026-10-02T20:45:08.150826+00:00
