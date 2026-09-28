# Cactus on Claude Code

Use the Claude Code plugin from this repository. Its `SessionStart` hook
resolves the Claude conversation identity, rehomes rows after `/clear`, shows
the outstanding frontier, and tells you whether a monitor is running.

Use the exact `--agent` value it prints. Do not substitute a pane id: it can
be inherited by a different conversation.

Arm the once-loop with the Bash tool, `run_in_background`, before the
first row:

    cactus --monitor --json --agent "$AGENT" --once

It exits on the first event for your rows, and that exit wakes you: mid-turn
or hours later on an idle session, with no prompt pending. On every wake,
re-arm it first, then act on the event. The gap between exit and re-arm is
the only window an event can slip through, so `cactus get` the row rather
than trusting the event line alone.

Do not use the Monitor tool for this. It is killed at 30 minutes, and when
the turn has already ended nobody re-arms it, so the inbox goes deaf until
the next prompt.

The Claude plugin's `UserPromptSubmit` and `PermissionDenied` hooks surface
the frontier and turn a denied Bash command into a `cactus run` row. The
`Stop` hook, which holds a turn that left open rows unwatched, is opt-in:
set `CACTUS_STOP_HOOK=1`. Continue to act on every monitor event and
clear rows after acting.
