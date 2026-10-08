# Interfaces

Every surface cactus exposes: CLI, delivery map, HTTP board, MCP tools, hooks.
Each row cites its definition site. No OpenAPI, proto or JSON-schema file exists; the code is the spec.

**Exit codes** (`src/cactus/cli.py` `EXIT_OK`, `EXIT_ERROR`, `EXIT_TIMEOUT`, `EXIT_EMPTY`)

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | error; argparse usage errors too (`src/cactus/cli.py` `_ArgumentParser`) |
| 2 | `--wait` timed out |
| 3 | no match: missing key, empty result, already answered. One stderr line `cactus: no match` on empty results (`src/cactus/cli.py` `_no_match`) |

Errors print one stderr line, `cactus: <reason>`.

## CLI

Entry points `cactus`, `cac` -> `cactus.cli:main`; `cactus-mcp` -> `cactus.mcp:main` (`pyproject.toml:17`).
`--json` works before or after the verb. `KEY` is `qN`, `LABEL:qN` or `/abs/path:qN`.

**Global flags.** `--tui`, `--watch`, `--www`, `--monitor` are mutually exclusive: two or more exit 1, `cactus: --tui and --watch are mutually exclusive` (`src/cactus/cli.py` `main`). `--db`, `--agent-help`, `--version` combine freely.

| Invocation | Does | Errors | Site |
|---|---|---|---|
| `cactus --tui [--here]` | human answering TUI | exit 1 when stdout is not a tty | `src/cactus/cli.py` `build_parser` |
| `cactus --watch [--here]` | read-only feed | exit 1 when stdout is not a tty | `src/cactus/cli.py` `build_parser` |
| `cactus --www [--host H] [--port P] [--open] [--here]` | HTTP board, default `127.0.0.1:8642` | see HTTP | `src/cactus/cli.py` `build_parser` |
| `cactus --monitor --agent ID [--all] [--replay] [--once] [--interval S] [--workspace W] [--tab T] [--pane P]` | one stdout line per row change | exit 1 without `--agent` | `src/cactus/cli.py` `build_parser` |
| `cactus --agent-help` | prints the agent reference | — | `src/cactus/cli.py` `build_parser` |
| `cactus --db PATH` | database path (else `CACTUS_DB`) | exit 1 on empty `CACTUS_DB` | `src/cactus/cli.py` `build_parser` |
| `cactus --version` | prints `cactus VERSION`, exit 0 | — | `src/cactus/cli.py` `build_parser` |

**Verbs**

