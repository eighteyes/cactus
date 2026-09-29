# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

    PYTHONPATH=src python3 -m cactus --help      # run from the checkout
    uv tool install --editable .               # install the `cactus` console script
    uv sync --group dev && uv run pytest        # the suite, tests/
    uv run pytest tests/test_tui.py -q         # one file
    CACTUS_DB=/tmp/scratch.db CACTUS_POKE=true PYTHONPATH=src python3 .ai/tmp/probe_footer.py

The suite lives in `tests/`, pytest with pytest-asyncio in auto mode. There is
no linter. `tests/conftest.py` gives every test a scratch database, an inert
poke transport, and records off; use its `store`, `project`, and `cli`
fixtures rather than setting the env by hand. One file per module: store, cli,
monitor, tui (Textual `App.run_test()` and a `Pilot`), hooks (the bash hook
scripts run against a `cactus` shim), poke. A test that exposes a bug is
marked `xfail` with the reason, never deleted, and the fix removes the mark.
Throwaway probes still go in `.ai/tmp/` (gitignored); a probe worth keeping
becomes a test.

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
    mcp.py       stdio MCP server (agent hosts such as Claude Desktop): each
                 tool is one `cactus --json` subprocess, so cli.py stays the
                 only validator; dependency-free JSON-RPC. Launched from
                 source by server/cactus-mcp (plugin .mcp.json, Desktop config)

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
- Keys number per project (q166): `ask()` inserts with an empty key inside a
  `BEGIN IMMEDIATE`, then updates it to `q{num}` where `num` is
  `MAX(num) WHERE project=?` plus one — race-free because the transaction
  holds SQLite's write lock across both the read and the insert. `key` stays
  unique only within `(project, key)`, not globally, so a bare `qN` needs a
  project to resolve unambiguously; `Store.resolve_ref` accepts a bare key
  (the caller's own project), `LABEL:qN`, or `/abs/path:qN`, and raises
  `AmbiguousLabel` when two projects share a basename. `id` (the row's
  AUTOINCREMENT rowid) is still globally unique and is what every foreign key
  and internal reload (`_get_by_id`) uses — `key` is display and lookup only.
  Relaxing `key`'s UNIQUE constraint is a table rebuild, so it follows the
  same destructive-shaped pattern as the `answers` rebuild: additive on open
  (a `num` column, backfilled from each row's existing key text), gated
  behind `cactus migrate --yes` (`needs_key_rebuild` / `_drop_key_uniqueness`).
  Until migrated, `ask()` keeps the old global `q{rowid}` numbering, so an
  un-migrated database behaves exactly as before.
- `--json` is accepted before and after the verb. The subparser copy uses
  `default=argparse.SUPPRESS` so an omitted trailing flag cannot clobber a
  leading one.
- Question and rail text is rendered with Textual markup disabled — question text
  is arbitrary agent input and `[` would otherwise open a markup tag.
- Choice strings split on the *first* colon into label and description; `-c`
  values are taken verbatim and never split on commas.
- Exit codes are part of the contract: 0 ok, 1 error, 2 `--wait` timeout, 3 no
  match. `--wait` on an act that never blocks is an error, not a hang — and
  `cmd_ask` rejects it before calling `Store.ask`, so a doomed `--wait` never
  leaves an orphan row behind.
- argparse usage errors (`cactus: error: ...`) exit 1, not argparse's default
  2 — `_ArgumentParser.error` overrides it, on the main parser and every
  subparser alike, because 2 is reserved for `--wait` timeout everywhere else.
- `Store.answer` refuses: a label not among the row's choices (names the
  valid labels), an empty answer (no selection, no text, no `--skip`), free
  text on a row posted with `--no-free`, and answering a `cleared` row
  (names `cactus reopen KEY --agent ID`). All raise `ValueError`, exit 1.
- Every verb that takes a key (`get`, `answer`, `clear`, `reopen`, `poke`,
  `review`, `plan`) exits 3 on a missing key, one stderr line — a miss, not
  a malformed call.
- `cactus ask --act A -c ...` refuses when `ACT_SHAPES[A] == ("text",)`
  (`notify`, `plan`): those acts collect text only, and forcing `kind="text"`
  while keeping the `-c` choices would strand them unread on the row.
- `Store(path)` raises `ValueError` — never lets an exception escape as a
  traceback — for `path=""` (same rule as an empty `CACTUS_DB`) and for a
  parent directory `mkdir` cannot create; `main()` turns both into exit 1.
- `--tui`, `--watch`, `--monitor` are mutually exclusive; `--tui`/`--watch`
  refuse a non-tty stdout. Checked in `main()` before `Store` is opened.
- Every "nothing matched" exit 3 (`list`, `feed`, `get --answered-only`,
  `threads`, `projects`) prints one `cactus: no match` stderr line — a
  `--json` caller ignores stderr, so the line costs it nothing.
- `_print_questions` (the text renderer behind `get`/`list`/`reopen`) shows
  a review row's verify block, a persistent row's whole verdict log (not
  just the latest), and a plan row's steps 1-based with `[x]`/`[ ]`.
- `WatchApp.on_mount` puts the scope label ahead of the db path in
  `sub_title` — Header truncates from the end, and a long path is the part
  that can afford to lose its tail.
- `CactusApp.on_event` clears `flash` on every keypress ahead of binding
  dispatch (guarded by `free_text_mode`), so a stale flash from an unrelated
  action does not linger past the next keypress that isn't a row move; an
  action fired by that same key still gets to set its own fresh flash after.
- `cli._msg(exc)` strips `str(KeyError(...))`'s Python-repr quoting before
  it reaches stderr — every `cactus: {exc}` print goes through it.
- `cactus ask` refuses before touching the store: whitespace-only text,
  duplicate choice labels, `--multi` with `--confirm`, a confirm-shaped row
  (explicit `--confirm` or an act whose only shape is confirm) given a
  choice count other than 2, and `--timeout` without `--wait` (`get` refuses
  the same `--timeout`-without-`--wait` case).
- `cactus feed` always emits JSON; `--json` is accepted as a no-op so a
  caller can pass it to every verb uniformly.
- `on_key` also catches `y`/`n` on a non-confirm row (check_action gates the
  binding off there) and flashes why, the same pattern as the `u` undo gate.
- `p` (poke) binds only on a row `poke.reachable` accepts: an owner plus one
  of an override transport (`CACTUS_POKE`), a webhook mapped to that agent,
  or the row's herdr `pane` stamp. herdr resolves a prompt target by pane id
  (`w3B:p3`), never by the conversation id cactus stores as `agent`, so the
  default transport prompts `{target}` = the pane and refuses a row without
  one; `{agent}` stays the owner for templates and webhooks. Every caller
  (`tui`, `cli poke KEY`, `www`) passes `pane=q.pane`; `cactus poke --agent`
  alone has no pane and only works through an override or a webhook. The
  footer omits `p poke` where unreachable and `on_key` flashes why.
- `v` (visit) binds only on a row with a herdr `pane` stamp and runs
  `herdr agent focus {pane}` (`poke.visit`; `CACTUS_VISIT` overrides, and
  tests set it inert). No owner or webhook fallback: without a pane there is
  no conversation on screen to jump to, so the footer omits it and `on_key`
  flashes why, same as `p`.
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
- Rail blocks are a fixed 4 rows and the project header a fixed 1, so an
  arriving or answered question never shifts the others under the reader's eye.
  There is no project strip (q226): the header names the current project and
  `[ ]` rotates; `--here` pins one project.
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
- `Store.answer` refuses, exit 1: an off-menu label (not one of the row's
  choices), an empty answer (nothing selected, nothing typed, and not
  `--skip`), an answer on a `cleared` row (`cactus reopen` first), and free
  text on a row posted with `--no-free`. `cli.cmd_ask` refuses `--no-free`
  up front when the resulting row would have no choices — a no-free text row
  could never be answered.
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
  `answered`. It also reports any drop in the answers log — an undone
  one-shot answer or a withdrawn verdict on a persistent row — as `reopened`,
  never `asked`/`verdict`; only a rising answer count reads as a fresh
  arrival or verdict.
- `cactus plan --step` appends to the existing steps and keeps their done
  flags; `--reset-steps` replaces the list with this call's `--step` values
  and clears every done flag.
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
- `monitor.run_monitor(agent=...)` never streams `asked` (q319): under
  that filter an arriving row is one the agent posted itself, or one the
  session-start hook already listed after a rehome, and every line lands in
  the agent's conversation. `--replay` still lists the inbox first, `asked`
  included, when asked to. Only a library caller without `agent` still gets
  `asked`; the CLI refuses `--monitor` without `--agent`, so no stream a
  human or agent starts from the shell ever carries it. It never streams
  `edited` either (q334): `cactus edit` is ownership-gated in cli.py with no
  TUI equivalent, so under an agent filter an `edited` event is always that
  agent's own edit echoed back. `--once` ignores both for the same reason a
  bare `asked` never fires it — neither ends a background wait for a verdict
  that never arrived.
- `monitor.run_monitor(agent=...)` still polls every agent's rows; only
  emission is filtered. `_snapshot` carries each row's owner alongside its
  signature so a `gone` event, read after the row is already deleted, can
  still be judged against the agent that owned it.
- Decision records (`record.py`) are written by `Store` after the DB commit,
  in `answer`, `clear`, and `reopen` only — never on `ask` or `purge` — and
  fail soft: any write error is a warning, not a rollback. Rendering is
  idempotent per row state. `CACTUS_RECORDS=0` disables writing; tests must
  set it or run inside a temp git repo, since a record lands in the row's
  *project root*, not the caller's scratch DB. The filename is
  `q{N}-{id}-{slug}.md`, not just `q{N}-{slug}.md` (q341): `id` is the row's
  globally unique rowid, because `key` (`q{N}`) numbers per project (q166)
  and a reused key across projects or numbering schemes would otherwise
  overwrite an older row's file.
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
- `Store.clear(record=...)` decides whether the clear writes a decision
  record. `cli.cmd_clear` (agent-initiated) passes `record=False`; the TUI's
  `c` keeps the default `True` and writes `declined`/`retired` as before.
  `Store.purge` never wrote records and is unaffected.
- A `run` act row's captured outcome — `run_exit`, `run_tail` (JSON list),
  `run_log` — lives on the row itself, additive columns like every other.
  `Store.set_run_result` writes them; approving a `run` row (TUI `R`, or y/1
  on a `run` act) always runs the command first and records `approve`
  alongside the result once it finishes, killed or not; `n`/deny records
  without running. `get --json`/`feed` expose it as `"result"`.
  `Store.set_run_result` also accepts a `review` row (q20): the TUI's `R`
  there spills and persists the same `run_exit`/`run_tail`/`run_log` so the
  asking agent's `get --json` sees `"result"` too, but never calls
  `answer()` — a review's pass/fail stays the human's verdict, unlike a
  `run` row's automatic `approve`.
- `cactus --monitor` requires `--agent ID`; humans use `--tui`/`--watch`
  instead. `--once` returns as soon as it emits the first non-`asked` event
  (or a `gone`) — inside the same tick, not after a further poll — and is
  the primary wake-up on Claude Code (q339): the agent arms it with Bash
  `run_in_background`, and its exit re-invokes the agent, mid-turn or hours
  later on an idle session (probed 2026-09-27: a background process lived
  35 min and an idle session woke 2.5 h after its last turn). The Monitor
  tool is not used: its 30-minute cap dies unattended once the turn ends.
  The recipe re-arms first thing on every wake; the exit-to-re-arm gap is
  the one window an event can slip through, so the agent reads the row with
  `get` rather than trusting the event line alone.
- Threads are agent-scoped: a thread name is only unique within one agent's
  rows, not project-wide. The TUI card and `watch` show `agent/thread`
  wherever they show the thread; `list`/`feed -t NAME --agent ID` narrow to
  that agent's rows of that thread the same way any other `agent` filter
  does — no separate mechanism, `_scope_where`'s thread clause and `list`'s
  `agent` clause already AND together.
- Hook identity (`hooks/identity.sh`, q327) resolves the hook payload's
  `session_id` first, then herdr's view of the pane, then `CACTUS_AGENT`.
  herdr infers a conversation id from the transcript file, which at
  SessionStart after `/clear` does not exist yet, so it answers with the
  previous conversation's id and the whole session posts under a dead
  owner. Every root hook reads stdin into `input` before sourcing
  identity.sh; nothing else may consume stdin first.
- Both Stop hooks (`hooks/stop-fork.sh`, `plugins/cactus/hooks/stop.sh`) are
  opt-in: they exit 0 before reading stdin unless `CACTUS_STOP_HOOK=1`. They
  stay registered in hooks.json so opting in needs no settings edit.
  `tests/test_hooks.py`'s `hook_env` sets it on.
- `cactus rehome --agent NEW` (q208) is gated to rows stamped with the
  caller's own `HERDR_PANE_ID`/`HERDR_SESSION` — missing either refuses (exit
  1) rather than guessing which rows are "mine". Scoped to the current
  project, `open`/`live`/`answered` rows only (a cleared row stays retired),
  and to rows whose `agent` differs from `NEW`. `Store.rehome` reassigns and
  bumps `updated_at` in one transaction. It changes `agent` only, which
  `monitor._signature` deliberately excludes, so a rehome itself never reads
  as a spurious `answered`/`verdict`/`asked` — a freshly started
  `--monitor --agent NEW` still sees the moved rows, as an ordinary arrival
  on its first poll.
