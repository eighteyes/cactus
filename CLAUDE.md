# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

    PYTHONPATH=src python3 -m cactus --help      # run from the checkout
    uv tool install --editable .               # install the `cactus` console script
    CACTUS_DB=/tmp/scratch.db CACTUS_POKE=true PYTHONPATH=src python3 .ai/tmp/test_tui.py
    bash .ai/tmp/test_feed.sh                  # CLI-side scripts are shell

There is no test suite and no linter. Verification is throwaway scripts in
`.ai/tmp/` that drive the real code against a scratch database — Textual apps via
`App.run_test()` and a `Pilot`, the CLI via subprocesses. Write new ones the same
way; they are gitignored and not part of the package.

Always point `CACTUS_DB` at a scratch file when testing. The default database is the
user's live inbox at `~/.local/share/cactus/cactus.db`. An empty `CACTUS_DB`
raises rather than falling through, so a failed `mktemp` cannot silently target
it.

Always set `CACTUS_POKE` to something inert when testing. The default transport
is `herdr agent prompt`, which prompts a live agent — so poking any row that
names a real pane with `--agent` interrupts whoever is running there. `cactus
ask` requires `--agent` at the CLI and never defaults it: a bare pane id
outlives the session it named. `Store.ask` itself still leaves `agent`
optional, so legacy and TUI-authored rows can be unowned.

## Architecture

Four layers, one direction of dependency:

    scope.py     cwd -> (project_root, cwd); git toplevel or the directory itself
    store.py     all SQLite; the only module that touches the database
    cli.py       argparse verbs, scope resolution, JSON/text rendering, --wait
                 plus AGENT_HELP, the agent-facing roadmap behind --agent-help
    tui.py       Textual answering surface (human): question rail + detail card
    watch.py     Textual read-only feed (human)
    monitor.py   plain-stdout event stream (agent): one line per transition
    poke.py      contentless nudge to a row's owning agent via $CACTUS_POKE
    shell.py     clipboard copy, command run, and output spill for the TUI

`poke` and `shell` are side leaves, imported lazily at the call site by `cli`
and `tui`; they never touch the store.

`cli.main` resolves scope once, constructs one `Store`, dispatches to a `cmd_*`
function or to `run_tui`/`run_watch`, and closes the store in a `finally`. The
Textual modules are imported lazily inside `main` so agent-side verbs never pay
for them.

`monitor.py` diffs a signature per question between ticks, so it reports content
changes and deletions, not just status flips.

**Two clients, one database.** Agent processes write; the TUI and watch feed are
separate long-lived processes reading the same file. Everything about the store is
shaped by that: WAL mode, `busy_timeout`, autocommit (`isolation_level=None`), and
a `cursor()` change token — `(max(id), max(updated_at))` — that pollers compare
against their last value before re-reading rows. `wait_for_answer` is the agent
side of the same loop, polling `get()` until the status leaves `open`.

**Scope.** Every question stores both `project` (git toplevel) and `cwd`. Agent
verbs filter to the current project by default; the human surfaces span all
projects unless `--here`. `_scope_where` builds that predicate for every query.

**Threading.** `parent_id` self-references with `ON DELETE CASCADE`; a follow-up
inherits its parent's `thread` when none is given. `tree()` walks parents to
children and assigns display depth, promoting orphans whose parent is out of
scope.

## Invariants

- `cursor()` carries a row count alongside the two maxima. Without it, purging
  any row that is not the newest leaves the token unchanged and deletions are
  invisible to every poller.
- `_now()` uses microsecond resolution. Second resolution lets two writes inside
  one second share a cursor token, and pollers silently miss the later write.
- Keys are `q{rowid}`: `ask()` inserts with an empty key, then updates it from
  `lastrowid`. Key and id are the same number in two forms.
- `--json` is accepted before and after the verb. The subparser copy uses
  `default=argparse.SUPPRESS` so an omitted trailing flag cannot clobber a
  leading one.
- Question and rail text is rendered with Textual markup disabled — question text
  is arbitrary agent input and `[` would otherwise open a markup tag.
- Choice strings split on the *first* colon into label and description; `-c`
  values are taken verbatim and never split on commas.
- Exit codes are part of the contract: 0 ok, 1 error, 2 `--wait` timeout, 3 no
  match. `--wait` on an act that never blocks is an error, not a hang.
- `CACTUS_DB` set but empty raises rather than falling through to the default.
  A failed `mktemp` in a test harness would otherwise point the run at the
  user's live inbox, which is the one thing the variable exists to prevent.
- An act is what is being asked for; `kind` stays the shape the answer is
  collected in. `ACT_SHAPES` pairs them and `ask()` refuses the rest.
- `review` and `plan` are persistent: born `live`, never auto-transitioning,
  answerable repeatedly. Their verdicts append, so `answer` is the latest of
  `answers` and undo withdraws only the newest row.
- `ListView` consumes `enter` before an App binding can see it, so the TUI
  triggers submit from `on_list_view_selected`, not from the `enter` binding.
- The TUI rotates over projects with open questions only; `store.projects()`
  still reports drained ones, which the CLI needs for history.
