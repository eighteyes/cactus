# q280 — Add a README section for non-Claude agents (Codex, Grok)?

status: answered
act: ask
kind: choice
thread: publish
agent: 5522ebde-0308-4668-bd7e-2cceaa73f09f
asked by: patches
cwd: .
asked at: 2026-09-24T22:54:19.345231+00:00

## Context

Codex reads AGENTS.md and configures MCP servers in ~/.codex/config.toml; I would verify both formats against current docs before writing. Grok's CLI MCP support is unverified. No Stop/frontier hooks exist for them, so the workflow snippet carries the monitor rule.

## Options

- add — CLI and MCP setup, an AGENTS.md workflow snippet, --agent choice without a Claude session id, polling without a monitor tool  (★◐)
- skip — README stays Claude-first

## Recommendation

add — med
they get the CLI and MCP today but nothing teaches the workflow; the skill and hooks are Claude-only

## Answer

add
answered at: 2026-09-24T22:54:45.096341+00:00
