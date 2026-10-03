# Troubleshooting

Symptom, cause, fix. Covers delivery (`cactus deliver`), Codex mod mode, and the Claude Stop hook.

Exit codes: 0 ok, 1 error, 2 `--wait` timeout, 3 no match.

## cactus deliver

**`cactus deliver: error: the following arguments are required: --agent`**
- Cause: no `--agent`. Exit 1.
- Fix: `cactus deliver herdr --agent ID`.

**`cactus: deliver needs a non-empty --agent`**
- Cause: `--agent` was blank or whitespace. Exit 1.
- Fix: pass the real agent id.

**``cactus: URL only goes with `deliver webhook` ``**
- Cause: a URL after `herdr` or `off`. Exit 1.
- Fix: drop the URL, or use `cactus deliver webhook URL --agent ID`.

**`cactus: deliver webhook needs a URL`**
- Cause: `deliver webhook` with no URL, or a blank one. Exit 1.
- Fix: `cactus deliver webhook URL --agent ID`.

**`cactus: no match`** (exit 3)
- Cause: `cactus deliver --agent ID` or `cactus deliver off --agent ID` on an agent with no entry.
- Fix: none needed. Set one with `cactus deliver herdr --agent ID`.

## Delivery map

The map is `~/.config/cactus/poke-webhooks.json`, or `CACTUS_POKE_WEBHOOKS` when set. Each key is an agent id; each value is `{"herdr": true}` or `{"url": URL}`.

**`cannot read webhook map PATH: ...`**
- Cause: the file is unreadable or not valid JSON.
- Fix: repair the JSON, or point `CACTUS_POKE_WEBHOOKS` at another file.

**`webhook map PATH must be a JSON object keyed by agent id`**
- Cause: the top level is a list, string or number.
- Fix: make it an object: `{"AGENT": {"herdr": true}}`.

**`webhook map entry for 'AGENT' must be an object`**
- Cause: that agent's entry is a string, bool or list.
- Fix: `cactus deliver herdr --agent AGENT` (or `webhook URL`) rewrites the entry.

## After an answer

**`auto-poke: ...` on stderr after `cactus answer`, or `cactus exec` on a `run` row**
- Cause: the row's owner has a delivery entry and was reached. Informational.
- Fix: none. `--json` suppresses it.

**`cactus: answer saved; webhook poke failed: ...`** (CLI) / **`answered; webhook poke failed: ...`** (TUI flash)
- Cause: the answer is stored; delivery raised an error.
- Fix: webhook entry: check the URL. herdr entry: check the row's pane and session still exist.

**herdr entry set, agent never prompted**
- Cause, one of:
  - the row has no herdr pane stamp; delivery skips it silently
  - `CACTUS_POKE` is set and replaces the herdr transport
  - the entry also has a `url` key, which makes it a webhook entry
- Fix: post rows from inside the herdr pane; unset `CACTUS_POKE`; drop `url` with `cactus deliver herdr --agent ID`.

## Codex mod mode

**Session start never prints `Cactus registered herdr delivery for ID: answers prompt this pane.`**
- Cause, one of:
  - `HERDR_PANE_ID` was unset
  - `cactus deliver herdr` failed; the hook hides its errors
  - `cactus` or `jq` is not on `PATH`
  - the payload has no `session_id`
  - the project is disabled; the hook prints `Cactus is disabled for this project.` instead
- Fix: start Codex inside a herdr pane, or run `cactus deliver herdr --agent ID` by hand to see the error.

**An answered row vanished from the frontier**
- Cause: the frontier hook printed its answer last turn, then cleared it (`cactus clear KEY --agent ID`). Review, plan and data rows are never auto-cleared.
- Fix: none. `cactus list -s any --agent ID` still shows it as `cleared`.

**An answer is missing from the frontier**
- Cause: the frontier prints the first five rows (elaborate, then answered, then open/live). Rows past five wait.
- Fix: act on and clear the shown rows; the rest surface on a later turn. Read one now with `cactus get KEY --json`.

**Frontier prints nothing**
- Cause: no rows for this agent, the project is disabled, `cactus`/`jq` is not on `PATH`, or the payload has no `session_id`.
- Only cleared rows: the frontier prints its `Cactus mod mode (plugin loaded)...` header line and no rows.
- Fix: check `cactus project-status --json` and `cactus list -s any --agent ID`.

## Claude Stop hook

**Stop hook never blocks**
- Cause, one of:
  - the agent has an `open` row in this project; `live` and `elaborate` rows do not count
  - `CACTUS_STOP_HOOK=0` is set
  - the project is disabled
  - `stop_hook_active` is true (the hook already blocked once this stop)
  - a task-notification or a cross-session message opened the turn
  - `cactus` is not on `PATH`
  - the payload has no `transcript_path`, or the transcript is unreadable
- Fix: expected for the first five. Check with `cactus list -s open --agent ID --json`.

**Stop hook blocks: `the turn ended without a fork; ...`**
- Cause: the turn ran no `cactus ask`, `edit`, `plan` or `review` (or `cac` form) and no AskUserQuestion, and the agent has no open row.
- Fix: post the next fork with `cactus ask ... --agent ID`, or set `CACTUS_STOP_HOOK=0`.
