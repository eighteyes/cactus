# q337 — Commit scope for --file?

status: answered
act: steer
kind: choice
thread: file
agent: 433c9778-c5d1-4246-a98e-904c8b772309
cwd: .
asked at: 2026-09-27T19:18:29.073787+00:00

## Context

The tree was dirty before I started: cli.py, store.py, hooks/*, both plugin
hook sets, README, SKILL.md, and .ai/cactus records. monitor.py gained an
open_ids change during this session that no agent of mine wrote. --file adds
~800 lines across 15 files and its hunks interleave with that work in cli.py
and store.py, so split means I stage by hunk and re-run the suite on the
staged tree. Default if unanswered: split.

## Options

- split — commit only the --file hunks; leave the stray work (monitor open_ids, cmd_projects, hooks, .ai/cactus records) uncommitted  (doing)
- sweep — one commit of everything dirty under src/ tests/ docs, stray work included
- hold — do not commit, leave it all in the tree

## Answer

sweep
answered at: 2026-09-27T19:24:36.202950+00:00
