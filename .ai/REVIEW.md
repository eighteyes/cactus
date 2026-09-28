# Review: --file on rows, f/F in the TUI

Branch cactus-v1, commit "Rows carry files".

## Setup

    export CACTUS_DB=/tmp/file-review.db CACTUS_POKE=true CACTUS_RECORDS=0
    A=review-$$
    printf 'one\n' > /tmp/one.txt; printf 'two\n' > /tmp/two.txt

## CLI

1. `cactus ask "look at these" -f /tmp/one.txt -f /tmp/two.txt --agent $A`
   prints a key. `cactus get KEY` shows two `file` lines with absolute paths.
2. `cactus ask "x" -f /nope --agent $A` exits 1 with `cactus: no such file: /nope`.
   Same shape for a directory (`not a file`) and a repeated path (`duplicate file`).
3. `cd /tmp && cactus ask "rel" -f one.txt --agent $A` stores `/tmp/one.txt`.
4. `cactus edit KEY --agent $A -f /tmp/two.txt` leaves only two.txt on the row.
   `cactus review KEY -f ...` and `cactus plan KEY -f ...` behave the same.
5. `cactus get KEY --json | jq '.[0].files'` is a list of strings.
6. `cactus --agent-help | grep -- '-f PATH'` finds the option.

## TUI

    cactus --tui

1. On the two-file row the card lists `files   1 /tmp/one.txt` and `2 /tmp/two.txt`;
   the footer shows `f View file` and `F Edit file`.
2. `f` then `1` opens one.txt in your pager; `q` returns to the TUI intact.
3. `F` then `2` opens two.txt in your editor; save and quit; the TUI redraws.
4. `f` then `j` opens nothing and moves the row.
5. `f` then `9` flashes `has no file 9`.
6. On a row with no files the footer omits both keys and `f` flashes `carries no file`.
7. Post a one-file row: `f` opens it with no digit.

## Monitor

`cactus --monitor --agent $A` in a second shell, then `cactus edit KEY --agent $A -f /tmp/one.txt`:
the stream prints nothing (own edit, q334). Run the same edit as a library call
without `agent` (tests/test_monitor.py `run_unfiltered_once`): one `edited` line.

# Once-loop wake-up (q339, 6705861 + this commit)

## Setup

Fresh Claude Code session in a herdr pane. Read the SessionStart hook output.

## Steps

1. The hook's first line names the Bash tool with `run_in_background=true` and
   `--once`; no `Monitor(` anywhere in it.
2. The agent arms it. `ps | grep -- --monitor` shows one process with `--once`.
3. Post a row from the agent, walk away 40+ minutes, answer it in the TUI.
4. The session wakes on its own, reads the row, re-arms, acts.
5. `cactus --agent-help` step 1 shows `--once` as the primary; the old
   foreground stream is listed as the unbounded alternative.
6. `cactus ask` with no waiter armed prints the reminder naming `--once`.

## Fail if

- the hook still prints `Monitor(` or `timeout_ms`
- the session does not wake after the human answers while it was idle
- two `--once` waiters run for the same agent after a wake (recipe says re-arm once)

## Fail if

- a pager or editor leaves the terminal garbled after return
- a relative -f is stored relative
- a digit reaches a choice or plan step while f/F is armed
- the swept-in project switch broke `cactus projects` output
