# Cactus for Codex

This plugin is the Codex equivalent of the Cactus pane mod, within the
capabilities Codex currently exposes.

## What it does

- The `cactus` skill supplies the mod-mode workflow: every decision goes to
  `cactus ask --no-wait --agent <session-id>` and the agent never starts a
  background Cactus waiter.
- The trusted `SessionStart` and `UserPromptSubmit` hooks inject that workflow
  and the current Cactus frontier into the agent context.  The frontier shows
  the full latest answer and automatically clears non-persistent answered or
  skipped rows after delivering it to the next turn.
- In a Herdr-managed session, `SessionStart` registers `cactus deliver herdr`
  for the Codex session.  That is an optional external wake route.

## Deliberate capability boundary

Codex does not currently expose a verified rendered MCP App surface for this
local plugin, or an API that lets a lifecycle hook start an idle Codex turn.
Consequently this package does **not** try to ship a non-functional pane or a
polling daemon.  The human continues to use the existing Cactus CLI/TUI,
including `cactus feed --json --here`; the agent receives the equivalent
frontier at the next prompt.  Herdr can wake a Herdr-backed terminal session,
but it is not a native Codex wake capability.

## Load locally

The repository marketplace already points at this package.  Trust its hooks,
then install or refresh it with:

```sh
codex plugin add cactus@cactus-local
```

Start a new Codex thread after installing so it loads the revised skill and
hook definitions.
