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
	cactus.db	questions, answers, reviews, steps, project_settings (`store.py` `SCHEMA`)	Store only: `store.py` `Store.ask`, `Store.answer`, `Store.clear`, `Store.purge`, `Store.set_run_result`, `Store.set_auto`	every surface via Store; change token cursor() `store.py` `Store.cursor`
	poke-webhooks.json	per-agent delivery entry: {"herdr": true} or {"url": URL} plus optional authorization/headers	`poke.py` `write_delivery` (from `cli.py` `cmd_deliver`, which writes only {"url"} or {"herdr"}); authorization/headers by hand-edit only	`poke.py` `load_webhooks`, `delivery_entry`
	.ai/cactus/*.md	decision record per row: question, choices, verdicts	`record.py` `write_record`, via `store.py` `Store._record` (from `Store.answer`, `Store.clear`, `Store.reopen`, `Store.elaborate_request`) and `Store._record_if_exists` (from `Store.edit`, `Store.unelaborate`)	humans, git
	mcp.log	one line per MCP request, incl. run argv	`mcp.py` `_log`	humans
	tui.json	TUI settings, pinned project path	`tui.py` `_save_tui_settings`	`tui.py` `_load_tui_settings`
	garden.json	field pile cells	`garden.py` `save` (`tui.py` `CactusApp._save_garden`, `fieldproc.py` `GardenSync.save`)	`garden.py` `load_into`
	cactus-KEY-*.log	full output of a run/review command	`shell.py` `spill` (`cli.py` `cmd_exec`, `tui.py` `CactusApp._finish_run_row`, `CactusApp._finish_output`)	path stored on the row as run_log
	decider-B.pid/.log	decider server pid and output	`cli.py` `cmd_decider`	cactus decider status/stop

**Locations**

- cactus.db: `CACTUS_DB`; else `$XDG_DATA_HOME/cactus/cactus.db` (default `~/.local/share`) if it exists; else legacy `qaui/qaui.db` if it exists; else the XDG path, created (`store.py` `default_db_path`). Empty `CACTUS_DB` raises.
- Delivery map: `CACTUS_POKE_WEBHOOKS`, else `~/.config/cactus/poke-webhooks.json` (`poke.py` `DEFAULT_WEBHOOKS_PATH`, `webhooks_path`).
- tui.json: `$XDG_CONFIG_HOME/cactus/tui.json`, else `~/.config/cactus/tui.json` (`tui.py` `_tui_settings_path`).
- mcp.log: `CACTUS_MCP_LOG`, else beside the database; `0` or empty disables (`mcp.py` `_log_path`).
- garden.json, decider-B.pid/.log: beside the database.
- Records: under the row's project root, not the caller's (`record.py` `RECORDS_DIRNAME`). `CACTUS_RECORDS=0` disables.

**Hops**

1. Ask. `cli.cmd_ask` validates, `Store.ask` inserts under `BEGIN IMMEDIATE` (`store.py` `Store.ask`) and numbers `q{N}` per project. No record written. Row text is agent-authored and may contain anything.
2. Wait. `Store.wait_for_answer` (`store.py` `Store.wait_for_answer`) polls the row. Blocking row: until status leaves `open`/`elaborate`. Non-blocking row (steer/notify/review/plan/data, `--no-block`): until (status, answer count) differs from the snapshot taken at wait start (q459). tui, watch, www, monitor poll `cursor()` (`tui.py` `CactusApp._reload_locked`, `watch.py` `WatchApp._poll`, `www.py` `_Handler._handle_events`, `monitor.py` `run_monitor`).
3. Answer. `Store.answer` inserts into `answers` under `BEGIN IMMEDIATE` (`store.py` `Store.answer`), then `_record` (`store.py` `Store._record`) writes the decision record. Clear, reopen, elaborate and edit also write or update it (see Stores). **Sensitive:** free text typed by the human lands in the DB and in a markdown file inside the project tree, where git can pick it up.
4. Delivery (the mod). After an answer, `deliver_if_mapped` (`poke.py` `deliver_if_mapped`) looks up the owner's entry. Callers: `cli.py` `cmd_answer` (`cactus answer`), `cli.py` `cmd_exec` (`cactus exec` on a run row), `tui.py` `CactusApp._submit_answer` and siblings, `www.py` `_Handler._handle_answer`. No entry: nothing. `{"herdr": true}` with a pane: `herdr agent prompt PANE` with `ANSWERED_MESSAGE` (`poke.py` `ANSWERED_MESSAGE`); `CACTUS_POKE` overrides the transport. `{"url": ...}`: POST `{"agent", "message"}` (`poke.py` `_post_webhook`); `CACTUS_POKE` is ignored. The message is fixed and carries no answer text. The agent reads the answer itself with `cactus feed`. Failure never rolls back the answer.
5. Register delivery. `cactus deliver herdr|webhook URL|off --agent ID` (`cli.py` `cmd_deliver`) rewrites the map atomically, mode 0600, other entries kept (`poke.py` `write_delivery`). No DB change. Codex `session-start.sh:18` runs `cactus deliver herdr --agent $agent` when `HERDR_PANE_ID` is set. **Sensitive:** a webhook entry may hold an `authorization` header (`poke.py` `_post_webhook`), added by hand-editing the map; `cactus deliver` never writes one. The map file is the only place it lives.
6. Codex frontier. `plugins/cactus/hooks/frontier.sh` on each user turn reads `cactus list -s any --agent ID --json`, prints the first five rows (elaborate, answered, open/live) with the full latest answer into the Codex turn (:18). It then runs `cactus clear KEY --agent ID` (:59) on printed answered rows whose act is not review/plan/data. **Sensitive:** human answer text enters the Codex model context. Clear retires the row; the transcript stays.
7. Stop gate. `hooks/stop_fork.py` exits silently when `cactus_identity.py` `resolve_agent` resolves an agent and `cactus list -s open --agent ID --json` is non-empty (`stop_fork.py` `main`, q469). `list` scopes to the current project: an open row elsewhere does not silence it. Otherwise it reads the Claude transcript from the hook payload's `transcript_path` (:55), read-only, looking for a cactus ask/edit/plan/review or AskUserQuestion. **Sensitive:** the whole conversation transcript is read; nothing from it is written.
8. Rank. The TUI worker `_auto_work` (`tui.py` `CactusApp._auto_work`, touches no Store) sends each open choice row (text, context, choices) to `rank.classify` (`rank.py` `classify`). Backends: apint (on-device), else `claude -p --model haiku` with the row on stdin (`rank.py` `classify`, `CLAUDE`, `_run`). `CACTUS_RANK` overrides both (`rank.py` `classify`). **Sensitive:** on the Haiku fallback, row text goes to Anthropic's API.
9. Auto-decider. Only rows `rank` gates (reversible, low complexity) go to `decide.propose` (`decide.py` `propose`), POST to `127.0.0.1:8000` (strands) or `:8001` (clef), or `CACTUS_DECIDER_URL`. `set_auto` stores the proposal on the row. **Sensitive:** this hop stays on localhost unless `CACTUS_DECIDER_URL` points elsewhere.
10. MCP. Each tool call is one `cactus --json` subprocess; `mcp.py` `_run` logs its argv. **Sensitive:** argv for `cactus_ask` carries row text and context into mcp.log.
11. Run output. `R` / `cactus exec` spill full command output to a `mkstemp` file (`shell.py` `spill`) and store its path, exit code and tail on the row.
12. Clipboard. TUI copy puts a data row's chunk (`tui.py` `CactusApp.action_select_choice`) or a row's command (`tui.py` `CactusApp.action_copy_command`) on the OS clipboard via `shell.copy` (`shell.py` `copy`: pbcopy, wl-copy, xclip, xsel). **Sensitive:** row text leaves cactus for the clipboard.

**Retention**

No retention is expressed anywhere in the code. Nothing expires on a timer.

	data	removed by
	DB rows, answers	`cactus clear --purge` only (`store.py` `Store.purge`). `clear` keeps the row.
	decision records	never, by cactus
	delivery map entry	`cactus deliver off --agent ID`
	mcp.log	never; appended, no rotation
	spill logs	never; left in the temp dir for the OS
	garden.json	`cactus garden --clear`
	tui.json, decider pid/log	never, by cactus
