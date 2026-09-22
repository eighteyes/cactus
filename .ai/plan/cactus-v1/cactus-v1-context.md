# cactus v1 — context

## Key files

    src/qaui/store.py      schema, KINDS tuple (line 22), SCHEMA (line 25),
                           default_db_path (line 58), _now (line 66)
    src/qaui/cli.py        argparse verbs, scope resolution, AGENT_HELP
    src/qaui/scope.py      cwd -> (project_root, cwd)
    src/qaui/tui.py        human answering surface
    src/qaui/watch.py      human read-only feed
    src/qaui/monitor.py    agent-facing plain-stdout event stream
    pyproject.toml         package name, console script entry point

## Prior art: cassr

`/Users/god/projects/c100` holds cassr, which solves the adjacent problem for the
c100 macro pad. It is the reason the act vocabulary exists rather than being
invented here.

    bin/cassr                    CLI: post, poll, list, answer, review, plan,
                                 step, clear, noop
    c100/core/cassr.py           store: per-agent JSON dict, fcntl flock
    checks/holdmenu.py           hold-menu placement and two-tap gestures
    .ai/input/cassr.md           spec: workflows, verb block, payload schema

cassr slot kinds: ask, steer, seen, run, write, plan, review.
cactus v1 adopts ask, steer, seen, run. `write` maps to the existing
`kind = text` shape rather than becoming an act. `plan` and `review` are
deferred.

cassr keys on agent-pane identity resolved from `HERDR_SESSION` and
`HERDR_PANE_ID`. Its store is `~/.ai/state/cassr.json`, polled read-only by the
c100 daemon.

## Why the axes are separate

`kind` in the existing schema is the answer shape — how a response is collected.
The act is what the agent is asking for. A `run` act uses a `confirm` shape; a
`steer` act may use `choice` or `text`. Collapsing them would force one column to
carry both meanings and would break the existing `--confirm` flag.

## Invariants the migration must not break

Listed in CLAUDE.md and load-bearing:

- `cursor()` carries a row count alongside `max(id)` and `max(updated_at)`.
- `_now()` uses microsecond resolution.
- Keys are `q{rowid}`, written after insert from `lastrowid`.
- `--json` is accepted before and after the verb, via `argparse.SUPPRESS`.
- Question and rail text renders with Textual markup disabled.
- Exit codes: 0 ok, 1 error, 2 `--wait` timeout, 3 no match.
- `reopen` cannot recall an answer an agent already read.

Adding two columns with defaults touches none of these. The `feed` verb reuses
`cursor()` unchanged.

## Verification

No test suite. Throwaway scripts in `.ai/tmp/` drive real code against a scratch
database — Textual apps via `App.run_test()` and a `Pilot`, the CLI via
subprocesses. Point `CACTUS_DB` at a scratch file; the default is the live inbox.

Existing scripts in `.ai/tmp/` reference `QAUI_DB` and the `qaui` module and must
be updated with the rename.
