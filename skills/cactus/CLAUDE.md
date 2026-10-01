# Cactus on Claude Code

Use the Claude Code plugin from this repository. Its `SessionStart` hook
resolves the Claude conversation identity, rehomes rows after `/clear`, and
shows the outstanding frontier.

Use the exact `--agent` value it prints. Do not substitute a pane id: it can
be inherited by a different conversation.

Do not start `cactus --monitor`. Post rows, keep working, and let any
background work finish. On your next turn, the frontier lists answered or
elaborated rows; read them with `cactus get KEY --agent "$AGENT"` before
acting. This deliberately avoids treating a background process as an idle
session wake-up.

The Claude plugin's `UserPromptSubmit` and `PermissionDenied` hooks surface
the frontier and turn a denied Bash command into a `cactus run` row. The
`Stop` hook holds a turn that posted no ask; `CACTUS_STOP_HOOK=0` turns it
off. Clear rows after acting.
