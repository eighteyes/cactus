# Interfaces

Every surface cactus exposes: CLI, delivery map, HTTP board, MCP tools, hooks.
Each row cites its definition site. No OpenAPI, proto or JSON-schema file exists; the code is the spec.

**Exit codes** (`src/cactus/cli.py:30`)

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | error; argparse usage errors too (`src/cactus/cli.py:1617`) |
| 2 | `--wait` timed out |
| 3 | no match: missing key, empty result, already answered. One stderr line `cactus: no match` on empty results (`src/cactus/cli.py:299`) |

Errors print one stderr line, `cactus: <reason>`.

## CLI

Entry points `cactus`, `cac` -> `cactus.cli:main`; `cactus-mcp` -> `cactus.mcp:main` (`pyproject.toml:17`).
`--json` works before or after the verb. `KEY` is `qN`, `LABEL:qN` or `/abs/path:qN`.

**Global flags.** `--tui`, `--watch`, `--www`, `--monitor` are mutually exclusive: two or more exit 1, `cactus: --tui and --watch are mutually exclusive` (`src/cactus/cli.py:1944`). `--db`, `--agent-help`, `--version` combine freely.

| Invocation | Does | Errors | Site |
|---|---|---|---|
| `cactus --tui [--here]` | human answering TUI | exit 1 when stdout is not a tty | `src/cactus/cli.py:1637` |
| `cactus --watch [--here]` | read-only feed | exit 1 when stdout is not a tty | `src/cactus/cli.py:1638` |
| `cactus --www [--host H] [--port P] [--open] [--here]` | HTTP board, default `127.0.0.1:8642` | see HTTP | `src/cactus/cli.py:1639` |
| `cactus --monitor --agent ID [--all] [--replay] [--once] [--interval S] [--workspace W] [--tab T] [--pane P]` | one stdout line per row change | exit 1 without `--agent` | `src/cactus/cli.py:1644` |
| `cactus --agent-help` | prints the agent reference | — | `src/cactus/cli.py:1663` |
| `cactus --db PATH` | database path (else `CACTUS_DB`) | exit 1 on empty `CACTUS_DB` | `src/cactus/cli.py:1636` |
| `cactus --version` | prints `cactus VERSION`, exit 0 | — | `src/cactus/cli.py:1662` |

**Verbs**

