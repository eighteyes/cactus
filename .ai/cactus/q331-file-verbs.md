# q331 — --file on which verbs?

status: answered
act: steer
kind: choice
thread: file
agent: 433c9778-c5d1-4246-a98e-904c8b772309
cwd: .
asked at: 2026-09-27T18:45:14.803235+00:00

## Context

Row gains a files JSON-list column, additive like run_tail. edit's -c already
replaces the choice list, so --file there replaces the file list the same way.
review/plan already carry their own flags; adding --file there is a later
patch if you want it. Default if unanswered: ask-edit.

## Options

- ask-edit — --file on ask (repeatable) and edit (replaces the list)  (doing)
- ask-only — ask only, edit later
- all — ask, edit, review, plan all take --file

## Answer

all
answered at: 2026-09-27T18:50:00.938006+00:00
