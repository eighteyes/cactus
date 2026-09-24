# q274 — Package which plugin, for which host?

status: answered
act: ask
kind: choice
thread: package
agent: 1e96990d-81ac-49af-856f-07578b778f56
cwd: .
asked at: 2026-09-24T21:55:05.427276+00:00

## Context

Desktop bundle: needs a manifest.json with a python entry point pointing at bin/cactus-mcp, the src tree, and a zip named cactus.mcpb; the launcher's interpreter hunt already handles Desktop's bare PATH. Claude Code: mostly a version bump plus marketplace.json check. Codex: manifest exists, hooks copied, no launcher yet. Default if unanswered: desktop-mcpb.

## Options

- desktop-mcpb — Claude Desktop extension bundle (.mcpb, ex .dxt) wrapping bin/cactus-mcp plus src/, manifest.json, installable by double-click  (★◐)
- claude-code — the Claude Code plugin already at .claude-plugin + bin + hooks + skills; package means validate and version it for the marketplace
- codex — the Codex plugin under plugins/cactus; package means finish its manifest and bundle

## Recommendation

desktop-mcpb — med
the thread so far is Claude Desktop; a .mcpb bundle is how Desktop installs an MCP server with one click

## Answer

desktop-mcpb
answered at: 2026-09-24T21:55:14.398014+00:00
