# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

    PYTHONPATH=src python3 -m cactus --help      # run from the checkout
    uv tool install --editable .               # install the `cactus` console script
    CACTUS_DB=/tmp/scratch.db PYTHONPATH=src python3 .ai/tmp/test_tui.py

There is no test suite and no linter. Verification is throwaway scripts in
`.ai/tmp/` that drive the real code against a scratch database — Textual apps via
`App.run_test()` and a `Pilot`, the CLI via subprocesses. Write new ones the same
way; they are gitignored and not part of the package.

Always point `CACTUS_DB` at a scratch file when testing. The default database is the
user's live inbox at `~/.local/share/cactus/cactus.db`.

## Architecture

Four layers, one direction of dependency:

    scope.py     cwd -> (project_root, cwd); git toplevel or the directory itself
    store.py     all SQLite; the only module that touches the database
    cli.py       argparse verbs, scope resolution, JSON/text rendering, --wait
                 plus AGENT_HELP, the agent-facing roadmap behind --agent-help
    tui.py       Textual answering surface (human): question rail + detail card
    watch.py     Textual read-only feed (human)
    monitor.py   plain-stdout event stream (agent): one line per transition

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
- `clear` retires a question and keeps the transcript; only `clear --purge`
  deletes rows.
- `reopen` is undo's store primitive: status back to `open`, answer row deleted.
  It cannot recall an answer an agent already read — `wait_for_answer` returns
  the moment the status leaves `open`.
