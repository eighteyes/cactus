# q414 — Stop hook: count cactus edit (and plan/review) as posting the fork

status: answered
act: steer
kind: choice
thread: stop-hook
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T17:41:24.094337+00:00

## Context

My last turn rewrote q413 with cactus edit; the hook found no 'cactus ask' and held the turn.

Also: its reason text says 'inspect the frontier on your next turn', which q413 (wake without your input) will overturn.

I'll fold both into the q413 build unless you tap ask-only.

## Files

- /Users/god/projects/cactus/hooks/stop-fork.sh

## Options

- accept-edit — treat `cactus edit|plan|review` as a fork, like `ask`
+ no false hold when the fork was rewritten in place
- a trivial typo edit also passes  (doing)
- ask-only — keep today; only `cactus ask`/AskUserQuestion pass
+ strict
- held my last turn although q413 was the fork

## Answer

accept-edit
answered at: 2026-10-01T17:42:46.687835+00:00
