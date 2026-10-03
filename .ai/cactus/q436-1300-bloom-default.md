# q436 — Make lots of bloom clouds the default sky?

status: answered
act: steer
kind: choice
thread: sky
agent: 275c9c71-be9e-42e8-a2ed-98fbafe29278
cwd: .
asked at: 2026-10-01T22:40:39.688056+00:00

## Context

cloud_count now reaches 12 (31b2210). At 30 fps, 8 costs about a third of a core for the sky. Proceeding with keep unless tapped.

## Options

- keep — defaults stay drift at cloud_count 2.2; you set bloom on the T page  (doing)
- bloom — default cloud_style bloom at cloud_count 8 (~79 clouds, ~11 ms a frame at 100x30)

## Answer

bloom
answered at: 2026-10-01T22:50:18.576148+00:00
