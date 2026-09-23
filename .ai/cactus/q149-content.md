# q149 — What should the UserPromptSubmit frontier show?

status: answered
act: ask
kind: multi
thread: frontier
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T16:07:00.698086+00:00

## Context

Injected as context each time you submit a prompt. Identity comes from the same pane-to-session resolution the session-start hook uses.

## Options

- mine — my open rows and my answered rows not yet cleared (acted on)  (★◐)
- project — open rows from every agent in this project
- counts — one line of totals only  (★◐)

## Recommendation

mine, counts — med
answered-not-cleared is exactly what I miss when you answer while I sleep; others' rows stay one number

## Answer

counts, mine
answered at: 2026-09-23T16:10:16.226235+00:00
