# q339 — Wake-up path: once-loop now proven idle-safe. Once-loop, channel, or both?

status: answered
act: ask
kind: choice
thread: durability
parent: q338
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-27T23:25:17.669304+00:00

## Context

PROVEN JUST NOW: the once-loop woke this session from idle. You hit
'e' on q339 at 19:21, 2.5 h after my last turn, and the background
process exit re-invoked me with no prompt pending. So once-loop
covers the idle case too. Cost: zero cactus code, a hook text change.

WHAT A CHANNEL IS. A Claude Code Channel is an MCP server that Claude
Code keeps running for the whole session. Instead of the agent
polling, the server pushes a message into the conversation whenever
it wants. Claude sees it as a <channel> block, like a user message
but tagged with its source. This is how the official Telegram and
Discord plugins let you text Claude from your phone while it sits
idle.

HOW CACTUS WOULD USE IT. cactus already ships a stdio MCP server
(src/cactus/mcp.py). Add one capability flag and a loop that runs
the same monitor diff and pushes each event as a notification. Each
answered/elaborate/reopened lands in the session as it happens, no
process to respawn, no cap.

WHAT IT COSTS. 1) You launch claude with --channels server:cactus,
so the herdr pane recipe changes. 2) A 'cactus channel' entry point.
3) Research preview: /clear and compaction behavior undocumented, may
shift under us. 4) Two identities to keep aligned: the channel needs
the agent id the hook prints.

WHAT IT BUYS OVER ONCE-LOOP. Nothing for wake-up now that idle wake
is proven. It buys: no respawn step for the agent to forget, events
batched as a group when several land, and a path to relaying
permission prompts through the TUI later.

Default if unanswered: once-loop.

## Options

- once-loop — background Bash 'cactus --monitor --once'; recipe change only, no code
- channel — cactus pushes events into the session via MCP; new verb plus launch flag
- both — once-loop now, channel as a planned follow-up

## Answer

both
answered at: 2026-09-28T02:28:30.661223+00:00
