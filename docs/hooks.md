# Hooks

Every hook cactus ships, for both hosts. Most exit 0 and print nothing when `cactus` is not on PATH or the project is disabled (`cactus project-status --json` reports `"enabled": false`). Exceptions: both SessionStart hooks print a reactivate line on a disabled project, and `pretooluse_wait.py` checks neither.

## Claude

Registered in `hooks/hooks.json`. Scripts live in `hooks/`.

| Event | Script | Prints | Blocks |
|---|---|---|---|
| SessionStart | `session-start.sh` | The required workflow, `Your cactus identity for this session: --agent ID`, a rehome count, open rows for the project. Disabled project: one reactivate line. | Never. |
| UserPromptSubmit | `frontier.sh` | `cactus frontier (--agent ID):`, then elaborate, answered, open/live rows with gist and verdict, a `... N more: cactus list -s any --agent ID` line past the cap, then a counts line. | Never. |
| PreToolUse (Bash) | `pretooluse_wait.py` | `cactus ask/run waits for the human by default; rerun with run_in_background: true. Its exit wakes you.` | Exit 2 on a foreground `cactus ask` or `cactus run` that would wait. |
| PermissionDenied (Bash) | `permission-denied.sh` | Nothing. Posts the denied command as `cactus run CMD --no-wait -t denied`, once per `tool_use_id` (deduped in `$XDG_STATE_HOME/cactus/denied-ID`). | Never. |
| Stop | `stop-fork.sh` | `{"decision":"block","reason":"the turn ended without a fork; ..."}` | See Stop below. |

**SessionStart.** Resolves identity, then runs `cactus rehome --agent ID` to move rows this pane posted under a previous identity. Rehome needs both `HERDR_PANE_ID` and `HERDR_SESSION`; outside herdr it does nothing. No identity: prints a line asking the agent to pick one stable `--agent`.

**UserPromptSubmit.** Lists `cactus list -s any --agent ID --json`, capped at `CACTUS_FRONTIER_MAX` rows (default 5). Silent without `jq`, when no identity resolves, or when the agent has no rows.

**PreToolUse.** Allows the call when `jq` is missing, `tool_input.run_in_background` is true, or the raw command string carries `--no-wait`, `--no-block`, or `--act steer|notify|review|plan|data` anywhere, quoted or heredoc text included. Matches `cactus ask|run` at command position only; that match skips heredoc bodies and quoted text.

**Stop.** In order:

1. `CACTUS_STOP_HOOK=0`: exit 0 before reading stdin. No `cactus` on PATH: exit 0.
2. Project disabled: exit 0.
3. Identity resolves and `cactus list -s open --agent ID --json` has length > 0: exit 0. The agent already has a row waiting on the human (q469). `live` and `elaborate` rows do not count. No identity: step skipped.
4. Payload not JSON, `stop_hook_active` set, no `transcript_path`, or transcript unreadable: exit 0.
5. Turn opened by a task-notification or a cross-session message: exit 0.
6. Turn contains an AskUserQuestion call, or a Bash command whose text contains `cactus ask|edit|plan|review` (or `cac ...`) anywhere, quoted or heredoc text included: exit 0.
7. Otherwise: print the block decision.

### Identity

`hooks/identity.sh` resolves `--agent` for every Claude hook. Order:

1. `session_id` from the hook payload.
2. herdr's view of the pane, when `HERDR_PANE_ID` is set (`c100-identity --resolve`, else `herdr agent get`).
3. `CACTUS_AGENT`.

The payload wins: after `/clear`, herdr still reports the previous conversation's id (q327). Each hook that sources `identity.sh` reads stdin into `input` first.

## Codex

Registered in `plugins/cactus/hooks/hooks.json`. Scripts live in `plugins/cactus/hooks/`. Identity is the payload's `session_id` only. Every script exits 0 silently without `cactus`, `jq`, or a `session_id`.

| Event | Script | Prints | Blocks |
|---|---|---|---|
| SessionStart | `session-start.sh` | See below. | Never. |
| UserPromptSubmit | `frontier.sh` | The mod-mode line whenever `cactus list -s any` returns any rows, cleared included. Then, when elaborate/answered/open/live rows exist: `cactus frontier (--agent ID):`, the first 5 with each row's full latest answer, counts, and with open rows a `Codex has no wake-up from idle ... cactus get KEY --wait --timeout 300 --json` line. | Never. |
| PermissionRequest (Bash) | `permission-request.sh` | Posts `cactus run CMD --no-wait`, then a `hookSpecificOutput` deny: `Cactus approval KEY was opened. Wait for its answer before retrying.` | Denies the request. |
| Stop | `stop.sh` | Nothing. | Never. |

**SessionStart** prints, in order:

1. Disabled project: `Cactus is disabled for this project. ...`, then exits.
2. Inside herdr (`HERDR_PANE_ID` set): runs `cactus deliver herdr --agent ID` and prints `Cactus registered herdr delivery for ID: answers prompt this pane.`
3. `Cactus is available. Use --agent ID for every Cactus row.`
4. `Cactus mod mode is active: post asks and runs with --no-wait; ...`
5. `Open Cactus rows for this Codex session:` and the rows, when any.

**UserPromptSubmit** also runs `cactus clear KEY --agent ID` on each answered row it printed, except `review`, `plan`, and `data` rows. Rows past the first 5 are not cleared. Detail: [codex-mod-mode.md](codex-mod-mode.md).

**Stop.** `CACTUS_STOP_HOOK=0` exits before reading stdin. Codex has no wake from idle, so the hook never blocks.

Delivery registration: [delivery.md](delivery.md).

## Environment

| Variable | Host | Effect |
|---|---|---|
| `CACTUS_STOP_HOOK` | both | `0` disables the Stop hook. On by default. |
| `CACTUS_AGENT` | Claude | Last-resort `--agent` in `identity.sh`. |
| `HERDR_PANE_ID` | both | Claude: enables the herdr identity tier (also needs `herdr` on PATH); with `HERDR_SESSION`, gates `cactus rehome`. Codex: SessionStart registers herdr delivery. |
| `HERDR_SESSION` | Claude | With `HERDR_PANE_ID`, gates `cactus rehome`. |
| `CACTUS_FRONTIER_MAX` | Claude | Rows `frontier.sh` lists. Default 5. |
