# q494 — --site URL on ask/edit; TUI w opens it via 'open', www board shows it as a link

status: answered
act: steer
kind: choice
thread: site
agent: 0f4be69e-67e5-485b-a467-0d31810683ad
cwd: .
asked at: 2026-10-03T04:39:25.024522+00:00

## Context

Plan: additive `site` column, http(s) only, `edit --site ""` clears.
CACTUS_OPEN overrides the opener (tests inert). Card + get text show `site: URL`;
feed/get --json carry "site"; MCP cactus_ask/edit take it.

## Options

- row-url — w opens the row's own --site URL in the browser
+ agent points the human at a PR, dashboard, preview  (doing)
- board — w opens the cactus www board itself, focused on this row
- not what --site carries

## Answer

row-url
answered at: 2026-10-03T04:41:58.196492+00:00
