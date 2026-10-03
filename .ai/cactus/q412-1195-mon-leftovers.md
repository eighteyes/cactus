# q412 — Monitor leftovers after 79a83c2: what next?

status: answered
act: ask
kind: multi
thread: no-monitor
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T17:39:36.626282+00:00

## Context

Committed: hooks, CLI, README, shared + Claude skills, Stop on by default, tradeoff text output.

Left uncommitted, not mine: CLAUDE.md field hunk (drop_floating paragraph move) and the project-enabled gates in permission-denied.sh / permission-request.sh.

Default if unanswered: q339 + policy + stragglers; keep the courier.

## Files

- /Users/god/projects/cactus/CLAUDE.md
- /Users/god/projects/cactus/agents/cactus-courier.md
- /Users/god/projects/cactus/skills/cactus/WEBHOOK_SETUP.md

## Options

- q339 — rewrite CLAUDE.md q339 rule; drop the --once wake-up half
+ removes the self-contradiction
- loses the 2.5h probe note unless kept as history  (★●)
- policy — reword "background exit does not wake" as policy, not fact
+ q339 measured that it does wake
- touches CLAUDE.md, README, two skill files  (★●)
- stragglers — fix CODEX.md, GROK.md, WEBHOOK_SETUP.md, monitor.py docstring, event wording
+ no doc teaches the monitor
- broad doc edit  (★●)
- courier — delete agents/cactus-courier.md
+ nothing parks on --monitor
- loses opt-in thread watcher

## Recommendation

q339, policy, stragglers — high
the docs still contradict each other

## Answer

courier, policy, q339, stragglers
answered at: 2026-10-01T17:41:48.632551+00:00
