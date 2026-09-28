# Cactus on Codex

Use the Codex plugin packaged under `plugins/cactus`. Its hooks use the Codex
hook event's `session_id` as the Cactus owner identity. Pass that exact value
on every `ask`, `edit`, and `clear`; it is session-scoped and avoids handing
rows to a later agent in the same terminal.

The SessionStart hook injects the resolved command. Arm the once-loop as a
background command before your first row:

    cactus --monitor --json --agent "$AGENT" --once

It exits on the first event for your rows, and that exit is the wake-up. On
every wake, re-arm it first, then act on the event. Never run it in the
foreground: without `--once` it is a stream that returns only when killed.

If the execution environment cannot keep a background command alive across
turns, configure a webhook owner as described in [GROK.md](GROK.md). Do not
pretend a waiter is armed when it is not.

Codex hooks provide the frontier at `UserPromptSubmit` and, with
`CACTUS_STOP_HOOK=1`, check open rows at `Stop`. A `PermissionRequest` hook can post a durable `cactus run` approval
row before it declines the transient Codex approval request. After an
approved row wakes you, re-read its result before running anything.

Plugin hooks are not trusted automatically: review and trust the plugin hook
definition after installation.
