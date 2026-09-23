# q165 — How should thread names be scoped?

status: answered
act: ask
kind: choice
thread: isolation
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T16:45:50.795500+00:00

## Context

No live thread is shared by two agents yet. Under agent, list/feed -t match within the caller's --agent; the TUI shows owner beside the thread.

## Options

- agent — a thread belongs to its agent; two agents' -t next are separate threads  (★◐)
- warn — threads stay project-wide; asking into another agent's thread warns
- project — unchanged, project-wide names

## Recommendation

agent — med
thread names like next and fixes collide by default; a human thread spanning agents is rare

## Answer

agent
answered at: 2026-09-23T16:51:17.552800+00:00
