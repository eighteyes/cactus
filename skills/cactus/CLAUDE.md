# Cactus on Claude Code

Use the Claude Code plugin from this repository. Its `SessionStart` hook
resolves the Claude conversation identity, rehomes rows after `/clear`, and
shows the outstanding frontier.

Use the exact `--agent` value it prints. Do not substitute a pane id: it can
be inherited by a different conversation.

Do not start `cactus --monitor`. `cactus ask` and `cactus run` wait for the
human by default. Post each blocking ask as one backgrounded command (Bash
`run_in_background`), keep working, and treat its exit as the wake-up. A
PreToolUse hook refuses the foreground form. `--no-wait` posts and returns;
those rows, review/plan/data rows and steers are collected with one
backgrounded `cactus get KEY... --wait`. Read a
row with `cactus get KEY --agent "$AGENT"` before acting.

The Claude plugin's `UserPromptSubmit` and `PermissionDenied` hooks surface
the frontier and turn a denied Bash command into a `cactus run` row. The
`Stop` hook holds a turn that posted no ask, edit, plan or review, and
stays silent while the agent already has an `open` row in the project;
`CACTUS_STOP_HOOK=0` turns it off. Clear rows after acting.
