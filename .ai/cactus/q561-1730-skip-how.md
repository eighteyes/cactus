# q561 — q557 came back skipped: did you press s in the pane, with no bar showing?

status: answered
act: ask
kind: choice
thread: pane-ux
agent: 091b69f0-072f-4f53-a412-b8f0d0706c99
cwd: .
asked at: 2026-10-05T05:29:31.893131+00:00

## Context

The row doesn't record where a skip came from. If it was the s key in the pane with the bar hidden, the probe passed: hidden Buttons keep their hotkeys, and the bar stays gone for good. If it came from the TUI or elsewhere, the probe is still untested.

## Options

- pane — Pressed s in the pane, bar was gone
- elsewhere — Skipped from the TUI or another surface
- bar — The bar was still showing (reload didn't land)

## Answer

s skipped, i have an idea, can we split the question list from the answer display? questions on top, answers on the bottom? no inline card. i feel this wuold give us more options. 
answered at: 2026-10-05T05:31:38.018481+00:00