- `elaborate` (q212) is a status, not a rebuild: `status` has no CHECK
  constraint, so the new value needs only the additive `elaborate`/
  `elaborate_at` columns. `Store.answer` refuses it like `cleared`, exit 1.
  `wait_for_answer` keeps blocking through it — only `open`/`elaborate` keep
  it waiting, any other status returns.
- `Store.edit` is `cactus edit`'s mechanism, gated open/live/elaborate only;
  ownership is the CLI's job, same split as `clear`/`reopen`. `-c` replaces
  the whole choice list and drops any `recommend` (plus its confidence/why)
  naming a label that fell off it. On an `elaborate` row it always clears
  the request and returns status to `open`/`live`, whether or not a field
  actually changed.
- `Store._record_if_exists` (used by `edit` only) writes only when the row's
  record file already exists — an agent's edit is bookkeeping like its own
  `clear`, not a human verdict (records write on human events and answers
  only, 4659beb), and must not conjure a record for a row that never had
  one. `elaborate_request` is human-triggered and always writes, same as
  `clear`/`reopen`. `unelaborate` (q228) instead uses `_record_if_exists`
  like `edit` — it only ever follows an `elaborate_request`, which already
  wrote the record, so it updates that copy and never conjures a fresh one.
- `record.render(event="edit", prior=...)` appends a `## Rewrite` section
  from `prior`'s pre-edit text/context/choices, so the file shows the
  question before (Rewrite) and after (the fields above it) in one document.
  `event="elaborate"` adds an `## Elaborate requested` section instead;
  `event="unelaborate"` (q228) adds a one-line `## Elaborate withdrawn` note,
  never a section of its own prose.
