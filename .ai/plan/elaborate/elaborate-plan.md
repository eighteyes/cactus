# Elaborate: the human asks the agent to rewrite a question

Source: user request 2026-09-23. q207 (default instruction) answered
`both`. q206 was answered with a question ("can we edit the current
question or not?"), answered in q211: no verb edits text/context/choices
today; every option below rewrites the row in place. q211 answered with
"can the verb be edit, not elaborate?": yes, the verb is `cactus edit`.
The mechanism was left unpicked twice, so it proceeds on the default,
`status`, under steer q212 in thread `elaborate`.

## Behaviour

TUI: `e` on any row that is `open` or `live`. Opens the text input with the
prompt `elaborate:`. Enter with or without text submits. Escape cancels.

Store: the row gains `elaborate` (text, nullable) and `elaborate_at`. Status
moves to `elaborate`. The row stays on the board under a `wants more`
marker and stops accepting answers until the agent rewrites it.

Monitor: emits event `elaborate` with `key`, `hint` (the typed text or
null), and `instruction`:

    hint present   the hint verbatim
    hint absent    "Rewrite the context plainly, no jargon, and add the
                    facts that are missing: what you tried, the numbers,
                    the files, what each option costs, what happens if
                    nobody answers. Longer is fine."          (q207: both)

CLI: `cactus edit KEY --agent ID [--text ...] [--context ...] [-c ...]`
(q211: the verb is `edit`, not `elaborate`). Replaces the given fields,
keeps the rest. On a row in `elaborate` status it clears the request and
moves status back to `open` (or `live`). On any other `open` or `live` row
it is a plain in-place edit, so an agent can fix a typo or add facts
unprompted. Refuses: another agent's row (exit 1), a row that is answered
or cleared (exit 1), missing key (exit 3), `-c` that drops a label named
by `--recommend` unless `--recommend` is also given (exit 1). `--json`
echoes the row.

Records: `record.py` writes on `elaborate` request and on the rewrite, both
appended to the row's decision record as a `rewrite` section, so the record
shows the question before and after.

Frontier hook: rows in `elaborate` status list first, above answered, as
`qN elaborate <hint or (eli5)>`.

TUI undo: `u` after `e` calls `Store.unelaborate(key)`: status back, fields
cleared. Refused once the agent has rewritten (row no longer `elaborate`).

## Invariants

- Elaborate never records an answer. `answers` is untouched.
- A rewrite bumps `updated_at` so every poller's cursor moves.
- `wait_for_answer` keeps waiting through `elaborate`; only leaving `open`
  for a terminal status returns.
- `--recommend` survives a rewrite unless `-c` changes the labels; then it is
  cleared and the rewrite refuses `--recommend` pointing at a dead label.

## Ownership

src/cactus (store, cli, tui, monitor, record): cactus-ba's builder.
hooks/frontier.sh, skills/cactus/SKILL.md teach line: this session, after
the verb lands.
