# q363 — Cactus field v2: does the desert grow under the question?

status: live
act: review
kind: confirm
thread: field
agent: 6104f97f-6932-4d73-9242-9d2c2ddd509a
cwd: .
asked at: 2026-09-28T18:25:47.744081+00:00

## Files

- /Users/god/projects/cactus/src/cactus/field.py
- /Users/god/projects/cactus/.ai/REVIEW.md

## Options

- pass
- fail

## Verdicts

look at: the 10-row desert under the question text in the card column
run: cactus --tui
pass: seeds fall from the answering key's scaled column, sway, land in front of the mountains, pile into cacti; sky keeps moving; clean quit mid-fall
fail: field above the footer, all seeds from the right edge, seeds through the pile, static sky, traceback on quit
then: follow .ai/REVIEW.md steps 1-11 with the seeded scratch DB

- 2026-09-28T20:27:17.578109+00:00: pass
