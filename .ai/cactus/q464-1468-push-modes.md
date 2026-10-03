# q464 — Herdr and webhook push from outside the session: keep them answer-side?

status: answered
act: ask
kind: choice
thread: delivery
parent: q462
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T20:44:53.640224+00:00

## Context

Settled (q462, your words): delivery lives in the receiving client.
TUI, `cactus answer`, the pane and www only write the answer.

  mod      client: the mod polls, sees its own agent id answered, starts a turn;
           it tells its model to post --no-wait (prompt.compose)
  wait     client: the blocking ask is the wait
  herdr    no client of its own: someone must type into the pane
  webhook  no client of its own: fired today by cli/www/TUI on answer

Default if unanswered: exception.

## Options

- exception — herdr/webhook stay pushes fired on answer, per-agent map
+ an agent with no mod and no wait (Grok) still gets woken
+ webhook works this way today
- two places decide delivery: the client, and the push map  (★◐)
- client — every mode is a client; herdr/webhook become watcher processes
+ one rule: the answer only writes
- a long-lived watcher per session: the background process mode 1 avoided

## Recommendation

exception — med
herdr and webhook agents have no process of their own to do the waking

## Answer

agent with a mod up... can we enable / disable the bp process on mod start / stop
answered at: 2026-10-02T20:46:36.367864+00:00
