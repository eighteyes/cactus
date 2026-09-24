# q251 — Should the plugin ship its own cactus CLI in bin/?

status: answered
act: ask
kind: choice
thread: publish
agent: 5522ebde-0308-4668-bd7e-2cceaa73f09f
asked by: patches
cwd: .
asked at: 2026-09-24T05:45:21.990005+00:00

## Context

Docs: a plugin's bin/ is put on PATH for Bash calls and hooks while enabled. Verified: ask/get run on a Python without textual. Risk: a uv-installed cactus and the plugin's copy can differ in version against one database; which one wins on PATH is undocumented. Needs python3 >= 3.11 on PATH.

## Options

- bundle — bin/cactus runs the plugin's own src with python3; agents need no install; --tui/--watch use uvx with textual when uv exists, else say to install  (★◐)
- separate — keep requiring uv tool install for everyone

## Recommendation

bundle — med
agents work the moment the plugin is enabled; the human's TUI is the only part needing textual

## Answer

bundle
answered at: 2026-09-24T06:18:57.214292+00:00
