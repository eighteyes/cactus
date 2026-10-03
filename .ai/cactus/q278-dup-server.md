# q278 — Desktop now runs cactus twice: the classic connector from claude_desktop_config.json and the plugin's .mcp.json server. Same 15 tools, two copies. Keep which?

status: answered
act: ask
kind: choice
thread: desktop-mcp
agent: 1e96990d-81ac-49af-856f-07578b778f56
cwd: .
asked at: 2026-09-24T22:36:18.971056+00:00

## Context

Log shows the classic connector is the one a plain chat called (pid 40908: where, feed). The plugin's server (pid 40874) connected too but only Cowork routes to it. Removing the manual entry means plain chat loses cactus unless the plugin route also serves chat, which the earlier 'Not found' suggests it may not. If unanswered: both stays as is.

## Options

- plugin — I remove the manual cactus entry from claude_desktop_config.json (backup kept)  (★◐)
- manual — keep the config entry, you uninstall the plugin's server or the plugin
- both — leave it, accept duplicate tool names

## Recommendation

plugin — med
the plugin is the packaged artifact you asked for and carries the skill; the manual entry was my earlier stopgap

## Answer

plugin
answered at: 2026-09-24T22:36:48.021718+00:00
