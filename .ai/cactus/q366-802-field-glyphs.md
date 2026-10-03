# q366 — Field v3: draw the scene with blocks or ASCII?

status: answered
act: steer
kind: choice
thread: field
agent: 6104f97f-6932-4d73-9242-9d2c2ddd509a
cwd: .
asked at: 2026-09-28T20:29:55.791139+00:00

## Context

Blocks: the sub-cell physics is visible, since a half-landed seed shows as a quarter block.
Piles read as rough green mass.

ASCII: shapes read as cactus (stems, tops, arms) but the 2x2 sampling collapses to one
glyph per cell, so the sub-cell resolution shows only as ' and , partials.

Mix: rough green mass on an ASCII sky.

Mono-plus palette and decision-counted ageing (q365) apply to all three. Default if
unanswered: ascii, per the chat message 'use ascii glyphs'.

## Options

- ascii — cactus autotiles from | n v = + o by neighbours, clouds . ~ o by depth, seeds *, ground . ,
- blocks — keep quadrant blocks for the cactus (2x2 sampling shows), clouds ░ ▒ ▓ by depth, seeds ▘-style flecks
- mix — ASCII sky and ground (. ~ o birds v ^), quadrant blocks for cactus and seeds

## Answer

mix — use blocks and ascii?
answered at: 2026-09-28T20:31:32.970035+00:00
