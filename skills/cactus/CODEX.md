# Cactus on Codex

Use the Codex plugin packaged under `plugins/cactus`. Its hooks use the Codex
hook event's `session_id` as the Cactus owner identity. Pass that exact value
on every `ask`, `edit`, and `clear`; it is session-scoped and avoids handing
rows to a later agent in the same terminal.

The SessionStart hook injects the resolved command. Start the monitor before
your first row and keep it alive while rows are open:

    cactus --monitor --json --agent "$AGENT"

If the execution environment cannot keep a foreground process alive, use a
re-armed one-shot waiter or configure a webhook owner as described in
[GROK.md](GROK.md). Do not pretend a monitor is running when it is not.

Codex hooks provide the frontier at `UserPromptSubmit` and, with
`CACTUS_STOP_HOOK=1`, check open rows at `Stop`. A `PermissionRequest` hook can post a durable `cactus run` approval
row before it declines the transient Codex approval request. After an
approved row wakes you, re-read its result before running anything.

Plugin hooks are not trusted automatically: review and trust the plugin hook
definition after installation.
