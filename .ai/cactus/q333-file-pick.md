# q333 — Multiple files in the TUI: how to pick one?

status: answered
act: steer
kind: choice
thread: file
agent: 433c9778-c5d1-4246-a98e-904c8b772309
cwd: .
asked at: 2026-09-27T18:45:15.012296+00:00

## Context

Digits 1-9 are already choices/steps/chunks on every row kind, so a bare
digit cannot pick a file. Card shows the file list numbered either way. Pager
is $PAGER (less), editor $EDITOR (vi), CACTUS_PAGER/CACTUS_EDITOR override
and tests set them inert, same pattern as CACTUS_VISIT. Key letters are a
guess until I read the binding table; I will report the final ones.
Default if unanswered: cycle.

## Options

- cycle — f views file 1; repeated f before any other key advances to the next; E edits the same slot  (doing)
- digit-prefix — f then a digit picks the file, like the plan step buffer
- first-only — f/E always act on file 1; the card lists the rest

## Answer

digit-prefix
answered at: 2026-09-27T18:50:49.661104+00:00
