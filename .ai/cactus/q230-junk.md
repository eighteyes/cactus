# q230 — Purge the two test rows a script wrote into your live inbox?

status: answered
act: ask
kind: confirm
thread: isolation
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T21:31:06.948758+00:00

## Context

Rows id 234 (/tmp/alpha q1) and 235 (/tmp/beta q1), created 20:58Z by .ai/tmp/test_here_strip.py, which calls Store() with no CACTUS_DB. Purge deletes them; the script also gets a scratch-DB guard. Its author is the session behind d4d953f (--here, q213), not this one.

## Options

- yes  (★●)
- no

## Recommendation

yes — high
/tmp/alpha and /tmp/beta are test fixtures, agent t; nothing real lives there

## Answer

yes
answered at: 2026-09-23T21:41:04.346434+00:00
