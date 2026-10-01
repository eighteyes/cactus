# Cactus on Codex

Use the Codex plugin packaged under `plugins/cactus`. Its hooks use the Codex
hook event's `session_id` as the Cactus owner identity. Pass that exact value
on every `ask`, `edit`, and `clear`; it is session-scoped and avoids handing
rows to a later agent in the same terminal.

Codex has no wake-up from idle. A background command's completion is
delivered at your next model request, not as a new turn, so a `--once`
waiter that exits while the session is idle wakes nobody (probed q342,
2026-09-27). Do not arm one and claim to be listening.

Answers reach you on the next turn: the `UserPromptSubmit` frontier hook
lists every answered-but-unacted row when the human next prompts you. Act
on those first. Inside a turn, when the very next step needs the answer,
block on the row in the foreground with a timeout under Codex's shell
limit (about 366 seconds):

    cactus get KEY --wait --timeout 300 --json

For a blocking structured choice in an ACP-capable Codex client, ask through
the ACP bridge instead. It turns the elicitation into a Cactus row marked
`BLOCKING · ACP` at the top of the board, holds the ACP request while the
human answers, and returns that answer as the response that resumes the
session. Use native `cactus ask` for durable, async, or richer Cactus work.

Never run `cactus --monitor` without `--once` here: it is a stream that
returns only when killed.

Codex hooks provide the frontier at `UserPromptSubmit`; the `Stop` hook never
blocks. A `PermissionRequest` hook can post a durable `cactus run` approval
row before it declines the transient Codex approval request. After an
approved row wakes you, re-read its result before running anything.

Plugin hooks are not trusted automatically: review and trust the plugin hook
definition after installation.
