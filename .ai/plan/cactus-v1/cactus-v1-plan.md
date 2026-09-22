# cactus v1

Rename qaui to cactus, add a speech-act axis to questions, allow rows that stay
answerable, and expose a JSON read interface that the c100 board consumes as a
second answering surface.

## Decisions

- **Name.** `qaui` becomes `cactus`. Console script `cactus`, alias `cac`.
  `QAUI_DB` becomes `CACTUS_DB`. Default database moves to
  `~/.local/share/cactus/cactus.db`.
- **Act, not kind.** `kind` already names the answer shape (`choice`, `multi`,
  `text`, `confirm`). The speech act is a separate column, `act`, defaulting to
  `ask`. An act constrains which shapes are legal; it does not replace them.
- **Agent identity is a filter, not a key.** A nullable `agent` column holds the
  herdr pane id. Project and cwd remain the scope key; `_scope_where` is
  unchanged. The TUI ignores `agent`. c100 filters on it.
- **Letters stay in c100.** Word-prefix letter assignment, collision renaming,
  and board placement are spatial concerns owned by c100. cactus emits rows with
  stable `q{rowid}` keys and knows nothing about keys or pixels.
- **One writer.** c100 answers by invoking `cactus answer <key> ... --json`.
  Store invariants stay enforced in a single implementation.
- **Answers are an append-only log.** The `UNIQUE` constraint on
  `answers.question_id` is dropped. The current answer is the latest row by
  `created_at`. This is what makes a persistent row possible and what makes the
  monitor stream event-shaped rather than a special case.

## Act vocabulary

    act      persistent   shape                 sidecar   blocking
    ask      no           choice, multi,        -         yes
                          text, confirm
    steer    no           choice, text          -         yes
    run      no           confirm               -         yes
    seen     no           none                  -         no
    review   yes          confirm (pass/fail)   reviews   no
    plan     yes          none                  steps     no

`ask`, `steer`, and `run` block: `wait_for_answer` returns when their status
leaves `open`.

`seen`, `review`, and `plan` never block. An agent learns their disposition by
watching `cactus monitor`, not by waiting.

## Status

    open        waiting for a first answer; blocking acts live here
    live        persistent; answerable repeatedly, never auto-transitions
    answered    terminal; non-persistent rows only
    cleared     retired, transcript kept

A persistent row is created directly as `live` and leaves that state only via
`clear`. `wait_for_answer` ignores `live` rows entirely.

## Sidecars

Rule: an act needing more than a selection gets its own table, cascading on
delete like `answers` already does.

    CREATE TABLE reviews (
        question_id  INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
        look_at      TEXT,
        run_cmd      TEXT,
        pass_when    TEXT,
        fail_when    TEXT,
        then_do      TEXT
    );

    CREATE TABLE steps (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
        idx          INTEGER NOT NULL,
        text         TEXT    NOT NULL,
        done         INTEGER NOT NULL DEFAULT 0,
        UNIQUE(question_id, idx)
    );

`reviews` mirrors the rearmatter verify block: look at, run, pass, fail, then.
It is not a new format, it is that block persisted.

`steps` is a real table rather than a JSON blob because the human surfaces and
the agent both toggle per-step done state, and a blob would make that a
read-modify-write race. An agent ticks a step with `cactus step`; a human ticks
it in the TUI or on the board. Neither is privileged.

Both sidecar writes bump the parent row's `updated_at` so the cursor moves and
pollers see the change.

## Commands on a row

`review` rows carry `run_cmd`; `run` rows carry a command in `text`. A surface
offers three dispositions as three keys, and the human's keypress is the
authorization:

    c    copy the command to the clipboard
    r    run it in the row's cwd; output streams live into the detail card,
         truncated to the last N lines, with a key to open the full capture
    p    push it to the agent's prompt

The row does not declare which. cactus never executes a command without a
keypress, and `r` runs in the row's recorded `cwd`, not the surface's.

## JSON interface

`cactus feed --json` emits the rows a projector needs in one document:

    {
      "cursor": {"max_id": 41, "max_updated": "...", "count": 12},
      "questions": [
        {"key": "q7", "act": "review", "kind": "confirm", "status": "live",
         "text": "...", "choices": [], "project": "/path", "cwd": "/path",
         "agent": "herdr:pane-3", "created_at": "...",
         "review": {"look_at": "...", "run_cmd": "...", "pass_when": "...",
                    "fail_when": "...", "then_do": "..."},
         "steps": [], "answers": [{"selected": ["fail"], "created_at": "..."}]}
      ]
    }

- `--agent <id>` filters to one pane. `--act <name>` filters by act, repeatable.
- `cursor` is the existing change token. A projector compares it against its
  last value before re-reading, the contract `monitor.py` and the TUI use.
- Default scope spans every project, matching the human surfaces. `--here`
  narrows to the current project.

## Flow back

A verdict on a `live` row appends to `answers` and bumps `updated_at`. The
cursor moves, and `cactus monitor` emits:

    {"event":"verdict","key":"q7","act":"review","selected":["fail"],"at":"..."}

No new transport. An agent watching the monitor sees dispositions from the TUI
and the board alike.

## Migration

    ALTER TABLE questions ADD COLUMN act TEXT NOT NULL DEFAULT 'ask';
    ALTER TABLE questions ADD COLUMN agent TEXT;

Existing rows read as `ask` with no agent, which is what they are. No data
rewrite.

Dropping `UNIQUE` on `answers.question_id` requires a table rebuild: create
`answers_new` without the constraint, copy, drop, rename, inside one
transaction. Existing rows each have one answer, so the copy is lossless.

The database path change is not migrated automatically. cactus reads the old
qaui location when the new one is absent and prints a one-line move
instruction.

## Consequences

- `reopen` currently deletes the answer row. With an append log it deletes the
  latest answer row, and on a persistent row that reveals the previous verdict
  rather than returning to unanswered. The TUI's undo changes behavior
  accordingly.
- `status` gains a value every surface must render. Rail blocks stay a fixed 4
  rows regardless.

## Out of scope

- Per-project preset choice sets.
- A human-triggered action menu.
- Any change to letter assignment, board placement, or the hold menu.
- Merging the cassr store. cassr and cactus stay separate; the board may read
  both.

## Resolved

Asked in the inbox as q41-q44 and settled:

- The repository directory is renamed along with the package, sequenced last so
  the editable install does not break mid-flight.
- Plan steps are toggled by the human surfaces and by the agent alike.
- Command output streams live into the card and a key opens the full capture.
- The database-migration question was retired unanswered; the conservative
  behavior above stands — cactus reads the old qaui path, prints a move
  instruction, and never writes to it.