- `questions.last_change` (q228) is the marker that lets the monitor tell an
  agent's `edit` clearing an `elaborate` row apart from a human's
  `unelaborate` withdrawing it — both leave the row at the same status, an
  identical before/after diff otherwise. `unelaborate` stamps `'withdrawn'`,
  `edit` stamps `'edited'` only on the transition out of `elaborate` (a plain
  edit elsewhere leaves it as-is, since that path is already told apart by
  its text/choices/context/recommend diff), and `elaborate_request` clears it
  on entry so a later cycle never reads a stale value. Additive column,
  included in `monitor._signature`; a leaving-`elaborate` transition reads
  `withdrawn` or `edited` from it instead of collapsing both to `edited`.
- `data` (q293/q294) is persistent like review/plan, shape `choice` only, and
  `Store.ask` refuses one with no choices. Each `-c` is a copyable chunk
  (label: body, body may be multi-line); a copy in the TUI appends a verdict
  naming the chunk's label via the ordinary `Store.answer` path. `d`/`c`
  close it the same as any other persistent row.
- `Store.answer` refuses a `selected` label on a choiceless row (`plan`,
  `notify`) — "has no choices; answer with text" — the same off-menu-label
  refusal a row with real choices already gets.
- `cactus list -s` (default `open,live,elaborate`, matching `feed`) accepts
  any comma-separated `status` list, including `live` and `elaborate`, or
  `any`; `-s open` alone still means only `open`. `cactus threads`'
  `open_count` counts `open`+`live`+`elaborate` the same way, so a thread
  holding only a live plan/review no longer reads as drained.