- Rail blocks are a fixed 4 rows and the project header a fixed 1, so an arriving
  or answered question never shifts the others under the reader's eye.
- Typing in the TUI is an explicit mode. Auto-focusing the answer input silently
  retargets `j`, `k`, `s`, `c` and the project brackets into the text field.
- Opening the store applies additive column adds only. The `answers` table
  rebuild that drops `UNIQUE(question_id)` is destructive-shaped — it changes
  the schema under any process holding an older module — so it lives behind
  `cactus migrate --yes` (or `CACTUS_MIGRATE=1` at open). `answer()` refuses on an un-rebuilt database with an
  instruction rather than a SQL error.
- Re-answering a one-shot row that is already `answered` raises
  `AlreadyAnswered` and exits 3. Two surfaces share one inbox, so the second
  tap must not silently overwrite what the first reader saw.
- TUI bindings are gated by `check_action`, so the footer and the keyboard
  agree: no `Run` key on a row with no command, no `d` on a row that is not a
  notice. Textual only re-asks `check_action` when something calls
  `refresh_bindings()` — the footer is stale until `_rebuild_card` or
  `_rebuild_status_bar` calls it, not on every focus change by itself.
- `clear` retires a question and keeps the transcript; only `clear --purge`
  deletes rows.
- `reopen` is undo's store primitive: status back to `open`, answer row deleted.
  It cannot recall an answer an agent already read — `wait_for_answer` returns
  the moment the status leaves `open`. On a *cleared* row it takes a second
  path instead of that delete: `clear` never touched the answers log, review,
  or steps, so restoring only moves `status` back — to `live` for a
  persistent row (every verdict intact), to `answered` for a one-shot row
  that already had one, else `open`. `cli.cmd_reopen` (`cactus reopen KEY...
  --agent ID`) is gated on ownership exactly like keyed `clear`, and refuses
  a key that is not cleared (exit 1) or does not exist (exit 3). The TUI's
  `c` (clear) pushes the row onto the undo stack the same as an answer or a
  skip, so `u` calls `Store.reopen` on it and restores it the same way.
  `monitor.py` reports every move out of `cleared` as `reopened`, whatever
  status it lands on — a restored answered row must not read as a second
  `answered`.
- `recommend` is advisory, not `chosen`: a chosen option is already being
  acted on, a recommended one still waits for the human. It requires choices,
  every label must be real, more than one only when `kind == "multi"`, and
  `confidence` is required with it and refused without it. The TUI preselects
  it — the recommended set on a multi row, the recommended label on a
  choice/confirm row when nothing else is picked or typed.
- `cactus plan --done`/`--undone` take a 1-based step number at the CLI; the
  store's `idx` stays 0-based underneath, and `Step.as_dict` carries both
  (`idx` and `n = idx + 1`) so a consumer never has to offset it itself.
- Enter on a plan row records typed text as a verdict via `Store.answer` and
  never closes the row; `c` is the only close. A lost note is worse than a row
  left open, and an append-only verdict log is what a plan is for.
- An empty multi submit — nothing toggled, nothing typed — is refused with a
  flash rather than stored, so a stray enter cannot record an answer nobody chose.
- `cli.cmd_ask` refuses a missing `--agent` with exit 1 before calling
  `Store.ask`; `Store.ask`'s own `agent` parameter stays optional so the TUI
  and legacy rows are unaffected.
- `cli.cmd_clear` gates on ownership, not `Store.clear`/`Store.purge`, which
  stay mechanism and only gained an `agent` filter. Bulk forms (`-t`,
  `--here`, `--all`) require `--agent` and touch only that agent's rows;
  unowned rows are never touched in bulk. An explicit-key clear refuses the whole call
  if any key is owned by another agent, or by the caller without a matching
  `--agent`; an unowned row clears by key regardless. The TUI's `c` binding
  calls `Store.clear` directly with no agent filter, so a human can still
  clear any row.
- `monitor.run_monitor(agent=...)` still polls every agent's rows; only
  emission is filtered. `_snapshot` carries each row's owner alongside its
  signature so a `gone` event, read after the row is already deleted, can
  still be judged against the agent that owned it.
- Decision records (`record.py`) are written by `Store` after the DB commit,
  in `answer`, `clear`, and `reopen` only — never on `ask` or `purge` — and
  fail soft: any write error is a warning, not a rollback. Rendering is
  idempotent per row state. `CACTUS_RECORDS=0` disables writing; tests must
  set it or run inside a temp git repo, since a record lands in the row's
  *project root*, not the caller's scratch DB.
- `Store.set_review` merges: each `cactus review` call only touches the
  fields it was given, `None` (an omitted flag) keeps the stored value, and
  `""` (`--run ""`) clears it explicitly. A second call can no longer wipe
  what an earlier one set.
- The TUI undo stack (`action_undo`) is a full LIFO stack, not a single slot:
  each `u` pops and restores one entry, walking past any whose row was purged
  out from under it (`reopen` raising `KeyError`). Every exit from
  `action_undo` — restored a row, or ran out of stack trying — leaves the
  status bar current, so draining the stack via failed entries still flashes
  "nothing to undo" instead of going silent.