| Verb | Inputs | Output | Errors | Site |
|---|---|---|---|---|
| `ask TEXT` | `-c LABEL[: DESC]`..., `--act ask\|steer\|run\|notify\|review\|plan\|data`, `--agent ID` (required), `--by ID` (default `CACTUS_AGENT`), `--multi`, `--confirm`, `--kind`, `--recommend L --confidence low\|med\|high`, `--why`, `--chosen`, `--blocked\|--no-block`, `--no-free`, `-t`, `-p`, `--context`, `--word`, `--title`, `-f PATH`..., `--site URL`, `-w\|--no-wait`, `--timeout S` | key, then the answer once given (blocking acts wait by default, 3600 s) | 1 on refusal; 2 on timeout | `src/cactus/cli.py` `cmd_ask` |
| `run CMD` | `--agent ID` (required), `--cwd`, `--why`, `-t`, `--recommend approve\|deny`, `--confidence`, wait flags | key, then verdict and `result` | 1, 2 | `src/cactus/cli.py` `cmd_run` |
| `get KEY...` | `-w`, `--timeout`, `--answered-only`, `--all`, `--agent ID` (owner read marks review/plan heard) | rows | 3 missing key; 2 timeout | `src/cactus/cli.py` `cmd_get` |
| `list` / `ls` | `-t`, `--act`, `--agent`, `--workspace`, `--tab`, `--pane`, `-s STATUSES\|any` (default `open,live,elaborate`), `--all` | rows | 3 empty | `src/cactus/cli.py` `cmd_list` |
| `answer KEY [TEXT\|-]` | `-s LABEL`..., `--skip\|--dismiss` | the row; `auto-poke: ...` on stderr when a delivery fires and `--json` is off (a herdr entry fires only on a row with a pane) | 1 off-menu/empty/cleared/no-free; 3 missing or already answered; `cactus: answer saved; webhook poke failed: ...` | `src/cactus/cli.py` `cmd_answer` |
| `elaborate KEY [HINT]` | `--decompose\|--withdraw` | the row | 1, 3 | `src/cactus/cli.py` `cmd_elaborate` |
| `undo KEY` | — | the row | 1 open/cleared; 3 | `src/cactus/cli.py` `cmd_undo` |
| `exec KEY` | — | command output streamed, result recorded; a `run` row also records `approve` and delivers like `answer` (`auto-poke: ...` unless `--json`) | 1 no command; 3; `cactus: answer saved; webhook poke failed: ...` | `src/cactus/cli.py` `cmd_exec` |
| `edit KEY` | `--agent ID` (required), `--text`, `--context`, `-c`..., `-f`..., `--site URL\|""` | the row | 1 not owner/not editable; 3 | `src/cactus/cli.py` `cmd_edit` |
| `clear [KEY...]` | `-t`, `--here`, `--all`, `--purge`, `--agent ID` (required for bulk) | count | 1 not owner; 3 | `src/cactus/cli.py` `cmd_clear` |
| `reopen KEY...` | `--agent ID` | rows | 1 not cleared/not owner; 3 | `src/cactus/cli.py` `cmd_reopen` |
| `feed` | `--act`, `--agent`, `--workspace`, `--tab`, `--pane`, `-t`, `-s`, `--here`, `--pretty` | one JSON document, always | 3 empty | `src/cactus/cli.py` `cmd_feed` |
| `poke [KEY]` | `--agent ID`, `-m MSG` | `poked AGENT` / `{"agent","ran"}` | 1 no key or agent, no pane; 3 | `src/cactus/cli.py` `cmd_poke` |
| `deliver [herdr\|webhook URL\|off]` | `--agent ID` (required) | `ID: herdr`, `ID: webhook URL`, `ID: delivery off`; `--json` prints the entry, `null` after `off` | see below | `src/cactus/cli.py` `cmd_deliver` |
| `rehome` | `--agent NEW` (required) | moved rows | 1 without `HERDR_PANE_ID`/`HERDR_SESSION` | `src/cactus/cli.py` `cmd_rehome` |
| `migrate` | `--yes` | rebuild report | 1 | `src/cactus/cli.py` `cmd_migrate` |
| `review KEY` | `--look-at`, `--run`, `--pass`, `--fail`, `--then`, `-f`..., `--agent ID` | the row | 1 not owner/cleared; 3 | `src/cactus/cli.py` `cmd_review` |
| `plan KEY` | `--step TEXT`..., `--reset-steps`, `--done N`, `--undone N` (1-based), `-f`..., `--agent ID` | the row | 1 not a plan, bad step; 3 | `src/cactus/cli.py` `cmd_plan` |
| `threads` | `--all` | threads with counts | 3 empty | `src/cactus/cli.py` `cmd_threads` |
| `projects` | — | projects with counts | 3 empty | `src/cactus/cli.py` `cmd_projects` |
| `project-status` | `--cwd DIR` | `{"enabled": ...}` with `--json` | — | `src/cactus/cli.py` `cmd_project_status` |
| `project [status\|activate\|ignore]` | `--cwd DIR` | state | — | `src/cactus/cli.py` `cmd_project` |
| `where` | — | db path, project | — | `src/cactus/cli.py` `cmd_where` |
| `sky` | `--dump [--force]`, `--bench` | config path / bench | 1 file exists | `src/cactus/cli.py` `cmd_sky` |
| `garden` | `--clear` | path, counts | — | `src/cactus/cli.py` `cmd_garden` |
| `decider [start\|status\|stop]` | `--backend strands\|clef` | server state | 1 binary missing; 3 down | `src/cactus/cli.py` `cmd_decider` |

**`cactus deliver` errors** (`src/cactus/cli.py` `cmd_deliver`)

| stderr | Exit | Trigger |
|---|---|---|
| `cactus deliver: error: the following arguments are required: --agent` | 1 | no `--agent` |
| `cactus: deliver needs a non-empty --agent` | 1 | `--agent ' '` |
| `cactus: URL only goes with \`deliver webhook\`` | 1 | `deliver herdr URL` |
| `cactus: deliver webhook needs a URL` | 1 | `deliver webhook` alone |
| `cactus: no match` | 3 | bare read, or `off`, on an agent with no entry |
| `cactus: cannot read webhook map PATH: ...` | 1 | map file unreadable or bad JSON (`src/cactus/poke.py` `load_webhooks`) |

