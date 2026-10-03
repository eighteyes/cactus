# q318 — Commit scope for the footer work?

status: answered
act: ask
kind: choice
thread: footer
agent: 83155dd4-270a-444a-bf43-8d9e8a6dfa37
cwd: .
asked at: 2026-09-25T22:05:35.581916+00:00

## Context

Pre-existing uncommitted diff before this session: README.md, both SKILL.md, cli.py,
and ~200 lines of tui.py not from me. My hunks are interleaved in tui.py, so 'mine'
still carries the earlier tui.py hunks. Default if unanswered: hold.

## Options

- mine — tui.py + CLAUDE.md + .ai/REVIEW.md, one commit (sweeps the earlier tui.py hunks in with it)  (★◐)
- all — every uncommitted file (README, both SKILL.md, cli.py too) in one commit
- hold — leave it uncommitted, you commit

## Recommendation

mine — med
keeps the footer change findable; the other files stay for their own commit

## Answer

mine
answered at: 2026-09-25T23:04:38.375191+00:00
