# q380 — Field v6: one fluid or three?

status: answered
act: steer
kind: choice
thread: field
agent: 6104f97f-6932-4d73-9242-9d2c2ddd509a
cwd: .
asked at: 2026-09-28T22:46:15.042419+00:00

## Context

One grid at braille-pixel resolution stays inside the frame budget in pure Python.
Three costs three times as much and the layers cannot interact. Proceeding with one.

## Options

- one — a single air grid; wind shear by height gives parallax, height gives haze  (doing)
- three — three independent grids at far/mid/near, composited front to back

## Answer

3, i'm thinking our game needs some levers to help me dial it in
answered at: 2026-09-28T22:48:36.046466+00:00
