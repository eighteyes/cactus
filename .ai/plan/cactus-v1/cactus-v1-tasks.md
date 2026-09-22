# cactus v1 — tasks

## 1. Rename

- [ ] `src/qaui/` -> `src/cactus/`; update intra-package imports
- [ ] `pyproject.toml`: package name, console script `cactus`, alias `cac`
- [ ] `QAUI_DB` -> `CACTUS_DB` in store.py, CLAUDE.md, `.ai/tmp/` scripts
- [ ] `default_db_path`: `~/.local/share/cactus/cactus.db`, falling back to the
      qaui path when the new one is absent, with a printed move instruction
- [ ] README.md and CLAUDE.md prose
- [ ] Reinstall: `uv tool install --editable .`
- [ ] Repository directory rename, last

## 2. Schema

- [ ] `ACTS = ("ask", "steer", "run", "seen", "review", "plan")`
- [ ] `PERSISTENT_ACTS = ("review", "plan")`
- [ ] `STATUSES` gains `live`
- [ ] `ALTER TABLE questions ADD COLUMN act TEXT NOT NULL DEFAULT 'ask'`
- [ ] `ALTER TABLE questions ADD COLUMN agent TEXT`
- [ ] `reviews` table, 1:1, cascade on delete
- [ ] `steps` table, 1:N, `UNIQUE(question_id, idx)`, cascade on delete
- [ ] Rebuild `answers` without `UNIQUE(question_id)`, in one transaction
- [ ] Idempotent migration guard for existing databases
- [ ] `idx_q_agent` on `(agent, status)`
- [ ] `Question` dataclass carries `act`, `agent`, `review`, `steps`, `answers`

## 3. Store semantics

- [ ] Persistent acts insert with status `live`, never auto-transition
- [ ] `wait_for_answer` ignores `live` rows; called on one, exits 1
- [ ] `answer()` appends rather than replaces; current answer is latest
- [ ] `reopen()` deletes the latest answer row only
- [ ] Sidecar writes bump the parent `updated_at`
- [ ] `cursor()` still reflects sidecar-only changes

## 4. Acts in the CLI

- [ ] `ask --act <name>`, defaulting to `ask`
- [ ] `--agent <id>`, defaulting to `HERDR_PANE_ID` when set
- [ ] Reject illegal act/shape pairs at parse time, exit 1
- [ ] `review` verb: `--look-at --run --pass --fail --then`
- [ ] `plan` verb: repeatable `--step`, `--done <idx>`, `--undone <idx>`
- [ ] `answer --dismiss` for `seen`
- [ ] `list --act <name>`, repeatable; `list -s live`
- [ ] AGENT_HELP documents acts, the shape pairing table, and persistence

## 5. Feed

- [ ] `cactus feed --json` emitting `{cursor, questions}`
- [ ] Rows embed `review`, `steps`, and the `answers` log
- [ ] `--agent`, `--act`, `--here` filters
- [ ] Exit 3 when filters match nothing

## 6. Monitor

- [ ] Emit `verdict` events on answers to `live` rows
- [ ] Include `act` on every event line
- [ ] Sidecar changes surface as `step` / `review` events

## 7. Surfaces

- [ ] TUI renders `act` as a rail badge and `live` distinctly from `open`
- [ ] TUI ignores `agent`
- [ ] Review card shows look-at / run / pass / fail / then
- [ ] Keys `c` copy, `r` run in the row's cwd, `p` push to prompt
- [ ] `r` streams stdout and stderr live into the card, never auto-runs
- [ ] A key opens the full captured output of the last `r` run
- [ ] Plan card lists steps; a key toggles done
- [ ] `cactus step --done <idx>` lets an agent toggle the same state
- [ ] `seen` dismisses on a single key
- [ ] Rail blocks stay a fixed 4 rows

## 8. Verify

- [ ] `.ai/tmp/test_acts.py` — every act round-trips ask, list, answer
- [ ] `.ai/tmp/test_persistent.py` — a `live` row takes two verdicts; the log
      holds both; `wait_for_answer` does not block on it
- [ ] `.ai/tmp/test_feed.py` — cursor stability, filters, exit 3
- [ ] `.ai/tmp/test_migrate.py` — a qaui-era database opens, reads as `ask`, and
      its single answers survive the constraint rebuild
- [ ] `.ai/tmp/test_sidecar_cursor.py` — a step toggle moves the cursor
- [ ] Existing `.ai/tmp/` scripts pass after the rename
- [ ] Manual: review row runs a command with `r` and takes a fail verdict

## 9. Handoff

- [ ] `.ai/REVIEW.md`: the `cactus answer` command shape c100 calls
- [ ] Confirm exit-code contract for a doubly-answered non-persistent row
