# q446 — Pile colour: replace the 3 age bands with what?

status: answered
act: ask
kind: choice
thread: garden
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-02T04:36:42.425609+00:00

## Context

Today field.py _age_colour: age <34 drops #7ee07e, <100 #3fae3f, else #2a7a2a. Terminal is truecolor (COLORTERM=truecolor), so any hex renders.

Default if unanswered: ramp.

## Files

- /Users/god/projects/cactus/src/cactus/field.py

## Options

- ramp — smooth new→mid→old blend by age, quantised to 32 steps, cached
+ gradual darkening, same three anchor colours
+ cache keeps it cheap (like _fade_tint)
- old cells all converge on one dark green past 100  (★◐)
- ramp+jitter — the ramp plus a small per-cell hue/lightness wobble
+ reads as living texture, not a gradient
- noisier; wobble must be seeded per cell so it never flickers
- lever — ramp, with steps (3..64) and the age span as T-page levers
+ tune it live like the sky
- two more keys on the T page

## Recommendation

ramp — med
fixes the banding with the least new surface

## Answer

lever
answered at: 2026-10-02T05:59:02.140391+00:00
