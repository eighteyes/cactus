# q482 — Push plan: what should change? (q481 came back revise, no note)

status: answered
act: ask
kind: text
thread: delivery
parent: q481
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T23:10:08.853271+00:00

## Context

The plan, for reference:
1 map    poke-webhooks.json entries: webhook URL or {"herdr": true}
2 cli    `cactus deliver herdr|webhook URL|off --agent ID` (own entry)
3 answer on answer: webhook POST, or herdr prompt to the row's pane
4 hooks  Codex session-start registers herdr itself
5 docs   WEBHOOK_SETUP -> delivery; CLAUDE.md q430 note revised
6 tests

Type what to change, by step number or in your own words.

## Files

- /Users/god/projects/cactus/src/cactus/poke.py

## Answer

god
answered at: 2026-10-02T23:10:59.652596+00:00