| Verb | Inputs | Output | Errors | Site |
|---|---|---|---|---|
| `ask TEXT` | `-c LABEL[: DESC]`..., `--act ask\|steer\|run\|notify\|review\|plan\|data`, `--agent ID` (required), `--by ID` (default `CACTUS_AGENT`), `--multi`, `--confirm`, `--kind`, `--recommend L --confidence low\|med\|high`, `--why`, `--chosen`, `--blocked\|--no-block`, `--no-free`, `-t`, `-p`, `--context`, `--word`, `--title`, `-f PATH`..., `--site URL`, `-w\|--no-wait`, `--timeout S` | key, then the answer once given (blocking acts wait by default, 3600 s) | 1 on refusal; 2 on timeout | `src/cactus/cli.py:1680` |
| `run CMD` | `--agent ID` (required), `--cwd`, `--why`, `-t`, `--recommend approve\|deny`, `--confidence`, wait flags | key, then verdict and `result` | 1, 2 | `src/cactus/cli.py:1720` |
| `get KEY...` | `-w`, `--timeout`, `--answered-only`, `--all`, `--agent ID` (owner read marks review/plan heard) | rows | 3 missing key; 2 timeout | `src/cactus/cli.py:1734` |
| `list` / `ls` | `-t`, `--act`, `--agent`, `--workspace`, `--tab`, `--pane`, `-s STATUSES\|any` (default `open,live,elaborate`), `--all` | rows | 3 empty | `src/cactus/cli.py:1745` |
| `answer KEY [TEXT\|-]` | `-s LABEL`..., `--skip\|--dismiss` | the row; `auto-poke: ...` on stderr when a delivery fires and `--json` is off (a herdr entry fires only on a row with a pane) | 1 off-menu/empty/cleared/no-free; 3 missing or already answered; `cactus: answer saved; webhook poke failed: ...` | `src/cactus/cli.py:1759` |
| `elaborate KEY [HINT]` | `--decompose\|--withdraw` | the row | 1, 3 | `src/cactus/cli.py:1769` |
| `undo KEY` | — | the row | 1 open/cleared; 3 | `src/cactus/cli.py:1779` |
| `exec KEY` | — | command output streamed, result recorded; a `run` row also records `approve` and delivers like `answer` (`auto-poke: ...` unless `--json`) | 1 no command; 3; `cactus: answer saved; webhook poke failed: ...` | `src/cactus/cli.py:1783` |
| `edit KEY` | `--agent ID` (required), `--text`, `--context`, `-c`..., `-f`..., `--site URL\|""` | the row | 1 not owner/not editable; 3 | `src/cactus/cli.py:1787` |
| `clear [KEY...]` | `-t`, `--here`, `--all`, `--purge`, `--agent ID` (required for bulk) | count | 1 not owner; 3 | `src/cactus/cli.py:1802` |
| `reopen KEY...` | `--agent ID` | rows | 1 not cleared/not owner; 3 | `src/cactus/cli.py:1812` |
| `feed` | `--act`, `--agent`, `--workspace`, `--tab`, `--pane`, `-t`, `-s`, `--here`, `--pretty` | one JSON document, always | 3 empty | `src/cactus/cli.py:1817` |
| `poke [KEY]` | `--agent ID`, `-m MSG` | `poked AGENT` / `{"agent","ran"}` | 1 no key or agent, no pane; 3 | `src/cactus/cli.py:1836` |
| `deliver [herdr\|webhook URL\|off]` | `--agent ID` (required) | `ID: herdr`, `ID: webhook URL`, `ID: delivery off`; `--json` prints the entry, `null` after `off` | see below | `src/cactus/cli.py:1842` |
| `rehome` | `--agent NEW` (required) | moved rows | 1 without `HERDR_PANE_ID`/`HERDR_SESSION` | `src/cactus/cli.py:1850` |
| `migrate` | `--yes` | rebuild report | 1 | `src/cactus/cli.py:1855` |
| `review KEY` | `--look-at`, `--run`, `--pass`, `--fail`, `--then`, `-f`..., `--agent ID` | the row | 1 not owner/cleared; 3 | `src/cactus/cli.py:1859` |
| `plan KEY` | `--step TEXT`..., `--reset-steps`, `--done N`, `--undone N` (1-based), `-f`..., `--agent ID` | the row | 1 not a plan, bad step; 3 | `src/cactus/cli.py:1873` |
| `threads` | `--all` | threads with counts | 3 empty | `src/cactus/cli.py:1887` |
| `projects` | — | projects with counts | 3 empty | `src/cactus/cli.py:1891` |
| `project-status` | `--cwd DIR` | `{"enabled": ...}` with `--json` | — | `src/cactus/cli.py:1894` |
| `project [status\|activate\|ignore]` | `--cwd DIR` | state | — | `src/cactus/cli.py:1898` |
| `where` | — | db path, project | — | `src/cactus/cli.py:1904` |
| `sky` | `--dump [--force]`, `--bench` | config path / bench | 1 file exists | `src/cactus/cli.py:1907` |
| `garden` | `--clear` | path, counts | — | `src/cactus/cli.py:1916` |
| `decider [start\|status\|stop]` | `--backend strands\|clef` | server state | 1 binary missing; 3 down | `src/cactus/cli.py:1920` |

**`cactus deliver` errors** (`src/cactus/cli.py:1294`)

| stderr | Exit | Trigger |
|---|---|---|
| `cactus deliver: error: the following arguments are required: --agent` | 1 | no `--agent` |
| `cactus: deliver needs a non-empty --agent` | 1 | `--agent ' '` |
| `cactus: URL only goes with \`deliver webhook\`` | 1 | `deliver herdr URL` |
| `cactus: deliver webhook needs a URL` | 1 | `deliver webhook` alone |
| `cactus: no match` | 3 | bare read, or `off`, on an agent with no entry |
| `cactus: cannot read webhook map PATH: ...` | 1 | map file unreadable or bad JSON (`src/cactus/poke.py:94`) |

