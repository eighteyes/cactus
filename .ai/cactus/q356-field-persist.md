# q356 — Cactus field: persist across TUI restarts?

status: answered
act: steer
kind: choice
thread: field
agent: 6104f97f-6932-4d73-9242-9d2c2ddd509a
cwd: .
asked at: 2026-09-28T06:10:11.923016+00:00

## Context

'Build up all day' reads as persistent. File beside the DB (CACTUS_DB dir), so a
scratch DB in tests gets a scratch field. Proceeding with file.

## Options

- file — one JSON grid in the cactus data dir, all projects share it  (doing)
- session — in memory only, empty on every launch

## Answer

session
answered at: 2026-09-28T06:13:03.587357+00:00
