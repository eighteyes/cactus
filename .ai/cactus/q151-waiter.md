# q151 — Replace the 30-minute Monitor window with a one-shot background waiter?

status: answered
act: ask
kind: choice
thread: frontier
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T16:07:00.812978+00:00

## Context

Background Bash has no 30-minute cap and notifies when it exits. The workflow line in the help, skill and your CLAUDE.md would change to match.

## Options

- oneshot — background cactus --monitor that exits on the first event and wakes the agent; re-armed after each event  (★◐)
- monitor — keep the Monitor tool, re-armed every 30 minutes

## Recommendation

oneshot — med
no expiry turns while you are away; testing it live on this thread now

## Answer

lets do Monitor by default, when we hit the cap switch to background, when we're active again, switch to Monitor
answered at: 2026-09-23T16:11:17.455266+00:00