- The text renderer's verdict history (`_print_questions`) shows each past
  verdict as `label — text` when an answer carries both, not just the label.
- `cactus plan`: `--reset-steps` with no `--step` refuses, exit 1 — the old
  behavior silently deleted every step. The same step number in both
  `--done` and `--undone` refuses, exit 1, rather than letting undone win
  silently. `--done`/`--undone` on a non-plan row refuse with the same
  `{key} is act={q.act!r}, not 'plan'` message `--step` already gives,
  checked before any step-range error. `Store.set_steps` refuses
  empty/whitespace-only step text, `ValueError`.
- `Store.set_steps`, `Store.set_step_done`, and `Store.set_review` all refuse
  a `cleared` row with the same message `Store.answer` uses — pointing at
  `cactus reopen KEY --agent ID` — so a retired plan/review row is frozen for
  steps and the verify block the same way it already was for verdicts.
- Enter on a plan row with no draft opens the input, same as `i`; with a
  draft it records the verdict. Typed text plus enter on a review row
  (`_submit_review`) records a text-only verdict in one keystroke, same as
  plan and data rows. None of the three park text for a second enter.
- A plan step toggle pushes a `kind: "step"` undo entry; `u` reverts it via
  `Store.set_step_done`, not `Store.reopen`. Every undo flashes what it
  undid (`_undo_flash`), never silent.
