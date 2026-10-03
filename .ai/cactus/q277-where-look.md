# q277 — Where are you looking when the cactus connector 'doesn't land'? The server itself connects every time (log 15:30:08: 15 tools announced); Desktop's web layer throws 'Not found' 7s later.

status: answered
act: ask
kind: choice
thread: desktop-mcp
agent: 1e96990d-81ac-49af-856f-07578b778f56
cwd: .
asked at: 2026-09-24T22:33:04.902012+00:00

## Context

Bridge code announces plugin MCP tools to claude.ai as session_type cowork-remote, so they may only surface inside Cowork, not plain chat. The classic mcpServers entry in claude_desktop_config.json never connected either in the logs. Free text: paste what the UI shows.

## Options

- connectors-list — Settings > Connectors or the chat's tool picker never shows cactus
- chat-call — a normal chat says it has no cactus tools or the call errors
- cowork — a Cowork session cannot see or call the tools

## Answer

connectors-list
answered at: 2026-09-24T22:34:16.159455+00:00
