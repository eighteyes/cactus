# q440 — Performance: how far may the fix go?

status: answered
act: steer
kind: choice
thread: sky
agent: 275c9c71-be9e-42e8-a2ed-98fbafe29278
cwd: .
asked at: 2026-10-01T22:59:03.015106+00:00

## Context

A profiler is measuring your live config at 6/15/30 fps now. numpy would be the cactus package's first heavy dependency. Proceeding with pure unless tapped; the numbers come back before any numpy decision.

## Options

- pure — pure-Python and Textual fixes only; the look stays identical; no new dependency  (doing)
- numpy — also allow numpy for the sky's composite and downsample if the profile shows a big win

## Answer

numpy
answered at: 2026-10-01T23:26:28.678156+00:00
