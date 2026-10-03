# q441 — Responsiveness: run the field in its own process?

status: answered
act: steer
kind: choice
thread: sky
agent: 275c9c71-be9e-42e8-a2ed-98fbafe29278
cwd: .
asked at: 2026-10-01T22:59:35.360466+00:00

## Context

The profiler measures keypress latency and prototypes both before any build. Tests keep an in-process mode. Proceeding with process unless tapped or the numbers say otherwise.

## Options

- process — the field simulates and renders in a separate process; the TUI only paints frames and handles keys  (doing)
- thread — a background thread; simpler, but Python's lock still makes it compete with key handling

## Answer

process
answered at: 2026-10-01T23:26:41.182421+00:00
