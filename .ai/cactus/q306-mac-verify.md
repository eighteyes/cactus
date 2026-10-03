# q306 — Does cactus-mac work on a real hotkey press?

status: retired
act: review
kind: confirm
thread: macapp
parent: q297
agent: 83155dd4-270a-444a-bf43-8d9e8a6dfa37
cwd: .
asked at: 2026-09-25T14:45:38.714546+00:00

## Options

- pass
- fail

## Verdicts

look at: .ai/REVIEW.md on branch macapp, steps 2-5. Post the scratch row from a shell with the same CACTUS_DB: CACTUS_DB=/tmp/cactus-mac-smoke.db CACTUS_POKE=true CACTUS_RECORDS=0 cactus ask 'Pick one' -c 'a: first' -c 'b: second' --recommend b --confidence high --why t --agent me
run: cd /Users/god/projects/cactus/.claude/worktrees/agent-a473a1499aecdabca/mac && swift build && CACTUS_DB=/tmp/cactus-mac-smoke.db CACTUS_POKE=true CACTUS_RECORDS=0 nohup ./.build/debug/cactus-mac >/dev/null 2>&1 &
pass: Build complete; ⌥Space toggles a panel listing the scratch row; digit+Enter records the answer
fail: hotkey silent, panel empty with a row on the board, or answer refused
then: merge macapp into cactus-v1, decide q302/q303

- 2026-09-25T16:48:35.224110+00:00: fail
- 2026-09-25T16:48:40.214942+00:00: fail
- 2026-09-25T16:48:57.645689+00:00: fail
- 2026-09-25T16:49:30.651410+00:00: not running
- 2026-09-25T16:55:54.512094+00:00: fail
- 2026-09-25T19:38:23.242424+00:00: pass
- 2026-09-25T21:19:02.120857+00:00: pass
