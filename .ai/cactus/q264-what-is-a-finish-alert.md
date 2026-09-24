# q264 — What is a 'finish alert' in cactus --www?

status: answered
act: ask
kind: choice
thread: www
agent: 574daac0-aae8-4605-a3a1-0d9a5be9dcd4
cwd: .
asked at: 2026-09-24T21:04:11.996787+00:00

## Context

cactus has no finish concept today. Webhooks are one-way agent<-human poke (poke.py). Answering from the web page will auto-poke webhook-mapped agents exactly like the TUI regardless. Building the base server now; this only shapes the alert layer. Default if unanswered: arrive.

## Options

- arrive — browser Notification + toast when an agent posts a new row (SSE on cursor change); no new agent contract  (★◐)
- inbound — www exposes POST /hook/finish {agent,message}; an agent calls it when done, browser shows the toast
- both — arrival notifications plus the inbound finish endpoint

## Recommendation

arrive — med
no new contract for agents to learn; SSE already needed for live updates

## Answer

arrive
answered at: 2026-09-24T21:18:03.342794+00:00