`deliver` touches no database row.

## Delivery map

JSON object keyed by agent id. Path: `CACTUS_POKE_WEBHOOKS`, else `~/.config/cactus/poke-webhooks.json` (`src/cactus/poke.py` `DEFAULT_WEBHOOKS_PATH`, `webhooks_path`).
Written by `write_delivery`: temp file plus rename, mode 0600, other entries kept (`src/cactus/poke.py` `write_delivery`).

| Entry | After an answer | Errors (`PokeError`) | Site |
|---|---|---|---|
| `{"herdr": true}` (no `url`) | prompts the row's herdr pane with `ANSWERED_MESSAGE`; `CACTUS_POKE` overrides the transport; no pane, skipped silently | `CMD timed out after Ns`, `CMD: TAIL` | `src/cactus/poke.py` `is_herdr_entry`, `deliver_if_mapped`, `_run_argv` |
| `{"url": URL}` | POSTs `{agent, message}` to URL; ignores `CACTUS_POKE` | `webhook HTTP CODE: TAIL`, `webhook failed: REASON` | `src/cactus/poke.py` `_post_webhook` |
| absent | nothing; the agent wakes on its own backgrounded wait | — | `src/cactus/poke.py` `deliver_if_mapped` |

Callers print the error and keep the answer.

Callers: `cactus answer` (`src/cactus/cli.py` `cmd_answer`), `cactus exec` on a `run` row (`src/cactus/cli.py` `cmd_exec`), TUI answers via `_auto_poke_webhook` (`src/cactus/tui.py` `CactusApp._auto_poke_webhook`; called from `_finish_run_row`, `_submit_plan`, `_submit_review`, `_submit_data`, `_submit_answer`; flash `answered; webhook poke failed: ...`), `POST /api/answer` (`src/cactus/www.py` `_Handler._handle_answer`).

| Map error | Site |
|---|---|
| `webhook map PATH must be a JSON object keyed by agent id` | `src/cactus/poke.py` `load_webhooks` |
| `webhook map entry for 'ID' must be an object` | `src/cactus/poke.py` `delivery_entry` |
| `webhook map entry for 'ID' needs a string url` | `src/cactus/poke.py` `_post_webhook` |

## HTTP (`cactus --www`)

Loopback, no auth (`src/cactus/www.py` `run_www`). POST bodies are JSON `{key, project, ...}`. Errors: `400 {"error": ...}` for bad input, `404 {"error": "not found"}`, `500` otherwise (`src/cactus/www.py` `_Handler._error`).

| Route | Inputs | Output | Errors | Site |
|---|---|---|---|---|
| `GET /` | — | the board page | — | `src/cactus/www.py` `_Handler.do_GET` |
| `GET /api/feed` | — | `{cursor, questions}` | 500 | `src/cactus/www.py` `_Handler._handle_feed` |
| `GET /api/events` | — | SSE `event: change` with `{cursor}`; `: ping` every 15 s | — | `src/cactus/www.py` `_Handler._handle_events` |
| `POST /api/answer` | `key`, `project`, `selected`, `text`, `skipped` | the row plus `poked`, `poke_error` | 400 `key is required`, refusals | `src/cactus/www.py` `_Handler._handle_answer` |
| `POST /api/clear` | `key`, `project` | `{cleared: N}` | 400 | `src/cactus/www.py` `_Handler._handle_clear` |
| `POST /api/reopen` | `key`, `project` | the row | 400 | `src/cactus/www.py` `_Handler._handle_reopen` |
| `POST /api/poke` | `key`, `project` | `{agent, ran}` | 400 `no such question: KEY`, poke errors | `src/cactus/www.py` `_Handler._handle_poke` |

## MCP (`cactus-mcp`)

Stdio JSON-RPC 2.0: `initialize`, `ping`, `tools/list`, `tools/call` (`src/cactus/mcp.py` `handle`). Each tool runs one `cactus --json` subprocess, so CLI errors and exit codes carry through as `isError`. Every tool takes `project`.
`agent` defaults to `CACTUS_AGENT`, else `claude-desktop` (`src/cactus/mcp.py` `DEFAULT_AGENT`, `_default_agent`); `project` to `CACTUS_PROJECT`, else home (`src/cactus/mcp.py` `_default_project`); waits clamp to `CACTUS_MCP_MAX_WAIT`, else 50 s (`src/cactus/mcp.py` `MAX_WAIT`, `_max_wait`).

