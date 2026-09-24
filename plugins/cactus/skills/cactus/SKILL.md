---
name: cactus
description: Ask the human without stopping work. Use Cactus to park a decision, request approval for a command, announce a default that can be redirected, or keep a review or plan on the human's board. Do not use it when the answer is required immediately and no safe default exists.
---

# Cactus for Codex

Cactus is a durable SQLite inbox. Post a row, continue useful work, and act
when the user answers. Read `cactus --agent-help` once per session for the
full CLI reference.

## Identity and monitor

The bundled hooks use Codex's hook-event `session_id` as the Cactus owner.
Use the `AGENT` value injected at session start on every `ask`, `edit`, and
`clear`; do not replace it with a terminal pane id.

Before the first row, start and retain a monitor while your rows are open:

    cactus --monitor --json --agent "$AGENT"

If the host cannot retain a monitor, use a re-armed `--once` waiter or a
per-agent webhook. Never assume an answer will reach you without one.

## Required workflow

1. Post every later decision as `cactus ask ... --agent "$AGENT"`.
2. Prefer `--act steer --chosen` when a safe default lets work continue.
3. Use `cactus run CMD --agent "$AGENT" --why ...` for a command awaiting
   approval; after approval, read the row result before running anything.
4. On `answered`, `elaborate`, `reopened`, or `cleared`, re-read the row and
   act on the new state.
5. Clear your own row after acting.

Use two or three mutually exclusive options; include the real trade-off in
`--context`. Add `--recommend LABEL --confidence low|med|high` when you have a
preference. Do not use a generic chat question for a decision Cactus can hold.

The `UserPromptSubmit` hook injects your outstanding frontier. The `Stop` hook
continues the turn when rows are open without a monitor. The `PermissionRequest`
hook converts an approval-needed Bash command into a Cactus run row and denies
the transient request so the durable inbox remains the approval surface.