`deliver` touches no database row.

## Delivery map

JSON object keyed by agent id. Path: `CACTUS_POKE_WEBHOOKS`, else `~/.config/cactus/poke-webhooks.json` (`src/cactus/poke.py:67`, `:80`).
Written by `write_delivery`: temp file plus rename, mode 0600, other entries kept (`src/cactus/poke.py:125`).

| Entry | After an answer | Errors (`PokeError`) | Site |
|---|---|---|---|
| `{"herdr": true}` (no `url`) | prompts the row's herdr pane with `ANSWERED_MESSAGE`; `CACTUS_POKE` overrides the transport; no pane, skipped silently | `CMD timed out after Ns`, `CMD: TAIL` | `src/cactus/poke.py:112`, `:149`, `:273`, `:278` |
| `{"url": URL}` | POSTs `{agent, message}` to URL; ignores `CACTUS_POKE` | `webhook HTTP CODE: TAIL`, `webhook failed: REASON` | `src/cactus/poke.py:196`, `:221`, `:223` |
| absent | nothing; the agent wakes on its own backgrounded wait | — | `src/cactus/poke.py:149` |

Callers print the error and keep the answer.

Callers: `cactus answer` (`src/cactus/cli.py:745`), `cactus exec` on a `run` row (`src/cactus/cli.py:886`), TUI answers via `_auto_poke_webhook` (`src/cactus/tui.py:2645`; called at `:2466`, `:3534`, `:3565`, `:3589`, `:3668`; flash `answered; webhook poke failed: ...`), `POST /api/answer` (`src/cactus/www.py:588`).

| Map error | Site |
|---|---|
| `webhook map PATH must be a JSON object keyed by agent id` | `src/cactus/poke.py:98` |
| `webhook map entry for 'ID' must be an object` | `src/cactus/poke.py:108` |
| `webhook map entry for 'ID' needs a string url` | `src/cactus/poke.py:199` |

## HTTP (`cactus --www`)

Loopback, no auth (`src/cactus/www.py:1`). POST bodies are JSON `{key, project, ...}`. Errors: `400 {"error": ...}` for bad input, `404 {"error": "not found"}`, `500` otherwise (`src/cactus/www.py:509`).

| Route | Inputs | Output | Errors | Site |
|---|---|---|---|---|
| `GET /` | — | the board page | — | `src/cactus/www.py:519` |
| `GET /api/feed` | — | `{cursor, questions}` | 500 | `src/cactus/www.py:551` |
| `GET /api/events` | — | SSE `event: change` with `{cursor}`; `: ping` every 15 s | — | `src/cactus/www.py:563` |
| `POST /api/answer` | `key`, `project`, `selected`, `text`, `skipped` | the row plus `poked`, `poke_error` | 400 `key is required`, refusals | `src/cactus/www.py:588` |
| `POST /api/clear` | `key`, `project` | `{cleared: N}` | 400 | `src/cactus/www.py:614` |
| `POST /api/reopen` | `key`, `project` | the row | 400 | `src/cactus/www.py:627` |
| `POST /api/poke` | `key`, `project` | `{agent, ran}` | 400 `no such question: KEY`, poke errors | `src/cactus/www.py:638` |

## MCP (`cactus-mcp`)

Stdio JSON-RPC 2.0: `initialize`, `ping`, `tools/list`, `tools/call` (`src/cactus/mcp.py:494`). Each tool runs one `cactus --json` subprocess, so CLI errors and exit codes carry through as `isError`. Every tool takes `project`.
`agent` defaults to `CACTUS_AGENT`, else `claude-desktop` (`src/cactus/mcp.py:28`, `:63`); `project` to `CACTUS_PROJECT`, else home (`src/cactus/mcp.py:67`); waits clamp to `CACTUS_MCP_MAX_WAIT`, else 50 s (`src/cactus/mcp.py:32`, `:71`).

