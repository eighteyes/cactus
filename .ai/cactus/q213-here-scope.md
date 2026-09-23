# q213 — What should --here mean for cactus --tui/--watch?

status: answered
act: ask
kind: choice
thread: here
agent: patches-here
cwd: .
asked at: 2026-09-23T19:51:15.512444+00:00

## Context

Today --here scopes to the PROJECT (git toplevel of pwd), not pwd itself (cli.py:860 help: 'scope to the current project only'; main passes project to run_tui/run_watch). Every row stores both project and cwd, so a cwd-based filter is cheap. Your message read as a statement; unclear if it is a bug report, a spec, or a description. Default if unanswered: no change.

## Options

- project — keep current — git toplevel of pwd (docs/help updated if wording misled)  (★○)
- cwd — narrow to rows whose cwd is exactly pwd
- subtree — rows whose cwd is pwd or below it

## Recommendation

project — low
matches current docs; your intent unknown

## Answer

project
answered at: 2026-09-23T20:34:17.960963+00:00
