---
name: cactus
description: Ask the human without stopping work. Use cactus instead of AskUserQuestion whenever a question can be posted now and collected later, whenever several decisions belong to one thread, whenever you are announcing what you will do anyway and only need a veto, whenever a command needs approval, or whenever a verify block or an ordered checklist should stay on the human's board across sessions. Triggers on "cactus", "ask the human", "park this question", "put it on the board", "I need a decision but keep going". Do NOT use for a question whose answer you need before the next keystroke and that has no sensible default; that is AskUserQuestion.
---

# cactus — the durable inbox between you and the human

cactus is a SQLite inbox. You post a row, get a key back, and keep working. The
human answers in `cactus --tui` on their own schedule, from any project, and you
read the answer when you reach the fork. Rows survive the session, so the next
agent in this repository sees them too.

Full syntax lives in the tool, not here. Read it once per session before any
unfamiliar verb:

    cactus --agent-help

## Preflight

    command -v cactus >/dev/null && cactus where

`cactus where` prints the project the row will be filed under. Agent verbs see
only that project; if it is wrong, `cd` before asking.

## Workflow, required

    1  monitor   start `cactus --monitor --json --agent ID` before the first
                 ask; keep it running while any row of yours is open
    2  ask       post every decision the human makes here, not in chat;
                 --recommend when you have a pick, --agent on every row
    3  work      do everything the answer does not block
    4  act       on each event as it lands: answered, reopened, cleared
    5  clear     your own rows, by key, once acted on

`--agent` is required: an unfiltered monitor is refused. Every event is one
JSON line, already filtered to your rows:

    cactus --monitor --json --agent "$AGENT"

Run it with the `Monitor` tool by default. Monitor expires after 30 minutes;
when it does, switch to a background one-shot that exits on the first event
that is not `asked`, then re-arm `Monitor` once the user is active again:

    cactus --monitor --json --agent "$AGENT" --once      # Bash run_in_background

Without `Monitor` at all, the one-shot in the background is the whole loop:
re-run it after each event.

## Blocked by a permission prompt

Do not stop and do not ask in chat. Post the command and keep working:

    cactus run "pnpm exec playwright install" --agent "$AGENT" --why "denied in auto mode"

`--why` becomes the row's context. The human approves or denies it from the
TUI; the `answered` event carries `approve` or `deny`. On approve, re-read
the row: `cactus get KEY --json | jq '.[0].result'`. A non-null `result`
means the TUI already ran it (exit code, a 50-line tail, a log path); act on
that. A null `result` after `approve` means the human approved from the CLI
and you run it yourself. Never run it before `approve`.

## Identity

`cactus ask` refuses a row without `--agent`. The session-start hook prints
the value to pass, resolved through herdr when the session runs in one. Outside
herdr, choose one stable value for the session and use it on every ask and
clear. A bare pane id is not an identity: it outlives the session and the next
occupant inherits your rows.

Clears are scoped by owner. `--thread`, `--here` and `--all` clear only rows
posted under the `--agent` you pass; another agent's key is refused; a row with
no owner clears by explicit key only.

## When cactus, when AskUserQuestion

    AskUserQuestion   the answer gates the next action and no default is safe
    cactus ask        the answer gates a later action; post now, work until then
    cactus steer      no gate: say what you will do, proceed, let a tap redirect
    cactus run        a command needs a yes before it runs
    cactus review     a verify block the human re-checks as the work changes
    cactus plan       an ordered checklist both sides tick
    cactus seen       an FYI the human dismisses; no answer expected

There is no fork act. A fork in the conversation is an `ask` with two or three
`-c` options, one per direction, and it becomes a `steer` with `--chosen` the
moment one direction is the sensible default.

Parking the human on a question you could have answered yourself is the failure
mode. It is measured: `cursor.blocked` in `cactus feed` counts open blocking
rows per agent, for rows posted with `--agent`. Reach for `steer` first, `ask`
when proceeding under any assumption would waste the work, `--wait` only when
the very next step depends on it.

## Batching

Post every question you can see now, under one thread, without `--wait`. Follow
up in the same thread with `-p KEY` when an answer opens a new question. A set
of taps is cheaper for the human than a drip of interrupts across an afternoon.

## Authoring a row

Options are mile posts: two or three, mutually exclusive, each one a thing that
actually happens. Never "other". Split each on the first colon, label then
description.

    cactus ask "Which auth backend?" \
      -c "oidc: existing IdP" \
      -c "local: bcrypt table" \
      --context "Staging tenant is provisioned. Local means owning password reset. Default if unanswered: oidc." \
      -t auth --agent "$AGENT" --recommend oidc --confidence high --why "tenant already exists"

