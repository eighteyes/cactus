# qaui v1 — context

## Key files

    src/qaui/store.py      SQLite gateway. Schema, Question/Choice/Answer types,
                           ask/answer/clear/purge, list/tree/projects/threads,
                           cursor() change token, wait_for_answer().
    src/qaui/scope.py      cwd -> (project_root, cwd). Git toplevel, else the dir.
    src/qaui/cli.py        argparse surface, all agent verbs, --tui/--watch dispatch.
    src/qaui/tui.py        Textual answering session. Exports run_tui(store, project).
    src/qaui/watch.py      Textual read-only live feed. Exports run_watch(store, project).
    pyproject.toml         hatchling, console script `qaui`, depends on textual.

## Decisions

Separate tool, not a shape-board mode. shape-board is a session owned by its
launching process; qaui is a durable inbox with many writers and a lifetime
longer than any agent turn.

Scope derives from pwd, not from an explicit flag. Agents already run in the
project they are working on, so the correct default needs no argument.

Keys are `q<rowid>`. Short, typeable, and stable. The key is assigned in a second
statement after insert because it derives from the autoincrement id.

Clear is a status change. Purge is the delete. The default preserves transcript.

A cleared question satisfies --wait. Declining to answer must not hang a caller.

Change detection is a polled (max_id, max_updated_at) token rather than a
filesystem watch, because SQLite WAL makes mtime an unreliable signal.

--json is declared on both the top-level parser and every subparser, with
argparse.SUPPRESS as the subparser default so a trailing omission cannot clobber
a leading --json.

## Verification

    QAUI_DB=/tmp/qaui-smoke.db PYTHONPATH=src python3 -m qaui where
    QAUI_DB=/tmp/qaui-smoke.db PYTHONPATH=src python3 -m qaui ask "..." -c a -c b
    QAUI_DB=/tmp/qaui-smoke.db PYTHONPATH=src python3 -m qaui list -s any

The TUI and watch screens are driven with Textual's App.run_test() + pilot, with
a second Store instance writing to the same database mid-test to prove live
refresh.