- The card's pending-text block reads `draft:` on a text-kind row; it is not
  recorded yet, whether typed or restored by undo. `_verdict_repr` renders
  `label — text` when a verdict carries both.
- Footer binding labels are static per `Binding` (Textual never reads a
  description from `check_action`), so `CactusApp._relabel` rewrites the
  row-dependent ones (`y`/`n` to the row's own confirm labels, `1-9` to
  pick/toggle/toggle step/copy chunk, `d` to dismiss/close) in Textual's
  binding map on every `_rebuild_card`, just before `refresh_bindings()`.
  It fails soft to the neutral defaults in `BINDINGS`. `s` (skip) stays
  offered on every answerable row, persistent ones included (q317). A
  `--no-free` row's hint drops `i type` the same way `check_action` hides
  `i`.
- `cactus plan`/`cactus review` take an optional `--agent`, gated in `cli.py`
  (not `Store`), same split as `clear`/`reopen`/`edit`: given and the row is
  owned by someone else, refuse exit 1; omitted, or the row unowned, behave
  as before.
- On a plan row past 9 steps, a digit buffers (~0.5s, `set_timer`) rather
  than firing at once, so "1" then "2" reaches step 12 instead of toggling
  step 1 (q16); a plan with 9 or fewer steps still fires every digit
  instantly. Any non-digit key, row move, or a digit that cannot extend to a
  valid step number (`0` as the first digit, or a two-digit buffer) fires or
  cancels immediately — `_handle_step_digit`/`_resolve_step_buffer`.
