# q387 — --file already exists: ask/edit/review/plan store absolute paths; the card lists them; f opens a pager, F an editor. What's missing?

status: answered
act: ask
kind: multi
thread: files
agent: ddd377dd-f47a-4a88-8a04-417e8b3f2561
cwd: .
asked at: 2026-09-29T05:18:33.646805+00:00

## Context

Today only the path is stored. Nothing stops the file from changing between ask and answer.

## Options

- capture — snapshot content at ask time, so the human sees what the agent meant even if the file changes or vanishes  (★◐)
- inline — preview the file's head inside the card, no pager hop  (★◐)
- diff — show changes since capture when the file changed
- www — files on the web board too

## Recommendation

capture, inline — med

## Answer

diff, inline
answered at: 2026-09-29T18:29:58.681890+00:00
