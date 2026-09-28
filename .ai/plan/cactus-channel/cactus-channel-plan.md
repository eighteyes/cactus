# cactus-channel — plan

Decision q339 (2026-09-27): "both". The once-loop is the wake-up now; a
Claude Code Channel is the follow-up.

## Goal

cactus pushes inbox events into a Claude Code session as `<channel>` blocks,
with no process for the agent to re-arm and no time cap.

## What a channel is

An MCP server that declares `capabilities.experimental["claude/channel"]`
and sends `notifications/claude/channel` with `{content, meta}`. Claude Code
renders each as a `<channel source=NAME k=v>` block in the conversation.
Events queue while the agent is busy and land as a group. Registration is
`.mcp.json` or a plugin; the session opts in with `--channels server:cactus`
at launch. Research preview.

Reference: https://code.claude.com/docs/en/channels-reference.md

## Design

- `src/cactus/channel.py`: runs `monitor.run_monitor`'s diff loop in-process
  with `agent` set, and emits each event as one notification. `meta` carries
  `key`, `event`, `thread`; `content` is the JSON line `--monitor --json`
  prints today, so an agent reads one shape everywhere.
- `mcp.py` gains the capability flag and a background thread that drives
  `channel.py`; one process serves tools and channel. Stay dependency-free.
- Identity: the channel needs the agent id the session-start hook prints.
  Read `CACTUS_AGENT` / herdr env at server start; the hook exports it.
- Sender gating: the only source is the local SQLite file. No inbound path,
  so no allowlist. Do not declare `claude/channel/permission` in v1.
- Launch: plugin `.mcp.json` entry `cactus-channel`; herdr pane recipe adds
  `--channels plugin:cactus@eighteyes-plugins`. Once-loop stays the fallback
  when the flag is absent; the hook detects the channel and skips the
  once-loop instruction.

## Out of scope

- Permission relay through the TUI (later, needs a sender gate).
- Codex, Grok, Desktop: they keep their own wake-up.

## Unknowns to probe first

1. Does a channel notification wake an idle session with no prompt pending?
   Probe: a throwaway channel that emits one line after 20 min, session idle.
2. What `/clear` does to a registered channel and its queue.
3. Whether compaction drops queued events.

## Grade

B. Mechanics documented; the three unknowns are cheap probes before code.
