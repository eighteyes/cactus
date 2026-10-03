# q359 — Cactus field: does the strip grow when you answer?

status: live
act: review
kind: confirm
thread: field
agent: 6104f97f-6932-4d73-9242-9d2c2ddd509a
cwd: .
asked at: 2026-09-28T06:47:53.890566+00:00

## Options

- pass
- fail

## Verdicts

look at: the 6-row green strip above the footer
run: cactus --tui
pass: each 1/y/n/s/d answer drops a bright block from that key's footer column; it falls, turns green, sticks beside or on top of earlier blocks
fail: no strip, block drops from the wrong column, blocks pass through each other, or a traceback on quit
then: answer a dozen rows and see whether the piles look like cacti; report what feels off

- 2026-09-28T16:10:34.841101+00:00: i want the field to grow underneath the question. all blocks seem to fall from the right of the screen. i also want it to be more... physics / rough. like a block exists in a higher resolution space then the grid, the grid just downsamples it.
- 2026-09-28T16:10:41.368499+00:00: pass
