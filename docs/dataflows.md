# Dataflows

Where cactus data goes: sources, stores, sinks. Line numbers are as of commit 32fecc9.

```mermaid
flowchart LR
  agent["agent: cactus ask / plan / review / edit"] -->|row text, context, choices, files| cli["cli.py"]
  mcp["mcp.py (cactus --json subprocess)"] --> cli
  mcp -->|argv incl. row text| mcplog[("mcp.log")]
  cli --> store["store.py"]
  store --> db[("cactus.db (SQLite, WAL)")]
  human["human: TUI / www / cactus answer"] -->|answer: labels + free text| store
  human -->|TUI copy: data chunk, command| clip[("OS clipboard")]
  store -->|answer / clear / reopen / elaborate / edit, fail soft| rec[("<project>/.ai/cactus/q{N}-{id}-{slug}.md")]
  db -->|cursor() poll| readers["tui / watch / www / monitor / wait_for_answer"]
  readers -->|answer| agent
  human -->|after answer| deliver["poke.deliver_if_mapped"]
  dmap[("poke-webhooks.json (delivery map)")] --> deliver
  setdel["cactus deliver / Codex session-start.sh"] --> dmap
  deliver -->|herdr entry: fixed message| herdr["herdr agent prompt PANE"]
  deliver -->|url entry: POST {agent, message}| hook["webhook URL"]
  db -->|cactus list --json| frontier["Codex frontier.sh"]
  frontier -->|full latest answer, stdout| codex["Codex turn context"]
  frontier -->|cactus clear KEY| store
  transcript[("Claude transcript JSONL")] --> stop["hooks/stop_fork.py"]
  db -->|cactus list -s open| stop
  db -->|open choice rows| tuiauto["TUI _auto_work"]
  tuiauto -->|open choice row text| rank["rank.py: apint, else claude -p --model haiku"]
  rank -->|gated rows only| decider["decide.py -> 127.0.0.1 picker"]
  decider -->|auto_pick / reason| db
  run["R / cactus exec"] --> spill[("$TMPDIR/cactus-KEY-*.log")]
```

