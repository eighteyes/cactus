---
name: cactus
description: Ask the human without stopping work. Use Cactus to park a decision, request approval for a command, announce a default that can be redirected, or keep a review or plan on the human's board. Do not use it when the answer is required immediately and no safe default exists.
---

# Cactus for Codex

Cactus is a durable SQLite inbox. Post a row, continue useful work, and act
when the user answers. Read `cactus --agent-help` once per session for the
full CLI reference.

## Identity and waiting

The bundled hooks use Codex's hook-event `session_id` as the Cactus owner.
Use the `AGENT` value injected at session start on every `ask`, `edit`, and
`clear`; do not replace it with a terminal pane id.

Codex has no wake-up from idle, and `cactus ask` and `cactus run` wait for
the human by default, which blocks Codex. Post with `--no-wait`; answers
reach you on the next turn through the frontier hook. When the very next
step needs an answer, block in the foreground under Codex's shell limit:

    cactus get KEY --wait --timeout 300 --json

Do not arm a monitor or a `--once` waiter: one that exits while the session
is idle wakes nobody.

## Required workflow

1. Post every later decision as `cactus ask ... --no-wait --agent "$AGENT"`, with
   `-f PATH` for each file the question is about.
2. Prefer `--act steer --chosen` when a safe default lets work continue.
3. Use `cactus run CMD --no-wait --agent "$AGENT" --why ...` for a command awaiting
   approval; after approval, read the row result before running anything.
4. On `answered`, `elaborate`, `reopened`, or `cleared`, re-read the row and
   act on the new state.
5. Read a review or plan row with `cactus get KEY --agent "$AGENT"`: that read
   tells the human you heard their verdict. After acting on it, respond through
   `plan`, `review`, or `edit` with `--agent "$AGENT"`.
6. Clear your own row after acting.

When an elaborate instruction asks to decompose a complex row, post several
smaller, independently answerable follow-ups with `-p ORIGINAL_KEY`, then
clear the original row. Do not edit it back into one question.

Use two or three mutually exclusive options; include the real trade-off in
`--context`. Add `--recommend LABEL --confidence low|med|high` when you have a
preference. Do not use a generic chat question for a decision Cactus can hold.

Format a question for an 80-column terminal: two or three rendered lines are
fine, but no more. Cactus warns after an ask or edit that wraps past three
lines; decompose a larger decision into follow-ups. Hard-wrap context and
choice descriptions at 80 columns and keep choice labels short.

`-f PATH` attaches a file. Attach every file the question is about: the plan,
spec, diff, config, or draft the human would otherwise have to go find. They
open it from the card with `f` (view) or `F` (edit), or preview it inline
with `o` (a diff vs git HEAD when changed). Repeat for more;
`edit -f` replaces the list. A row about a file with no `-f` is a row the
human answers blind.

The `UserPromptSubmit` hook injects your outstanding frontier. The `Stop` hook
never blocks. The `PermissionRequest`
hook converts an approval-needed Bash command into a Cactus run row and denies
the transient request so the durable inbox remains the approval surface.
