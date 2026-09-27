# Cactus on Claude Code

Use the Claude Code plugin from this repository. Its `SessionStart` hook
resolves the Claude conversation identity, rehomes rows after `/clear`, shows
the outstanding frontier, and tells you whether a monitor is running.

Use the exact `--agent` value it prints. Do not substitute a pane id: it can
be inherited by a different conversation.

Start the foreground monitor before the first row:

    cactus --monitor --json --agent "$AGENT"

When the foreground monitor must end, keep a one-shot waiter in the
background and re-arm the foreground monitor while the user is active:

    cactus --monitor --json --agent "$AGENT" --once

The Claude plugin's `UserPromptSubmit` and `PermissionDenied` hooks surface
the frontier and turn a denied Bash command into a `cactus run` row. The
`Stop` hook, which holds a turn that left open rows unwatched, is opt-in:
set `CACTUS_STOP_HOOK=1`. Continue to act on every monitor event and
clear rows after acting.
