# q341 — Decision records collide after per-project renumbering. Fix now?

status: answered
act: ask
kind: choice
thread: durability
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-28T04:49:16.602557+00:00

## Context

Found while clearing q340: its record overwrote .ai/cactus/q340-grok-wake.md,
a file from an older row that had q340 under the old global numbering
(committed in fb8ca4b). record.py picks up any existing qN-*.md for the
key, so every reused number clobbers history. Rows q338 and q339 were
fresh numbers and did not collide; q340 did.

now: change the record filename to carry the row id; old files stay,
new ones never collide. Small change in record.py plus a test.

Default if unanswered: later.

## Options

- now — records named by row id (qN-id-slug.md), old files left in place
- later — logged in TODO, keep going on the wake-up work  (★◐)

## Recommendation

later — med
history loss is real but rare; Codex probe is the open thread

## Answer

now
answered at: 2026-09-28T04:49:36.707433+00:00