Output: the verb's `--json` stdout as text. Exit 3 -> `{"match": false, "note"}`; exit 2 -> `{"timeout": true, "note"}`; exit 1 -> `isError` with the CLI's stderr line; a missing project dir, a killed or unstartable subprocess -> `isError` (`src/cactus/mcp.py:102`). Unknown tool -> `isError` `unknown tool: NAME` (`:477`); missing required arg -> `isError` `missing argument: NAME` (`:519`); unknown method -> JSON-RPC `-32601` (`:522`).

| Tool | Maps to | Inputs (required first) | Output | Errors | Site |
|---|---|---|---|---|---|
| `cactus_ask` | `ask ... --no-wait` unless `wait` | `text`; `choices`, `files`, `site`, `act`, `kind`, `multi`, `confirm`, `context`, `thread`, `parent`, `recommend`, `confidence`, `why`, `chosen`, `blocked`, `no_free`, `word`, `title`, `wait`, `timeout`, `agent` | key, or the answered row | `ask` refusals; timeout object | `src/cactus/mcp.py:171` |
| `cactus_run` | `run ... --no-wait` | `command`; `why`, `cwd`, `thread`, `recommend`, `confidence`, `agent` | key | `run` refusals | `src/cactus/mcp.py:202` |
| `cactus_get` | `get` | `keys`; `wait`, `timeout`, `answered_only`, `all` | rows | no-match object; timeout object | `src/cactus/mcp.py:217` |
| `cactus_list` | `list` | `status`, `thread`, `act`, `agent`, `all` | rows | no-match object | `src/cactus/mcp.py:229` |
| `cactus_feed` | `feed` | `status`, `thread`, `act`, `agent`, `here` | feed document | no-match object | `src/cactus/mcp.py:240` |
| `cactus_answer` | `answer` | `key`; `select`, `text`, `skip`, `dismiss` | the row | `answer` refusals; no-match object | `src/cactus/mcp.py:251` |
| `cactus_edit` | `edit` | `key`; `text`, `context`, `choices`, `files`, `site`, `agent` | the row | not owner/not editable; no-match object | `src/cactus/mcp.py:263` |
| `cactus_review` | `review` | `key`; `look_at`, `run`, `pass_when`, `fail_when`, `then`, `files`, `agent` | the row | not owner/cleared; no-match object | `src/cactus/mcp.py:277` |
| `cactus_plan` | `plan` | `key`; `steps`, `reset_steps`, `done`, `undone`, `files`, `agent` | the row | not a plan, bad step; no-match object | `src/cactus/mcp.py:292` |
| `cactus_clear` | `clear` | `keys`, `thread`, `here`, `purge`, `agent` | count | not owner; no-match object | `src/cactus/mcp.py:306` |
| `cactus_reopen` | `reopen` | `keys`; `agent` | rows | not cleared/not owner; no-match object | `src/cactus/mcp.py:317` |
| `cactus_threads`, `cactus_projects`, `cactus_where` | `threads`, `projects`, `where` | — | threads / projects / db path and project | no-match object | `src/cactus/mcp.py:322` |
| `cactus_help` | `AGENT_HELP` text, no subprocess | — | reference text | — | `src/cactus/mcp.py:325` |

No `deliver` tool.

## Hooks (events consumed)

Claude plugin: `hooks/hooks.json`. Codex plugin: `plugins/cactus/hooks/hooks.json`. Hooks exit 0 silently when `cactus` is missing; most also when `jq` is missing (not `hooks/stop-fork.sh`, `hooks/session-start.sh`) and when `cactus project-status` reports the project disabled. Both SessionStart hooks print `Cactus is disabled for this project. ...` instead.

