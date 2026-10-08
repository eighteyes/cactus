# Security model

cactus is a single-user, local tool. One person's machine, one SQLite inbox, many agent processes. Nothing below is multi-tenant.

**Trust boundaries**

	boundary	crosses	check	where
	agent -> store	question text, choices, files, --agent id	argument validation; no identity proof	src/cactus/cli.py:360 cmd_ask
	agent -> another agent's row	edit, clear, reopen, plan, review	ownership string compare	src/cactus/cli.py:923, :968, :1141, :1190
	browser -> www	/api/answer, /api/clear, /api/reopen, /api/poke	loopback by default (--host overrides); no auth	src/cactus/www.py:12, :675; src/cactus/cli.py:1642
	human -> shell	a run row's command, a review's run_cmd	explicit keypress (TUI R, cactus exec)	src/cactus/shell.py:56
	answer -> agent	delivery map entry: webhook POST or herdr prompt	entry must exist for the row's owner	src/cactus/poke.py:149
	hook payload -> identity	session_id from the harness	none; taken as given	hooks/cactus_identity.py resolve_agent

**Identity**

- `--agent ID` is a self-declared string. No token, no signature.
- Required on `ask`, `run`, `edit`, `deliver`, `rehome`, `--monitor`, and bulk `clear` (src/cactus/cli.py:462, :563, :909, :1301, :1852, :2002).
- Hooks resolve it: payload `session_id`, then herdr's view of `HERDR_PANE_ID`, then `CACTUS_AGENT` (hooks/cactus_identity.py `resolve_agent`).
- Any local process can claim any id.

**Authorization**

- Ownership gates live in cli.py; Store stays mechanism.
- `edit`: refuses a row owned by another agent (src/cactus/cli.py:923).
- `plan`, `review`: refuse only when `--agent` is given and differs (`_refuse_if_not_owner`, src/cactus/cli.py:968).
- `clear` by key: refuses rows owned by another agent (src/cactus/cli.py:1141). Bulk forms need `--agent` and touch only that agent's rows.
- `reopen`: same gate (src/cactus/cli.py:1190).
- `rehome`: needs `HERDR_PANE_ID` and `HERDR_SESSION`; moves only rows stamped with both (src/cactus/cli.py:1352).
- No gate: `poke` (src/cactus/cli.py:1259) and the human verbs `answer`, `elaborate`, `undo`, `exec`.
- TUI `c` clears any row, no agent filter (src/cactus/tui.py:3647).

These gates stop agents colliding. They are not access control: the id they compare is the self-declared one.

**Command execution**

- `shell.run` runs with `shell=True` in the row's `cwd` (src/cactus/shell.py:71). The command text comes from the asking agent.
- Runs only on a human keypress, never on arrival.
- Poke and visit split templates with `shlex` and substitute per argument; no shell (src/cactus/poke.py:186).
- MCP tools run `python -m cactus --json ...` as an argv list; no shell (src/cactus/mcp.py:119).

**Push delivery (the mod)**

- Map file: `CACTUS_POKE_WEBHOOKS`, default `~/.config/cactus/poke-webhooks.json` (src/cactus/poke.py:80).
- Entries: `{"herdr": true}` or `{"url": URL}`.
- `cactus deliver herdr|webhook URL|off --agent ID` writes one entry: temp file, `chmod 600`, `os.replace` (src/cactus/poke.py:142).
- Codex `session-start.sh` registers herdr delivery when `HERDR_PANE_ID` is set (plugins/cactus/hooks/session-start.sh:19).
- After an answer (TUI, `cactus answer`, www) or `cactus exec` on a `run` row (src/cactus/cli.py:886), `deliver_if_mapped` prompts the row's pane or POSTs `{agent, message}`. No row text in the body.
- `CACTUS_POKE` overrides the herdr branch; the webhook branch ignores it (src/cactus/poke.py:321).
- Delivery failure never rolls back the answer.

**Codex frontier**

- plugins/cactus/hooks/frontier.sh injects up to five rows, full latest answer included, into the Codex turn.
- Clears printed answered rows except review, plan, data: `cactus clear KEY --agent $agent` (plugins/cactus/hooks/frontier.sh:59). Gated like any agent clear.

**Stop hook**

- hooks/stop_fork.py exits silent when the resolved agent has an `open` row in the current project (hooks/stop_fork.py `main`). `live` and `elaborate` do not count. No resolved identity: no check.
- plugins/cactus/hooks/stop.sh (Codex) counts `open`, `live`, `elaborate`; it never blocks.
- `CACTUS_STOP_HOOK=0` turns both off.

**Secrets**

- Two secret-bearing keys on a webhook entry, read at POST time: `authorization` (or `Authorization`) and `headers` (src/cactus/poke.py:205-212).
- Source: hand-edited into the delivery map. `cactus deliver` never sets them.
- No env var, keychain, or secret manager.

**Data at rest**

- Inbox: `CACTUS_DB`, default `$XDG_DATA_HOME/cactus/cactus.db` (`~/.local/share/...` when unset); falls back to legacy `<data_root>/qaui/qaui.db` when the new path is absent and the legacy file exists (src/cactus/store.py:236). No chmod; process umask applies.
- Decision records: `<project>/.ai/cactus/q{N}-{id}-{slug}.md`, inside the repo working tree. `CACTUS_RECORDS=0` disables.
- MCP request log: `CACTUS_MCP_LOG`, default `mcp.log` beside the database; logs argv.

**Known gaps**

- No authentication anywhere. Agent ids are claims.
- www POST handlers check no Origin header and no token (src/cactus/www.py:532).
- `--www --host` binds any address; no auth follows it.
- `cactus deliver webhook URL` and `cactus deliver herdr` replace the whole entry, dropping a hand-added `authorization` or `headers` (src/cactus/cli.py:1320). Codex session-start.sh runs `deliver herdr` whenever `HERDR_PANE_ID` is set, so it silently wipes a hand-configured webhook entry and its secret.
- `chmod 600` applies only when cactus writes the map; a hand-created map keeps its own mode.
- The inbox, records, and MCP request log carry question text, answers, and run output in plain text. The log records each call's argv, question text and choices included (src/cactus/mcp.py:117).
- Run rows execute agent-authored shell text once a human approves.
