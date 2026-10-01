# Cactus on Claude Code

Use the Claude Code plugin from this repository. Its `SessionStart` hook
resolves the Claude conversation identity, rehomes rows after `/clear`, and
shows the outstanding frontier.

Use the exact `--agent` value it prints. Do not substitute a pane id: it can
be inherited by a different conversation.

Under herdr, answering a row prompts your pane: nothing to arm. Keep
working and act on each wake; read the row with `cactus get KEY --agent
"$AGENT"` first.

Outside herdr (no pane, no webhook) arm the once-loop with Bash
`run_in_background`:

    cactus --monitor --json --agent "$AGENT" --once

Its exit wakes you, even from an idle session. Re-arm it first thing on every
wake, then `cactus get` the row; the exit-to-re-arm gap is the one window an
event can slip through. Do not use the Monitor tool: its 30-minute cap dies
unattended.

`cactus ask` and `cactus run` also wait for the human by default. Post each
blocking ask as one backgrounded command (Bash `run_in_background`); its exit
is a wake too. A PreToolUse hook refuses the foreground form. `--no-wait`
posts and returns.

The Claude plugin's `UserPromptSubmit` and `PermissionDenied` hooks surface
the frontier and turn a denied Bash command into a `cactus run` row. The
`Stop` hook holds a turn that posted no ask, edit, plan or review;
`CACTUS_STOP_HOOK=0` turns it off. Clear rows after acting.
