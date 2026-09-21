# qaui v1 — plan

## Purpose

A transitory question/answer interface between coding agents and a human. Agents
add questions to a durable inbox and read answers back, on their own schedule.
The human answers in a terminal UI, or watches questions arrive live.

## Relationship to shape-board

`shape-board` serves the same broad need through a different object. It is a
session: a caller composes a batch, launches a browser board, blocks until the
human submits, and the board exits. Its live engine (`serve-live.mjs`) holds
standing state and generates follow-up depth ahead of the human, but the channel
still belongs to the process that launched it.

qaui is an inbox rather than a session. It is always available, accepts writes
from any agent in any session at any time, and survives every process that
touches it. An agent can post a question in one turn and read the answer in a
later turn from a different session. That gap is the capability shape-board does
not cover, and it is the reason qaui is a separate tool rather than a mode.

## Scope model

Every question records the working directory it was asked from and the project
root resolved from it — the git toplevel when one exists, otherwise the directory
itself. Scope follows from this:

- Agent-facing commands default to the current project. An agent sees its own
  mail and nothing else.
- `--tui` and `--watch` span every project, grouped, with a key to switch.
- `--here` scopes the human modes to the current project; `--all` widens the
  agent commands.

Named threads remain available as an optional sub-grouping inside a project.

## Threading

Each question is a node. `--parent <key>` attaches a follow-up beneath an
existing question, and a follow-up inherits its parent's thread unless given its
own. Listing renders the tree in parent-before-child order with a depth on each
node. A follow-up whose parent falls outside the current filter is promoted to
depth zero rather than being dropped, so no question becomes unreachable.

## Storage

SQLite at `~/.local/share/qaui/qaui.db`, overridable with `QAUI_DB`. WAL mode,
foreign keys on, a ten-second busy timeout. Two tables: `questions` and
`answers`, one answer per question, enforced by a unique constraint and written
through an upsert so an answer can be revised.

Clearing is a status change, not a delete. The transcript survives so a thread
can be read back after the agent has moved on. `--purge` deletes outright, and
follow-ups cascade with their parent.

## Blocking

`ask --wait` and `get --wait` poll the store until the question leaves `open`,
with an optional `--timeout`. A cleared question satisfies the wait: the human
declining to answer is an outcome, not a hang. Timeout exits 2, so a caller can
distinguish it from an error.

Change detection for the TUI and watch feed rides on `Store.cursor()`, which
returns the maximum question id paired with the maximum `updated_at`. Both
screens poll that token and only re-read rows when it moves.

## Surfaces

    mode     command                                  blocks
    agent    qaui ask "..." -c a -c b [--wait]        only with --wait
    agent    qaui get q7 [--wait] [--json]            only with --wait
    agent    qaui list [-s open|answered|any]         no
    agent    qaui clear q7 | --thread X | --here      no
    agent    qaui answer q7 -s label "free text"      no
    agent    qaui threads | projects | where          no
    human    qaui --tui                               answering session
    human    qaui --watch                             live read-only feed

## Question kinds

`choice` (one of), `multi` (several of), `confirm` (yes/no), `text` (free entry).
The kind is inferred from the flags given and can be overridden with `--kind`.
Free text is accepted alongside a selection unless `--no-free` is passed, which
covers the "multiple choice and/or input" requirement in a single field pair.

## Out of scope for v1

- Generated follow-up depth. Agents author their own follow-ups.
- Any network surface. The database file is the only shared medium.
- Notification beyond the watch feed.

## Grade

B. The data model and scope rule are settled and the blocking contract is
explicit. The residual risk is in the two Textual screens, where live refresh
must not disturb focus or in-progress text entry; that is a behaviour only a
driven test can confirm.