- `files` is an additive JSON-list column on `questions`; `cactus ask`/`edit`/
  `review`/`plan` all take `-f/--file` (repeatable), and the CLI resolves each
  path to absolute against cwd before writing, refusing a missing path, a
  directory, or a duplicate after resolution — never the store's job.
  `Store.edit`'s `files` follows `choices`' whole-list-replace semantics
  (`None` keeps, a list replaces, `[]` clears); `review`/`plan` route through
  `Store.set_files`, which refuses a `cleared` row like `set_review`/
  `set_steps`. The TUI's `f`/`F` bind only on a row with files
  (`check_action`); a one-file row runs immediately, a multi-file row arms
  `file_pending` ("view"/"edit") and takes the next digit via
  `action_select_choice` (which `check_action` also lets through while armed,
  even on a row with no choices of its own) — any other key, or a row move,
  disarms it (`on_event`'s pre-dispatch hook, mirroring the plan-step
  buffer). Both actions run the external program under `App.suspend()`,
  falling back on `SuspendNotSupported` (the headless test driver);
  `CACTUS_PAGER`/`CACTUS_EDITOR` override the pager/editor template with
  `{path}` substitution, and tests set them to an inert logging script.
- `o` toggles an inline preview of the focused row's files in the card
  (q387/q393/q394), bound only on a row with files (`check_action`, keybar
  `o preview`). Nothing is stored: `shell.file_preview` asks the file's
  repository at render time — `diff HEAD` when changed, else head of content
  (untracked, unchanged, no repo), capped at 40 lines per file — and git
  failure or a 2s timeout falls back to the head. `preview_open` resets on
  a row move and the block is recomputed only while open; markup stays off.
- `Store.projects()`'s `due_count` is `open + elaborate` (q351) — `live` is
  re-answerable but never blocks anyone, so it stays out of "due"; the
  projects page and the projects pane both rank by it, `due_count DESC,
  last_activity DESC`. `Store.history(project, limit=200)` (q347) is the
  answers view's backing query: `answered`/`cleared` rows that carry at
  least one verdict, newest-verdict-first by the latest answer's own
  timestamp, not the row's `updated_at`.
- `CactusApp.settings_open`/`projects_open`/`answers_open` are three plain
  booleans, not a `view` enum (q354 explicitly vetoed the enum refactor) —
  mutually exclusive by convention, not by type: each panel's own open
  action calls `_close_other_panels` before flipping its own flag, so
  opening one always closes whichever of the other two was open, and each
  of the three `open_*` actions stays reachable via `check_action` no
  matter which of the three is currently open.
- The projects pane (q349/q352, `#projects-pane`) is a due-ranked preview
  beside the rail — every enabled project, one line each, `▸ label  N due`,
  ranked by `due_count` like `projects()` itself, current project marked
  `▸`. Left of `#rail` inside `#body`, so it never shifts the rail's own
  fixed-height rows — it lives in its own column, not stacked above them.
  Read-only, never focused, rebuilt on every `_reload`. Hidden in `bottom`
  orientation (no room beside the rail there) and behind the settings `3`
  toggle (`tui_settings["projects_pane"]`, persisted, default on).
- The answers view (`a`, q347/q353, `#answers-panel`) shows the current
  project's history only — `[`/`]` rotate which project's history it shows,
  over every known project (not just the live ones: a drained project's
  history is exactly what this view is for). `esc` or `a` again returns to
  the inbox. `j`/`k` move the selected line; `enter` toggles an expanded
  block below it (full text, context, every verdict) rather than opening a
  second view. The verdict column is `_verdict_repr` on the latest answer,
  except a `cleared` row always reads `cleared` there regardless of what
  that last answer actually was.
- `p` on the projects page (`P`, q370-q372) pokes the selected project: one
  `poke.poke(webhook=False)` per distinct herdr `pane` on its
  `open`/`live`/`elaborate` rows (`Store.project_panes`), each carrying
  `PROJECT_POKE_MESSAGE`. Herdr only — no webhook, no owner-only fallback;
  `CACTUS_POKE` still overrides. A project with no stamped pane flashes
  `no herdr panes (K rows unstamped)`. `check_action` admits `poke` while
  `projects_open`; the inbox `p` row poke is unchanged.