**Stores**

	store	holds	written by	read by
	cactus.db	questions, answers, reviews, steps, project_settings (store.py:91, :157, :166, :175, :187)	Store only: ask store.py:775, answer :946, clear :1035, purge :1145, set_run_result :1223, set_auto :1309	every surface via Store; change token cursor() store.py:1947
	poke-webhooks.json	per-agent delivery entry: {"herdr": true} or {"url": URL} plus optional authorization/headers	poke.write_delivery poke.py:125 (from cli.py:1294 cmd_deliver, which writes only {"url"} or {"herdr"}, cli.py:1316-1320); authorization/headers by hand-edit only	poke.load_webhooks poke.py:86, delivery_entry :102
	.ai/cactus/*.md	decision record per row: question, choices, verdicts	record.write_record record.py:293, via Store._record store.py:1597 (answer :1032, clear :1087, reopen :1142, elaborate :1423) and Store._record_if_exists :1621 (edit :1565, unelaborate :1455)	humans, git
	mcp.log	one line per MCP request, incl. run argv	mcp._log mcp.py:88	humans
	tui.json	TUI settings, pinned project path	tui._save_tui_settings tui.py:127	tui.py:101
	garden.json	field pile cells	garden.save garden.py:70 (tui.py:3858, fieldproc.py:121)	garden.load_into garden.py:37
	cactus-KEY-*.log	full output of a run/review command	shell.spill shell.py:113 (cli.py:871, tui.py:2459, :2496)	path stored on the row as run_log
	decider-B.pid/.log	decider server pid and output	cli.py:1566-1608	cactus decider status/stop

**Locations**

- cactus.db: `CACTUS_DB`; else `$XDG_DATA_HOME/cactus/cactus.db` (default `~/.local/share`) if it exists; else legacy `qaui/qaui.db` if it exists; else the XDG path, created (store.py:233-237). Empty `CACTUS_DB` raises.
- Delivery map: `CACTUS_POKE_WEBHOOKS`, else `~/.config/cactus/poke-webhooks.json` (poke.py:67, :80).
- tui.json: `$XDG_CONFIG_HOME/cactus/tui.json`, else `~/.config/cactus/tui.json` (tui.py:92).
- mcp.log: `CACTUS_MCP_LOG`, else beside the database; `0` or empty disables (mcp.py:78).
- garden.json, decider-B.pid/.log: beside the database.
- Records: under the row's project root, not the caller's (record.py:34). `CACTUS_RECORDS=0` disables.

**Hops**

1. Ask. `cli.cmd_ask` validates, `Store.ask` inserts under `BEGIN IMMEDIATE` (store.py:897) and numbers `q{N}` per project. No record written. Row text is agent-authored and may contain anything.
2. Wait. `Store.wait_for_answer` (store.py:1960) polls the row. Blocking row: until status leaves `open`/`elaborate`. Non-blocking row (steer/notify/review/plan/data, `--no-block`): until (status, answer count) differs from the snapshot taken at wait start (q459). tui, watch, www, monitor poll `cursor()` (tui.py:1808, watch.py:137, www.py:569, monitor.py:339).
3. Answer. `Store.answer` inserts into `answers` under `BEGIN IMMEDIATE` (store.py:1013), then `_record` (store.py:1032) writes the decision record. Clear, reopen, elaborate and edit also write or update it (see Stores). **Sensitive:** free text typed by the human lands in the DB and in a markdown file inside the project tree, where git can pick it up.
4. Delivery (the mod). After an answer, `deliver_if_mapped` (poke.py:149) looks up the owner's entry. Callers: cli.py:745 (`cactus answer`), cli.py:888 (`cactus exec` on a run row), tui.py:3668 and siblings, www.py:606. No entry: nothing. `{"herdr": true}` with a pane: `herdr agent prompt PANE` with `ANSWERED_MESSAGE` (poke.py:39); `CACTUS_POKE` overrides the transport. `{"url": ...}`: POST `{"agent", "message"}` (poke.py:196); `CACTUS_POKE` is ignored. The message is fixed and carries no answer text. The agent reads the answer itself with `cactus feed`. Failure never rolls back the answer.
5. Register delivery. `cactus deliver herdr|webhook URL|off --agent ID` (cli.py:1842) rewrites the map atomically, mode 0600, other entries kept (poke.py:125). No DB change. Codex `session-start.sh:18` runs `cactus deliver herdr --agent $agent` when `HERDR_PANE_ID` is set. **Sensitive:** a webhook entry may hold an `authorization` header (poke.py:203), added by hand-editing the map; `cactus deliver` never writes one. The map file is the only place it lives.
6. Codex frontier. `plugins/cactus/hooks/frontier.sh` on each user turn reads `cactus list -s any --agent ID --json`, prints the first five rows (elaborate, answered, open/live) with the full latest answer into the Codex turn (:18). It then runs `cactus clear KEY --agent ID` (:59) on printed answered rows whose act is not review/plan/data. **Sensitive:** human answer text enters the Codex model context. Clear retires the row; the transcript stays.
7. Stop gate. `hooks/stop_fork.py` exits silently when cactus_identity.py resolves an agent (:36-37) and `cactus list -s open --agent ID --json` is non-empty (:38, q469). `list` scopes to the current project: an open row elsewhere does not silence it. Otherwise it reads the Claude transcript from the hook payload's `transcript_path` (:55), read-only, looking for a cactus ask/edit/plan/review or AskUserQuestion. **Sensitive:** the whole conversation transcript is read; nothing from it is written.
8. Rank. The TUI worker `_auto_work` (tui.py:1873, touches no Store) sends each open choice row (text, context, choices) to `rank.classify` (tui.py:1888). Backends: apint (on-device), else `claude -p --model haiku` with the row on stdin (rank.py:10, :48, :159). `CACTUS_RANK` overrides both (rank.py:13). **Sensitive:** on the Haiku fallback, row text goes to Anthropic's API.
9. Auto-decider. Only rows `rank` gates (reversible, low complexity) go to `decide.propose` (decide.py:121), POST to `127.0.0.1:8000` (strands) or `:8001` (clef), or `CACTUS_DECIDER_URL`. `set_auto` stores the proposal on the row. **Sensitive:** this hop stays on localhost unless `CACTUS_DECIDER_URL` points elsewhere.
10. MCP. Each tool call is one `cactus --json` subprocess; `mcp.py:117` logs its argv. **Sensitive:** argv for `cactus_ask` carries row text and context into mcp.log.
11. Run output. `R` / `cactus exec` spill full command output to a `mkstemp` file (shell.py:113) and store its path, exit code and tail on the row.
12. Clipboard. TUI copy puts a data row's chunk (tui.py:3352) or a row's command (tui.py:2358) on the OS clipboard via `shell.copy` (shell.py:41: pbcopy, wl-copy, xclip, xsel). **Sensitive:** row text leaves cactus for the clipboard.

**Retention**

No retention is expressed anywhere in the code. Nothing expires on a timer.

	data	removed by
	DB rows, answers	`cactus clear --purge` only (store.py:1145). `clear` keeps the row.
	decision records	never, by cactus
	delivery map entry	`cactus deliver off --agent ID`
	mcp.log	never; appended, no rotation
	spill logs	never; left in the temp dir for the OS
	garden.json	`cactus garden --clear`
	tui.json, decider pid/log	never, by cactus
