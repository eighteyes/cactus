# q206 — Elaborate on e: how does the human's request reach the agent?

status: answered
act: ask
kind: choice
thread: elaborate
agent: 24400027-88f9-4355-a682-fe8b9a598105
cwd: .
asked at: 2026-09-23T19:36:00.244035+00:00

## Context

status is the only option where the TUI can show 'awaiting elaboration' and the frontier hook can list it in the agent's backlog without a second row. child reuses threading but inverts direction (human asks agent) and leaves a row to clear. verdict muddies the answers log on one-shot rows, which currently have exactly one answer. All three need a context-edit verb in src/cactus, which is cactus-ba's builder's turf; I will spec it and hand it over. Default if unanswered: status.

## Options

- status — row gets a status 'elaborate' + the typed hint stored on it; monitor emits an elaborate event with key + hint; agent rewrites via a new 'cactus elaborate KEY --context ... --text ...' which flips it back to open  (★●)
- child — TUI posts a child row (parent_id=KEY, act=seen-shaped, owner=agent) carrying the hint; agent answers by editing the parent; the child clears itself
- verdict — the hint is appended to the row's answers log with label 'elaborate'; row stays open; monitor reports it as a verdict

## Recommendation

status — high
one row, visible state, hook-listable

## Answer

can we edit the current question or not?
answered at: 2026-09-23T19:46:01.524836+00:00
