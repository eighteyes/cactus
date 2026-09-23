# Elaborate: the human asks the agent to rewrite a question

Source: user request 2026-09-23. Forks q206 (mechanism) and q207 (default
instruction) are open on the board; this spec follows the recommended
answers and is revised when they land.

## Behaviour

TUI: `e` on any row that is `open` or `live`. Opens the text input with the
prompt `elaborate:`. Enter with or without text submits. Escape cancels.

Store: the row gains `elaborate` (text, nullable) and `elaborate_at`. Status
moves to `elaborate`. The row stays on the board under a `wants more`
marker and stops accepting answers until the agent rewrites it.

Monitor: emits event `elaborate` with `key`, `hint` (the typed text or
null), and `instruction`:

    hint present   the hint verbatim
    hint absent    "Rewrite the context plainly. No jargon. Say what you
                    tried, what each option costs, what happens if nobody
                    answers."                                    (q207: eli5)

CLI: `cactus elaborate KEY --agent ID [--text ...] [--context ...] [-c ...]`.
Replaces the given fields, keeps the rest, clears `elaborate`, moves status
back to `open` (or `live`). Refuses: a row not in `elaborate` status (exit 1),
another agent's row (exit 1), missing key (exit 3). `--json` echoes the row.

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