Output: the verb's `--json` stdout as text. Exit 3 -> `{"match": false, "note"}`; exit 2 -> `{"timeout": true, "note"}`; exit 1 -> `isError` with the CLI's stderr line; a missing project dir, a killed or unstartable subprocess -> `isError` (`src/cactus/mcp.py` `_run`). Unknown tool -> `isError` `unknown tool: NAME` (`call_tool`); missing required arg -> `isError` `missing argument: NAME` (`handle`); unknown method -> JSON-RPC `-32601` (`handle`).

| Tool | Maps to | Inputs (required first) | Output | Errors | Site |
|---|---|---|---|---|---|
| `cactus_ask` | `ask ... --no-wait` unless `wait` | `text`; `choices`, `files`, `site`, `act`, `kind`, `multi`, `confirm`, `context`, `thread`, `parent`, `recommend`, `confidence`, `why`, `chosen`, `blocked`, `no_free`, `word`, `title`, `wait`, `timeout`, `agent` | key, or the answered row | `ask` refusals; timeout object | `src/cactus/mcp.py` `TOOLS` (`cactus_ask`) |
| `cactus_run` | `run ... --no-wait` | `command`; `why`, `cwd`, `thread`, `recommend`, `confidence`, `agent` | key | `run` refusals | `src/cactus/mcp.py` `TOOLS` (`cactus_run`) |
| `cactus_get` | `get` | `keys`; `wait`, `timeout`, `answered_only`, `all` | rows | no-match object; timeout object | `src/cactus/mcp.py` `TOOLS` (`cactus_get`) |
| `cactus_list` | `list` | `status`, `thread`, `act`, `agent`, `all` | rows | no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_list`) |
| `cactus_feed` | `feed` | `status`, `thread`, `act`, `agent`, `here` | feed document | no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_feed`) |
| `cactus_answer` | `answer` | `key`; `select`, `text`, `skip`, `dismiss` | the row | `answer` refusals; no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_answer`) |
| `cactus_edit` | `edit` | `key`; `text`, `context`, `choices`, `files`, `site`, `agent` | the row | not owner/not editable; no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_edit`) |
| `cactus_review` | `review` | `key`; `look_at`, `run`, `pass_when`, `fail_when`, `then`, `files`, `agent` | the row | not owner/cleared; no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_review`) |
| `cactus_plan` | `plan` | `key`; `steps`, `reset_steps`, `done`, `undone`, `files`, `agent` | the row | not a plan, bad step; no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_plan`) |
| `cactus_clear` | `clear` | `keys`, `thread`, `here`, `purge`, `agent` | count | not owner; no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_clear`) |
| `cactus_reopen` | `reopen` | `keys`; `agent` | rows | not cleared/not owner; no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_reopen`) |
| `cactus_threads`, `cactus_projects`, `cactus_where` | `threads`, `projects`, `where` | — | threads / projects / db path and project | no-match object | `src/cactus/mcp.py` `TOOLS` (`cactus_threads`, `cactus_projects`, `cactus_where`) |
| `cactus_help` | `AGENT_HELP` text, no subprocess | — | reference text | — | `src/cactus/mcp.py` `TOOLS` (`cactus_help`) |

No `deliver` tool.

## Hooks (events consumed)

Claude plugin: `hooks/hooks.json`. Codex plugin: `plugins/cactus/hooks/hooks.json`. Hooks exit 0 silently when `cactus` is missing; most also when `jq` is missing (not `hooks/stop_fork.py`, `hooks/session_start.py`) and when `cactus project-status` reports the project disabled. Both SessionStart hooks print `Cactus is disabled for this project. ...` instead.

