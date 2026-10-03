# q480 — Text input is one line only. Show a multi-row draft?

status: answered
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-02T22:08:05.836702+00:00

## Context

InputProps has key, label, placeholder, value, submitLabel, autoFocus,
onInput, onSubmit: no rows or multiline. A real multi-line editor would need
a custom Client surface module.

Default if unanswered: draft.

## Options

- draft — as you type, the text wraps in a box of several rows above the
input line; Enter still sends
+ you see the whole answer while typing
- still no newlines inside an answer  (★◐)
- none — leave the single line

## Recommendation

draft — med
closest to multiple rows the API allows

## Answer

draft
answered at: 2026-10-02T23:02:31.786683+00:00
