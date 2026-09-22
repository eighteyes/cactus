# cactus

A transitory question/answer interface between coding agents and a human.

Agents add questions to a durable inbox and read the answers back on their own
schedule. The human answers them in a terminal UI, or leaves a live feed running
and watches them arrive.

Questions are scoped by working directory. Every question records the project it
was asked from — the git toplevel, or the directory itself — so an agent sees
only its own mail while the human sees every project at once.

## Install

    uv tool install --editable ~/projects/cactus

Or run it from a checkout:

    PYTHONPATH=src python3 -m cactus --help

## Agent side

Ask, and get a key back immediately:

    cactus ask "Which auth backend?" -c "oidc: existing IdP" -c "local: bcrypt table"
    q7

Read it later, from any session:

    cactus get q7 --json

Block until it is answered, with a deadline:

    cactus ask "Safe to drop the legacy column?" --confirm --wait --timeout 600

Attach a follow-up to an existing question:

    cactus ask "Which IdP?" --parent q7

Other verbs:

    cactus list [-s open|answered|cleared|any] [-t thread] [--all]
    cactus answer q7 -s oidc "use the staging tenant first"
    cactus clear q7 | cactus clear --thread auth | cactus clear --here
    cactus threads | cactus projects | cactus where

`--json` works before or after the verb.

    cactus --agent-help

prints the whole agent-side roadmap: the ask/work/collect arc, what belongs in
`--context`, when `--wait` is worth the block, and the exit codes.

Stream every change as plain lines, for a watcher in an agent loop:

    cactus --monitor

    q7  asked     Which auth backend?  (2 choices)
    q7  answered  [oidc] staging first
    q7  reopened  Which auth backend?
    q9  gone

Events are `asked`, `answered`, `skipped`, `cleared`, `reopened`, `changed`, and
`gone`. Add `--all` to span projects, `--json` for one object per line,
`--replay` to emit the current inbox first, `--interval` to change the poll.

## Human side

    cactus --tui      answer the inbox
    cactus --watch    live read-only feed of questions and answers

Both span every project by default. `--here` scopes them to the current one.

## Question kinds

    choice    one of several labels          -c a -c b
    multi     several of them                -c a -c b --multi
    confirm   yes / no                       --confirm
    text      free entry                     no choices

Free text is accepted alongside a selection unless `--no-free` is passed, so a
question can take a pick, a typed answer, or both.

## Exit codes

    0   success
    1   error
    2   --wait timed out
    3   nothing matched

## Storage

SQLite at `~/.local/share/cactus/cactus.db`, overridable with `CACTUS_DB`. WAL mode, so
the TUI reads while agents write.

`clear` marks a question retired and keeps the transcript. `clear --purge`
deletes it, and its follow-ups cascade.
