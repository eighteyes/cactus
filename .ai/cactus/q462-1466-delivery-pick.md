# q462 — How does cactus learn which delivery mode a session uses?

status: answered
act: ask
kind: choice
thread: delivery
parent: q460
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T20:40:28.551568+00:00

## Context

Your four modes:
  1 mod      the mod sees the answer and starts a turn; the ask returns at once
  2 wait     the blocking ask itself waits, backgrounded (today, q430);
             `get --wait` only for non-blocking rows or after a timeout
  3 herdr    inject a prompt into the agent's pane
  4 webhook  per-agent webhook map (today)

Several cactus sessions share one machine and one db, so the mode is per
agent id, not per host.

Conflict: q430 removed herdr auto-poke on answer; mode 3 returns it as opt-in.

Recommend register (● high): mode is per session, and every surface
answering a row must read it. Default if unanswered: register.

## Files

- /Users/god/projects/cactus/CLAUDE.md

## Options

- register — each session declares its mode; cactus stores it per agent id
+ mod declares `mod` at session start
+ hooks read it: a mod session posts --no-wait, gets no wait advice
+ answer side picks delivery from one column
- new column/table, migration  (★◐)
- env — CACTUS_DELIVERY in each session's environment, no store change
+ smallest change
- answer side (TUI, pane, www) cannot see another process's env

## Recommendation

register — med
the answer side and the hooks both need to read the same fact

## Answer

chat: delivery lives in the receiving client, not the answering command; TUI/CLI/pane/www only write the answer
answered at: 2026-10-02T20:44:53.446722+00:00
