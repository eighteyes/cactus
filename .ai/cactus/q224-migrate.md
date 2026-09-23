# q224 — Migrate the live inbox to per-project keys now?

status: answered
act: ask
kind: choice
thread: isolation
agent: w3B:p1
asked by: patches
cwd: .
asked at: 2026-09-23T20:42:14.550240+00:00

## Context

Until migrated, ask keeps global numbering; nothing is broken. Live now: 4 cactus TUIs and one agent monitor (rca-robot-bands). The rebuild swaps UNIQUE(key) for UNIQUE(project, key) and keeps every row and id. Anything still running afterwards must restart. Backup: sqlite3 .backup to a dated copy first.

## Options

- me — you quit the 4 TUIs; I back up the db, run cactus migrate --yes, and verify  (★◐)
- you — you run it yourself
- defer — keep global numbering for now; per-project stays dormant

## Recommendation

me — med
the rebuild is lossless and tested; the risk is only live processes, which quitting the TUIs removes

## Answer

Yes, you quit the tuis, and do the mig
answered at: 2026-09-23T20:50:52.311564+00:00
