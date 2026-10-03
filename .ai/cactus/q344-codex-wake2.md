# q344 — Codex wake without herdr: which path?

status: answered
act: ask
kind: choice
thread: durability
parent: q343
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-28T05:50:09.040089+00:00

## Context

You asked: we had monitor with Codex before? The old CODEX.md told Codex
to run the unbounded 'cactus --monitor' in the foreground and 'keep it
alive'. No probe ever showed that waking Codex; the same doc hedged
with 'if the environment cannot keep a foreground process alive, use a
one-shot waiter or a webhook'. Mechanically it is the same thing that
just failed: a process printing or exiting does not re-enter Codex.

auto-poke is off the table: it needs herdr.

next-turn: zero code. Codex only learns of an answer when you type to
it. The frontier hook already prints answered-but-unacted rows then.

hold-turn: Codex's own shell timeout caps N (unknown, likely minutes).
An answer during the hold wakes it; an answer after it waits for your
next turn. Burns a Codex turn per hold.

research-first: a runner is sweeping Codex CLI docs now for any wake
path (background completion, notifications, idle hooks, app-server or
ACP prompt injection). Result lands in this row's context.

Default if unanswered: next-turn.

## Options

- next-turn — no wake; the UserPromptSubmit frontier hook already lists answered rows when you next type to Codex  (★○)
- hold-turn — Codex ends each turn with 'cactus get KEY --wait --timeout N' in the foreground, so the turn stays open until the answer or N seconds
- research-first — find out whether Codex CLI has any background-exit or notification wake at all, then decide

## Recommendation

next-turn — low
only path proven to work; research may change it

## Answer

research-first
answered at: 2026-09-28T05:51:00.309043+00:00