`--context` carries what the human cannot see from the labels: what you tried
and what it cost, the numbers, what breaks under each option, what happens if
nobody answers. Never a restatement of the question, never reassurance.

`--recommend` waits for the human and preselects the pick, so enter alone
submits it. `--chosen` on a steer does not wait: you proceed with it.

`--word SHORT` gives boards a stable label. Set it when a project has many rows
whose text starts the same way.

## Steer: proceed, invite a veto

    cactus ask "Using the staging tenant for the migration dry run" \
      --act steer --chosen staging -t auth --agent "$AGENT" \
      -c "staging: provisioned, disposable" \
      -c "prod-shadow: real data, read only"

Then keep going. Before the irreversible step, re-read the row: a tap on the
other option redirects you.

## Block only when blocked

    cactus ask "Safe to drop the legacy column?" --confirm --agent "$AGENT" --wait --timeout 600

Always pair `--wait` with `--timeout`. Exit 2 is the timeout: proceed on the
default you stated in `--context`, do not treat it as an error. A row the human
clears returns exit 0 with status `cleared`, which is a decline: check the
status, not just the exit code.

## Approve a command

    K=$(cactus run "alembic upgrade head" --agent "$AGENT" -t ship --why "schema is one revision behind")
    cactus get "$K" --wait --timeout 900 --json

`cactus run` posts the command as the row text, `--why` as its context. The
human sees the command and runs it from the TUI with `R` or `y`, which
records `result` on the row. The verdict labels are `approve` and `deny`.
Read `result` before doing anything: non-null means it already ran, null
after `approve` means run it yourself. `review --run` still attaches a
command to any other row when a verify block needs one.

## Persistent rows: review and plan

Both are born `live`, take a verdict every time the work is re-checked, and stay
on the board until cleared. Post them once at the start of a piece of work and
update them as it moves.

    cactus ask "Does the build verify?" --act review -t ship --agent "$AGENT"
    cactus review q8 --look-at "the diff" --run "pytest -q" --pass "0 failures" --fail "any failure" --then "tag the release"

    cactus ask "Release steps" --act plan -t ship --agent "$AGENT"
    cactus plan q9 --step build --step test --step tag
    cactus plan q9 --done 1          # 1-based at the CLI

The latest verdict is `answer`; the full log is `answers`. Re-read rather than
cache: a human can undo a verdict and the row reads `open` again.

## Collect without blocking the session

The monitor you started first is the wake-up. When a thread needs its own
watcher, or the harness has no `Monitor`, two more ways:

    Agent(subagent_type: "cactus-courier", prompt: "agent $AGENT, thread auth, deadline 1800")

The courier parks on the stream and its task notification carries the answers.
Launch it right after posting the batch and keep working. Or run the stream
yourself with Bash `run_in_background`:

    cactus --monitor --json --agent "$AGENT" | jq -c --unbuffered 'select(.thread == "auth" and .event == "answered")' | head -1

Listen for `reopened` and `gone` too: `reopened` means a verdict you already
read is stale; `gone` means the row was purged.

## Read back

    cactus get q7 --json | jq '.[0]'              get returns a list, one row per key
    cactus list -s answered -t auth --json        a thread's verdicts
    cactus feed --json --here                     the whole actionable inbox, one document

An answered row carries `selected[]`, `text`, and `skipped`. `skipped` means the
human saw it and chose not to decide; act on your stated default.

Keys are `qN` within the project. Across projects (`--all`) use the row's
`ref`, `LABEL:qN`, which every verb accepts as a key.

## Decision records

Every answer, undo, verdict and clear rewrites one file per row in the
project, so the decision travels with the code. Commit it with the change it
governed.

    .ai/cactus/qN-SLUG.md    decision record, rewritten on each answer, undo, verdict, clear; commit it

Set `CACTUS_RECORDS=0` in a test harness that runs from a real repository, or
the scratch rows write records into it.

## Retire

    cactus clear q7                                retire, keep the transcript
    cactus clear --thread auth --agent "$AGENT"    retire your rows in a thread
    cactus clear --purge q7                        delete

Clear what you have acted on. A stale open row is a question the human answers
for nothing.

## Exit codes

    0  ok      1  error      2  --wait timed out      3  nothing matched

`--wait` on a row you posted with `--no-block`, or on a `steer`, `seen`,
`review`, or `plan`, is exit 1: nothing will ever arrive.
