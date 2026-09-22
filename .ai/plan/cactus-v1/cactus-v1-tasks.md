# cactus v1 — tasks

## 1. Rename

- [x] `src/qaui/` -> `src/cactus/`; update intra-package imports
- [x] `pyproject.toml`: package name, console script `cactus`, alias `cac`
- [x] `QAUI_DB` -> `CACTUS_DB` in store.py, CLAUDE.md, `.ai/tmp/` scripts
- [x] `default_db_path`: `~/.local/share/cactus/cactus.db`, falling back to the
      qaui path when the new one is absent, with a printed move instruction
- [x] README.md and CLAUDE.md prose
- [x] Reinstall: `uv tool install --editable .`
- [ ] Repository directory rename, last (user-run; renaming the session's
      own working directory from inside it is left to the human)

## 2. Schema

- [x] `ACTS = ("ask", "steer", "run", "seen", "review", "plan")`
- [x] `PERSISTENT_ACTS = ("review", "plan")`
- [x] `STATUSES` gains `live`
- [x] `ALTER TABLE questions ADD COLUMN act TEXT NOT NULL DEFAULT 'ask'`
- [x] `ALTER TABLE questions ADD COLUMN agent TEXT`
- [x] `reviews` table, 1:1, cascade on delete
- [x] `steps` table, 1:N, `UNIQUE(question_id, idx)`, cascade on delete
- [x] Rebuild `answers` without `UNIQUE(question_id)`, in one transaction
- [x] Idempotent migration guard for existing databases
- [x] `idx_q_agent` on `(agent, status)`
- [x] `Question` dataclass carries `act`, `agent`, `review`, `steps`, `answers`

## 3. Store semantics

- [x] Persistent acts insert with status `live`, never auto-transition
- [x] `wait_for_answer` ignores `live` rows; called on one, exits 1
- [x] `answer()` appends rather than replaces; current answer is latest
- [x] `reopen()` deletes the latest answer row only
- [x] Sidecar writes bump the parent `updated_at`
- [x] `cursor()` still reflects sidecar-only changes

## 4. Acts in the CLI

- [x] `ask --act <name>`, defaulting to `ask`
- [x] `--agent <id>`, defaulting to `HERDR_PANE_ID` when set
- [x] Reject illegal act/shape pairs at parse time, exit 1
- [x] `review` verb: `--look-at --run --pass --fail --then`
- [x] `plan` verb: repeatable `--step`, `--done <idx>`, `--undone <idx>`
- [x] `answer --dismiss` for `seen`
- [x] `list --act <name>`, repeatable; `list -s live`
- [x] AGENT_HELP documents acts, the shape pairing table, and persistence

## 5. Feed

- [x] `cactus feed --json` emitting `{cursor, questions}`
- [x] Rows embed `review`, `steps`, and the `answers` log
- [x] `--agent`, `--act`, `--here` filters
- [x] Exit 3 when filters match nothing

## 6. Monitor

- [x] Emit `verdict` events on answers to `live` rows
- [x] Include `act` on every event line
- [x] Sidecar changes surface as `step` / `review` events

## 7. Surfaces

- [x] TUI renders `act` as a rail badge and `live` distinctly from `open`
- [x] TUI ignores `agent`
- [x] Review card shows look-at / run / pass / fail / then
- [x] Keys `C` copy, `R` run in the row's cwd, `p` poke the owner
      (lowercase c and r were already clear and refresh)
- [x] `r` streams stdout and stderr live into the card, never auto-runs
- [x] A key opens the full captured output of the last `r` run
- [x] Plan card lists steps; a key toggles done
- [x] `cactus step --done <idx>` lets an agent toggle the same state
- [x] `seen` dismisses on a single key
- [x] Rail blocks stay a fixed 4 rows

## 8. Verify

- [x] `.ai/tmp/test_acts.py` — every act round-trips ask, list, answer
- [x] `.ai/tmp/test_persistent.py` — a `live` row takes two verdicts; the log
      holds both; `wait_for_answer` does not block on it
- [x] `.ai/tmp/test_feed.sh` — cursor stability, filters, exit 3
- [x] `.ai/tmp/test_migrate.py` — a qaui-era database opens, reads as `ask`, and
      its single answers survive the constraint rebuild
- [x] `.ai/tmp/test_sidecar_cursor.py` — a step toggle moves the cursor
- [x] Existing `.ai/tmp/` scripts pass after the rename
- [x] `.ai/tmp/test_tui_acts.py` — rail badges, review card, R/O/d, step digits
- [ ] Manual: review row runs a command with `R` and takes a fail verdict

## 9. Poke

- [x] `poke.py` — pluggable transport, default `herdr agent prompt`
- [x] `cactus poke KEY` / `--agent ID` / `-m TEXT`
- [x] TUI `p` nudges the focused row's agent, reporting through the status bar
- [x] `--agent ""` disowns explicitly; an omitted flag inherits the pane
- [x] `.ai/tmp/test_poke.py` and CLI cases in `test_cli_acts.sh`
- [ ] Confirm the herdr transport against a real pane the user nominates

## 10. Handoff

- [ ] `.ai/REVIEW.md`: the `cactus answer` command shape c100 calls
- [ ] Confirm exit-code contract for a doubly-answered non-persistent row
