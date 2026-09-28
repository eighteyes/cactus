# cactus-channel — context

## Key files

- src/cactus/mcp.py — existing stdio MCP server, dependency-free JSON-RPC;
  each tool is one `cactus --json` subprocess.
- src/cactus/monitor.py — `run_monitor`, `_snapshot`, `_signature`,
  `_OWN_ECHO`; the diff loop the channel reuses.
- hooks/session-start.sh — prints the once-loop recipe; must detect a
  channel and skip it.
- skills/cactus/CLAUDE.md — Claude host recipe.
- plugins/cactus/.mcp.json — where the channel server registers.

## Decisions

- q338/q339: once-loop is the wake-up now; channel is the follow-up.
- q334: `--agent` streams never echo `asked` or `edited`; the channel
  inherits that filter.
- Probes 2026-09-27: background Bash lived 35 min; an idle session woke 2.5 h
  after its last turn when the once-loop exited. So the channel buys
  convenience (no re-arm, batched events), not durability.

## Facts from docs

- Notification method `notifications/claude/channel`, params
  `{content: string, meta?: Record<string,string>}`; `meta` keys become tag
  attributes, hyphens dropped.
- Session opt-in: `--channels plugin:NAME@MARKETPLACE` or
  `--channels server:NAME`; dev: `--dangerously-load-development-channels`.
- Org gates: `channelsEnabled`, `allowedChannelPlugins`.
- Undocumented: idle wake, `/clear`, compaction, lifetime cap.
