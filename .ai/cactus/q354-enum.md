# q354 — Refactor projects_open/settings_open into one view enum while adding answers

status: answered
act: steer
kind: choice
thread: sublists
agent: ddd377dd-f47a-4a88-8a04-417e8b3f2561
cwd: .
asked at: 2026-09-28T06:00:32.834071+00:00

## Context

Third boolean makes panel state combinatorial; enum keeps check_action one branch.

## Options

- yes — one self.view, ~10 call sites  (doing)
- no — add answers_open boolean alongside

## Answer

no
answered at: 2026-09-28T06:11:37.924202+00:00
