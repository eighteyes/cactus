# q432 — Version stamp: what should it be?

status: answered
act: ask
kind: choice
thread: release
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-01T22:34:41.147188+00:00

## Context

Today: 0.1.0 in pyproject.toml, src/cactus/__init__.py, .claude-plugin/plugin.json, marketplace.json (x2), codex plugin.json. No --version flag. No release tags (only field-best).

I'll stamp after the q430 wait-only revert lands, so the tag covers it.

Default if unanswered: minor.

## Options

- minor — 0.2.0 everywhere + `cactus --version` + git tag v0.2.0
+ one number in pyproject, __init__, 3 plugin manifests
+ tag marks the wake/no-monitor rework
- tag is local only (no push)  (★◐)
- sha — 0.2.0 plus the commit, e.g. `0.2.0+c3db875`, shown in --version and the TUI header
+ tells two checkouts apart
- needs git at runtime (falls back to plain 0.2.0)
- tag-only — git tag v0.1.0 on HEAD, no file changes
+ zero code
- nothing in the tool reports it

## Recommendation

minor — med
the workflow changed enough to be a minor; --version makes it visible

## Answer

minor
answered at: 2026-10-01T22:41:15.646130+00:00
