# q410 — Tradeoff marks on choices: how do agents write them?

status: answered
act: ask
kind: choice
thread: tradeoffs
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T03:47:55.494351+00:00

## Context

Today a choice renders as one line: '1) label — description' (tui.py:386).

parse: description body after the first colon may hold lines starting '+' or '-'; card draws each under the choice, ✓ green / ✗ red. Plain descriptions unchanged. Touches tui card + watch + text renderer + skill docs. No schema change.

convention: zero code, but no color and agents will drift.

flags: cleanest data, but a schema column, CLI, MCP, edit semantics. Heaviest.

Default if unanswered: parse.

## Files

- /Users/god/projects/cactus/src/cactus/tui.py
- /Users/god/projects/cactus/skills/cactus/SKILL.md

## Options

- parse — '+ pro' / '- con' lines in a -c description render as green ✓ / red ✗ in the card  (★◐)
- convention — agents type ✓/✗ themselves; skill + --agent-help teach it; no color, no code
- flags — new --pro LABEL:TEXT / --con LABEL:TEXT on ask/edit; stored per choice

## Recommendation

parse — med
color without schema change; old rows unaffected

## Answer

parse
answered at: 2026-10-01T03:48:43.716083+00:00
