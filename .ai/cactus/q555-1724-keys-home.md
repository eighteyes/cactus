# q555 — Action bar: where should the keys live?

status: answered
act: ask
kind: choice
thread: pane-ux
agent: 091b69f0-072f-4f53-a412-b8f0d0706c99
cwd: .
asked at: 2026-10-05T05:25:19.068751+00:00

## Context

Why it's at the bottom: arrows are focus steps with no direction, and a deny holds the ring in place instead of skipping. With keys inside the open card, a down arrow from the current header lands on its first key, gets denied, and stays stuck. Keys below the last question move that dead end to the bottom of the list, where it does no harm. Hotkeys (digits, s/e/c...) only work while a Button carries them, so the keys can't be plain text.

## Files

- /Users/god/ai/mods/cactus-pane/hooks/register.tsx

## Options

- card — Keys back inside the card under the question. Arrows stop at the open card; j/k move past it.
+ keys sit with their question
- down arrow dead-ends at the open card
- tidy — Keep them below, but as one dim line: choices first, rare keys (break up, undo, up/down) dropped or folded.
+ arrows stay header-to-header
- keys still far from the question
- probe — Check whether a Button can be hidden or zero-width and still take its hotkey, then show keys as a text legend in the card.
+ could get both
- unknown, may not exist  (★◐)

## Recommendation

probe — med

## Answer

probe
answered at: 2026-10-05T05:25:43.131423+00:00
