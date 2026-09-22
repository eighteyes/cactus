# Review — cactus v1

Branch `cactus-v1`. Seven commits, `2633d40` through `1fba1b5`. 23 verification
scripts in `.ai/tmp/`, all passing.

Run everything below against a scratch database. The default is the live inbox.

    export CACTUS_DB=$(mktemp -d)/review.db
    export CACTUS_POKE="echo would-poke {agent}"

## 1. The act vocabulary

    cactus --agent-help | sed -n '/^ACTS/,/^AUTHORING/p'

Six acts, and a table saying which block by default. Whether a row blocks is
the agent's call; the act only supplies the default.

    cactus ask "Which backend?" -c "oidc: existing IdP" -c "local: bcrypt"
    cactus ask "Using staging" --act steer --chosen staging \
      -c "staging: shared tenant" -c "prod: the real one"
    cactus ask "heads up, the lock expired" --act seen
    cactus list -s any

PASS: the steer reads `not blocking`, the seen row too, the ask does not.
FAIL: any row's blocked state disagrees with the table in `--agent-help`.

    cactus ask "no one is coming" --act seen -w

PASS: exits 1 with a message pointing at `--monitor`.
FAIL: it blocks.

## 2. A review row, end to end

    K=$(cactus ask "Does the suite pass?" --act review)
    cactus review $K --look-at "the diff" --run "ls -la" \
      --pass "no surprises" --fail "anything missing" --then "tag it"
    cactus get $K

PASS: status is `live`, choices are pass/fail, the block is attached.
FAIL: status is `open`, or the choices read yes/no.

    cactus answer $K -s pass
    cactus answer $K -s fail
    cactus get $K --json | jq '.[0] | {status, answer, answers}'

PASS: status is still `live` and `answers` holds both verdicts, latest last.
FAIL: the row closed, or only one verdict survived.

## 3. The answering surface

    cactus --tui

Focus the review row.

PASS: the rail line leads with `review` and is marked `live`. The card shows
look at / run / pass / fail / then. The footer offers `C`, `R` and `O`.
FAIL: the row is missing from the rail entirely.

Press `R`.

PASS: output streams into the card, ending with an exit line. The status bar
names the directory it ran in — the ROW's cwd, not yours.
FAIL: it runs somewhere else, or the card does not update until it finishes.

Press `O`, then read the named file.

PASS: the full capture is there, including anything scrolled past in the card.

Press `y` or `1` to record a fail verdict, then `u`.

PASS: undo withdraws the latest verdict and uncovers the previous one. The row
stays `live`.
FAIL: undo empties the row, or closes it.

Now focus the steer row.

PASS: the card says `doing anyway: staging`, and the footer offers NO `R`, `C`
or `d` — that row has no command and is not a notice.
FAIL: a key is offered that the row cannot honour.

Focus a plan row with steps.

    cactus ask "Release" --act plan
    cactus plan qN --step build --step test --step tag

PASS: digits toggle steps, the rail shows `1/3 steps`, and `y`/`n` are absent.
FAIL: a digit past the last step is still offered.

## 4. The projector interface

    cactus feed --pretty | head -40

PASS: one document — a `cursor` block with `max_id`, `max_updated`, `count`
and a per-agent `blocked` rollup, then rows embedding `review`, `steps` and the
full `answers` log. Rows are ordered by rowid.
FAIL: a row needs a second call to render.

    cactus feed --json | jq -c .cursor      # twice, unchanged
    cactus plan qN --done 0
    cactus feed --json | jq -c .cursor      # moved

PASS: a sidecar step tick moves the cursor. A poller that only watched status
would have missed it.

## 5. The event stream

    cactus --monitor --interval 0.3 &
    cactus answer $K -s pass
    cactus plan qN --done 1

PASS: the verdict line reads `verdict`, not `answered`, and carries the act.
The step tick reads `stepped` with a done count.
FAIL: a live-row verdict reads `answered` — an agent would think it closed.

## 6. Poking

    cactus poke $K                       # no agent on the row
    cactus poke --agent some-pane

PASS: the first exits 1 saying the row has no agent; the second runs the
configured transport. With CACTUS_POKE unset the transport is `herdr agent
prompt`, which really does prompt a live agent.
FAIL: it pokes with CACTUS_POKE unset during review.

## 7. Guards worth confirming

    CACTUS_DB="" cactus where          # exits 1, does not touch the live inbox
    cactus answer $SOMETHING_ANSWERED   # exits 3, first verdict survives
    cactus migrate                      # refuses without --yes

PASS: all three refuse. The middle one is the contract c100 renders as a stale
cell rather than an error.

## Still open, deliberately

- The repository directory is still `projects/qaui`. Renaming it from inside a
  session anchored there would pull the floor out from under the process doing
  the renaming, so it is left to a human:

      mv /Users/god/projects/qaui /Users/god/projects/cactus
      cd /Users/god/projects/cactus && uv tool install --editable .

- The live inbox at `~/.local/share/qaui/qaui.db` has already had its answers
  table rebuilt. Adopting it under the new name is still a manual step:

      sqlite3 ~/.local/share/qaui/qaui.db \
        "VACUUM INTO '$HOME/.local/share/cactus/cactus.db'"

- cactus has no equivalent of cassr's stop-hook gate, which blocks an agent's
  turn until it posts a slot. That is forced externalisation and it is a
  different surface with a different owner. Nothing here replaces it.

## What c100 needs, in one line

Poll `cactus feed --json --agent <resolved-id>` by the cursor block, answer
through `cactus answer KEY -s LABEL`, and treat exit 3 as a stale cell. Letter
assignment and placement stay theirs; `word` is what they assign from.