- Sky config save/recall slots (v6g): nine files beside `sky.toml`,
  `sky-slot-N.toml`, sparse-dumped the same way `sky.toml` itself is. The `T`
  overlay's bare digit `1`-`9` recalls a slot (applies live, rewrites
  `sky.toml`, flashes empty when unset); `S` arms, and the next digit opens
  a name prompt (v6h) rather than saving at once — `enter` saves with the
  typed name (or none), `escape` cancels. A slot's name is a plain
  top-level `name` key in its TOML file (`overlay()` ignores unknown
  top-level keys, so it never affects loading). The overlay's saved-skies
  grid sits at the very top, right under the "tuning" title, one `N name`
  cell per slot (`—` empty, `(unnamed)` filled but nameless) — the ~75 key
  rows below it push the grid off-screen otherwise.
- The garden (the field's landed cactus pile) is a shared, persistent file
  (`garden.py`), `garden.json` beside the database — every TUI on the same
  database reads and writes the same one, and it survives a restart.
  `World` only counts `landed_since_save`; it never touches the file
  itself. A landing saves on the next `_field_tick`; every `SKY_RELOAD_SECONDS`
  poll (the same clock the sky config reload uses) also stats the file and
  reloads it if another process's write is newer, flashing "garden updated".
  `~` hides/shows the field strip (`tui_settings["field"]`, persisted);
  backtick drops a seed while shown, or while hidden flips `pile_only`
  (persisted) to show the pile alone without the sky/birds/seeds. A hidden
  garden still grows: the field timer keeps ticking and only the draw is
  skipped, so an answer's seed still lands and reaches the file. `cactus
  garden` prints the file's path, cell count, and drop count (or "empty");
  `--clear` removes it (`nothing to clear` if it was already gone).
- A falling clump has hidden `charge` (no UI text): +1 and +1 member on each
  clear-sky-to-cloud entry (`in_cloud`'s False->True edge, not per frame
  spent inside one), +1 per distinct bird it shares a terminal cell with.
  Landing explodes `charge` single-member clumps off the landing point;
  those are `bounty=False` so they can never collect and cascade. Cloud
  presence is read off `World._sky_cells`, the glyph grid `render()` cached
  last frame — never a live query against the sky engine.
- `perspective` (v8) is a `SkyConfig` choices lever for the fluid engine
  only: `on` (default) is the v7 projection through `horizon`/`focal`/
  `z_far`; `off` is the v6 look, `Sky.render_cells` handing `downsample` the
  raw grids so each deck's bands draw flat across the sky at their own
  height. Texture and puffs never projected and ignore it.
- The `T` overlay shows only the keys the running engine reads
  (`sky.tuning_visible`/`tuning_fields_for`, v8): far/mid/near grids, shear
  and `perspective` under fluid, the projection levers only while
  `perspective == "on"`; `shear_base` alone under texture; the `cloud_*`
  levers under puffs; tone/haze/glyph thresholds, `fps`, `pile_style`,
  `stick_distance`, `seed_wind`, `sky_engine` always. `edge_*` and `flat_*`
  are never shown — the strokes they governed are gone: the sky draws
  braille only (a single dot on the fringe, the dither inside, the full
  cell at a core), the keys stay so an older sky.toml still loads. `_render_tuning` refilters on every
  redraw and keeps the cursor on the same key when it survives.
- `cloud_style = "bands"` (v8, planetary layers) is the puffs engine's
  fourth style: `lanes * cloud_count` equal lanes down the whole sky, one
  full-width `_Puff` per lane (`lane=(index, y0, h)`), its noise lattice
  fitted to the width so it wraps with no seam, neighbouring lanes flowing
  opposite ways (odd east, even west). A dead band respawns in its own lane;
  a `cloud_count` change re-cuts every lane. Lanes colour by thirds: top far,
  middle mid, bottom near.
- Birds are levers on `SkyConfig` (v8), read off `World.sky.config` like
  `seed_wind`: `birds` picks the depth bands a flock may spawn in (`all`,
  `far`, `mid`, `near`, `far+mid`, `mid+near`, `none`; `World.bird_bands`),
  `bird_rate` the spawns per second, `bird_max` how many flocks fly at once
  (0 grounds them). `FLOCK_SPAWN_P`/`FLOCK_MAX_ALIVE` are only the defaults'
  documentation now. The glyph set per depth stays `field.DEPTH_GLYPHS`.