| Host | Event | Script | Does | Errors / exit | Site |
|---|---|---|---|---|---|
| Claude | SessionStart | `hooks/session_start.py` | prints the workflow, `--agent ID`, rehomes this pane's rows (`cactus rehome`), lists open rows | none; disabled project prints `Cactus is disabled for this project. ...` (points at `cactus project activate`) | `hooks/session_start.py` `main`, `rehomed` |
| Claude | UserPromptSubmit | `hooks/frontier.py` | prints up to `CACTUS_FRONTIER_MAX` (5) rows: elaborate, answered, open/live, with verdicts, then a counts line | none; silent on no identity or no rows | `hooks/frontier.py` `main` |
| Claude | PreToolUse (Bash) | `hooks/pretooluse_wait.py` | refuses a foreground `cactus ask\|run` that would wait; passes `run_in_background`, `--no-wait`, `--no-block`, non-waiting acts | exit 2, stderr `cactus ask/run waits for the human by default; rerun with run_in_background: true. Its exit wakes you.` | `hooks/pretooluse_wait.py` `main` |
| Claude | PermissionDenied (Bash) | `hooks/permission_denied.py` | posts the denied command as `cactus run --no-wait -t denied`, once per `tool_use_id` | none; post failures discarded | `hooks/permission_denied.py` `main` |
| Claude | Stop | `hooks/stop_fork.py` | silent when `CACTUS_STOP_HOOK=0`, or when `cactus list -s open --agent ID --json` is non-empty (q469; `live`/`elaborate` do not count); else blocks a human-opened turn with no `cactus ask\|edit\|plan\|review` or AskUserQuestion: `{"decision":"block","reason":"the turn ended without a fork; ..."}` | a failed `cactus list` reads as no open rows, so the hook can still block | `hooks/stop_fork.py` `main` |
| Codex | SessionStart | `plugins/cactus/hooks/session-start.sh` | with `HERDR_PANE_ID` set, runs `cactus deliver herdr --agent SESSION_ID` and prints `Cactus registered herdr delivery for ID: answers prompt this pane.`; prints the mod-mode line and open rows | deliver failure: no registration line; disabled project prints `Cactus is disabled for this project. ...` | `plugins/cactus/hooks/session-start.sh:18` |
| Codex | UserPromptSubmit | `plugins/cactus/hooks/frontier.sh` | the mod-mode substitute: reads `cactus list -s any --agent ID --json`, prints up to five rows (elaborate, answered, open/live) with the latest answer (`— answer: LABELS — TEXT` or `— skipped; use the stated default`), then `cactus clear KEY --agent ID` for each printed answered row whose act is not review, plan or data | none | `plugins/cactus/hooks/frontier.sh:17`, `:59` |
| Codex | PermissionRequest (Bash) | `plugins/cactus/hooks/permission-request.sh` | posts the command as `cactus run --no-wait`, then denies: `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"Cactus approval KEY was opened. ..."}}}` | post fails: no output, Codex's own prompt stands | `plugins/cactus/hooks/permission-request.sh:17`, `:19` |
| Codex | Stop | `plugins/cactus/hooks/stop.sh` | never blocks (no idle wake in Codex) | none | `plugins/cactus/hooks/stop.sh:23` |

Agent id: Codex hooks use the payload `session_id`. Claude hooks resolve payload `session_id`, then herdr, then `CACTUS_AGENT` (`hooks/cactus_identity.py` `resolve_agent`).

## Environment

| Variable | Effect | Site |
|---|---|---|
| `CACTUS_DB` | database path; empty refuses, exit 1 | `src/cactus/store.py` `default_db_path` |
| `CACTUS_POKE` | poke transport template (`{agent}` `{target}` `{session}` `{message}`); also overrides herdr-entry delivery, never webhook delivery | `src/cactus/poke.py` `poke` |
| `CACTUS_POKE_WEBHOOKS` | delivery map path | `src/cactus/poke.py` `webhooks_path` |
| `CACTUS_VISIT` | `v` visit template (`{pane}`) | `src/cactus/poke.py` `visit` |
| `CACTUS_RECORDS` | `0` disables decision records | `src/cactus/store.py` `Store._record` |
| `CACTUS_STOP_HOOK` | `0` disables the Claude Stop hook | `hooks/stop_fork.py` `main` |
| `CACTUS_AGENT` | last-resort hook identity; MCP default agent; `ask --by` default | `hooks/cactus_identity.py` `resolve_agent`, `src/cactus/mcp.py` `_default_agent` |
| `CACTUS_PROJECT` | MCP default project (else home) | `src/cactus/mcp.py` `_default_project` |
| `CACTUS_MCP_MAX_WAIT` | MCP wait clamp, seconds (default 50) | `src/cactus/mcp.py` `_max_wait` |
| `HERDR_PANE_ID` | Codex session start registers herdr delivery only when set | `plugins/cactus/hooks/session-start.sh:18` |
