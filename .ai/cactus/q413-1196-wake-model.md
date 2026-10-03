# q413 — Answers must wake an idle agent: by what?

status: answered
act: ask
kind: choice
thread: no-monitor
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T17:40:03.804561+00:00

## Context

You ruled out next-turn: the agent must continue without your input.

Today: cmd_answer auto-pokes only webhook-mapped owners (cli.py ~657). Herdr rows carry a pane stamp; poke.reachable already gates p in the TUI.

Per-row/batch --wait is the once-loop by another name, so it is folded into once-loop.

Default if unanswered: push.

## Files

- /Users/god/projects/cactus/skills/cactus/SKILL.md

## Options

- push — answering a row auto-pokes its herdr pane (as TUI p does by hand)
+ no agent process, nothing to arm, works idle for hours
- herdr-only; a busy agent gets the poke queued mid-turn
- once-loop — restore --monitor --once, armed in the background, re-armed on wake
+ proven (q339 probe), host-agnostic where background exists
- every agent must arm and re-arm correctly
- push+loop — auto-poke where a pane exists, once-loop elsewhere
+ covers herdr and non-herdr
- two paths to document and test

## Answer

push+loop
answered at: 2026-10-01T17:42:31.204065+00:00