| Host | Event | Script | Does | Errors / exit | Site |
|---|---|---|---|---|---|
| Claude | SessionStart | `hooks/session-start.sh` | prints the workflow, `--agent ID`, rehomes this pane's rows (`cactus rehome`), lists open rows | none; disabled project prints `Cactus is disabled for this project. ...` (points at `cactus project activate`) | `hooks/session-start.sh:19`, `:42` |
| Claude | UserPromptSubmit | `hooks/frontier.sh` | prints up to `CACTUS_FRONTIER_MAX` (5) rows: elaborate, answered, open/live, with verdicts, then a counts line | none; silent on no identity or no rows | `hooks/frontier.sh:30` |
| Claude | PreToolUse (Bash) | `hooks/pretooluse_wait.py` | refuses a foreground `cactus ask\|run` that would wait; passes `run_in_background`, `--no-wait`, `--no-block`, non-waiting acts | exit 2, stderr `cactus ask/run waits for the human by default; rerun with run_in_background: true. Its exit wakes you.` | `hooks/pretooluse_wait.py:134` |
| Claude | PermissionDenied (Bash) | `hooks/permission-denied.sh` | posts the denied command as `cactus run --no-wait -t denied`, once per `tool_use_id` | none; post failures discarded | `hooks/permission-denied.sh:44` |
| Claude | Stop | `hooks/stop-fork.sh` | silent when `CACTUS_STOP_HOOK=0`, or when `cactus list -s open --agent ID --json` is non-empty (q469; `live`/`elaborate` do not count); else blocks a human-opened turn with no `cactus ask\|edit\|plan\|review` or AskUserQuestion: `{"decision":"block","reason":"the turn ended without a fork; ..."}` | without `jq` the open-row check reads 0 and the hook can still block | `hooks/stop-fork.sh:38`, `:185` |
| Codex | SessionStart | `plugins/cactus/hooks/session-start.sh` | with `HERDR_PANE_ID` set, runs `cactus deliver herdr --agent SESSION_ID` and prints `Cactus registered herdr delivery for ID: answers prompt this pane.`; prints the mod-mode line and open rows | deliver failure: no registration line; disabled project prints `Cactus is disabled for this project. ...` | `plugins/cactus/hooks/session-start.sh:18` |
| Codex | UserPromptSubmit | `plugins/cactus/hooks/frontier.sh` | the mod-mode substitute: reads `cactus list -s any --agent ID --json`, prints up to five rows (elaborate, answered, open/live) with the latest answer (`— answer: LABELS — TEXT` or `— skipped; use the stated default`), then `cactus clear KEY --agent ID` for each printed answered row whose act is not review, plan or data | none | `plugins/cactus/hooks/frontier.sh:17`, `:59` |
| Codex | PermissionRequest (Bash) | `plugins/cactus/hooks/permission-request.sh` | posts the command as `cactus run --no-wait`, then denies: `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"Cactus approval KEY was opened. ..."}}}` | post fails: no output, Codex's own prompt stands | `plugins/cactus/hooks/permission-request.sh:17`, `:19` |
| Codex | Stop | `plugins/cactus/hooks/stop.sh` | never blocks (no idle wake in Codex) | none | `plugins/cactus/hooks/stop.sh:23` |

Agent id: Codex hooks use the payload `session_id`. Claude hooks resolve payload `session_id`, then herdr, then `CACTUS_AGENT` (`hooks/identity.sh:35`).

## Environment

| Variable | Effect | Site |
|---|---|---|
| `CACTUS_DB` | database path; empty refuses, exit 1 | `src/cactus/store.py:218` |
| `CACTUS_POKE` | poke transport template (`{agent}` `{target}` `{session}` `{message}`); also overrides herdr-entry delivery, never webhook delivery | `src/cactus/poke.py:321` |
| `CACTUS_POKE_WEBHOOKS` | delivery map path | `src/cactus/poke.py:82` |
| `CACTUS_VISIT` | `v` visit template (`{pane}`) | `src/cactus/poke.py:358` |
| `CACTUS_RECORDS` | `0` disables decision records | `src/cactus/cli.py:188` |
| `CACTUS_STOP_HOOK` | `0` disables the Claude Stop hook | `hooks/stop-fork.sh:24` |
| `CACTUS_AGENT` | last-resort hook identity; MCP default agent; `ask --by` default | `hooks/identity.sh:35`, `src/cactus/mcp.py:64` |
| `CACTUS_PROJECT` | MCP default project (else home) | `src/cactus/mcp.py:68` |
| `CACTUS_MCP_MAX_WAIT` | MCP wait clamp, seconds (default 50) | `src/cactus/mcp.py:73` |
| `HERDR_PANE_ID` | Codex session start registers herdr delivery only when set | `plugins/cactus/hooks/session-start.sh:18` |
