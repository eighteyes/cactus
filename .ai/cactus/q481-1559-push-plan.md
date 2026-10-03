# q481 — Push plan: grow the webhook map into a per-agent delivery map. Go?

status: answered
act: ask
kind: choice
thread: delivery
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T23:02:37.987602+00:00

## Context

Rule (q462): delivery is the client's. The webhook map already is: each
agent registers its own entry; answering only delivers to it.

1 map    ~/.config/cactus/poke-webhooks.json entries become webhook OR herdr:
         {"AGENT": {"herdr": true}} prompts the row's stamped pane.
2 cli    `cactus deliver herdr|webhook URL|off --agent ID` writes/removes
         the caller's own entry. No db change.
3 answer poke_webhook_if_mapped -> deliver_if_mapped: webhook POST as today,
         herdr `herdr agent prompt {pane}`. Same callers (cli, www, TUI, pane).
4 hooks  Codex session-start in herdr runs `cactus deliver herdr` itself.
5 docs   WEBHOOK_SETUP becomes delivery; CLAUDE.md: q430's "herdr agents are
         not auto-poked" becomes "unless registered".
6 tests  map parse, deliver verb, herdr delivery under an inert transport.

Mod sessions register nothing (the mod pulls). Plan grade: B.
Default if unanswered: go.

## Files

- /Users/god/projects/cactus/src/cactus/poke.py
- /Users/god/projects/cactus/skills/cactus/WEBHOOK_SETUP.md

## Options

- go — build it as below
+ one registry, already client-declared
+ webhook path unchanged  (★◐)
- revise — change the plan first (say what in free text)

## Recommendation

go — med
extends a client-declared registry instead of adding a second one

## Answer

revise
answered at: 2026-10-02T23:09:54.602273+00:00
