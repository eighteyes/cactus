# q275 — The Desktop MCP server connects (log: 15 tools announced at 15:19) and the installed launcher answers where/list/ask from a shell. What did you see fail?

status: answered
act: ask
kind: choice
thread: desktop-mcp
agent: 1e96990d-81ac-49af-856f-07578b778f56
cwd: .
asked at: 2026-09-24T22:22:52.015720+00:00

## Context

No cactus tool execution appears in main.log after connect, only claude-in-chrome calls. The plugin is loaded inside a local-agent-mode session (Cowork), which may not expose plugin tools to a plain chat. Default project without CACTUS_PROJECT is /Users/god. Free text with the exact error or the chat you tried helps most.

## Options

- invisible — the cactus tools never show up in the chat's tool list
- errors — Desktop calls a tool and it returns an error (paste the text as free text)
- hang — a tool call spins and never returns
- wrong-project — rows land under /Users/god instead of the repo

## Answer

hang
answered at: 2026-09-24T22:23:44.334780+00:00
