# q252 — Which hooks should tell the agent to set up the monitor?

status: answered
act: ask
kind: multi
thread: hooks
agent: 5522ebde-0308-4668-bd7e-2cceaa73f09f
asked by: patches
cwd: .
asked at: 2026-09-24T07:09:11.528528+00:00

## Context

Today: SessionStart lists the workflow with a placeholder ID before resolving identity; frontier stays silent until the agent has open rows; Stop reminds only when blocking a turn without an ask. The hooks can check for a live monitor process (frontier already does).

## Options

- start — SessionStart prints a ready-to-run Monitor(command="cactus --monitor --json --agent <resolved id>") as the first instruction  (★◐)
- prompt — the frontier hook reminds on every prompt while no monitor runs, even with no rows
- stop — the Stop hook blocks a turn that ends with open rows and no monitor running  (★◐)

## Recommendation

start, stop — med
start covers setup before the first ask; stop enforces it once rows exist; per-prompt nagging with no rows fires in sessions not using cactus

## Answer

start, stop — answered in chat
answered at: 2026-09-24T07:10:49.645391+00:00
