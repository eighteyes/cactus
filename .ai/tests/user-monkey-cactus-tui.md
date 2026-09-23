# user-monkey: cactus-tui

subject: `cactus --tui` (the human answering surface)
date: 2026-09-22
driver: tmux session `monkey` at 110x34, keys via `tmux send-keys`, screen via `tmux capture-pane -p`

## Setup (repeatable)

Scratch DB only; poke is inert.

    S=<scratch dir>
    bash $S/seed.sh          # builds $S/monkey.db, see below
    tmux new-session -d -s monkey -x 110 -y 34 \
      "cd $S && CACTUS_DB=$S/monkey.db CACTUS_POKE=true cactus --tui; echo EXITED \$?; sleep 600"

seed.sh, run from two cwd's so there are two projects:

    # in $S/projA
    cactus ask "Which auth backend?" -c "oidc: existing IdP" -c "local: bcrypt table" --context "We need login by Friday"   # q1
    cactus ask "Which features to enable?" -c "search" -c "export" -c "dark mode" --multi                                    # q2
    cactus ask "Ship it tonight?" --confirm                                                                                    # q3
    cactus ask "What should the release be called?"                                                                            # q4
    cactus ask "Run the migration" --act run --context "make migrate"                                                          # q5
    cactus ask "Follow-up: which IdP tenant?" -p q1                                                                            # q6
    # in $S/projB
    cactus ask "Delete the old logs? [y/n] <b>bold</b>" --confirm -t cleanup                                                   # q7
    cactus ask "Review the login refactor" --act review                                                                        # q8
    cactus ask "Plan for v2" --act plan                                                                                        # q9
    cactus ask "FYI the build is green" --act seen                                                                             # q10

Blank state: same launch with `CACTUS_DB=$S/empty.db`.

## Walk coverage

1. Open cold: done. First screen, footer, card hints recorded.
2. Obvious path: done. Pick (`1`), multi toggle + `enter`, `y`, text via `i`/`enter`.
3. Toggle test: done. `u` after answer, `u` after clear, multi toggle on/off, `esc` out of typing.
4. Jumping: done. Digits, `]` / `[` project switch.
5. Wrong thing: done. `x`, `9` on a 2-choice row, `enter` on a confirm row, `u` with empty stack, empty `enter` in the text box, keys on an empty inbox.
6. Mix scopes: done. Undo from projB of a projA action; question added by CLI while the TUI was open; draft in one row, then `i` on another.
7. Labels: done. Footer vs card hint vs status bar compared on every row type.

Held up: undo restores rows and walks back through several actions; drafts stay with their row; free text on a confirm row explains itself ("enter submits this text alone, or pick above to send both"); `[y/n] <b>bold</b>` renders literally; a question added from the CLI appears without pressing `r`; `q` exits 0.

## Surprises

### 1. Documented checkout command cannot open the TUI
- What I tried: `PYTHONPATH=src python3 -m cactus --tui` (the "run from the checkout" command in CLAUDE.md)
- What I expected: the TUI opens, or a one-line message says what to install.
- What happened: Python traceback ending `ModuleNotFoundError: No module named 'textual'`, exit 1. Installed `cactus --tui` works.
- Why it surprised me: launch/feedback. The documented command fails with a stack trace instead of an instruction.

### 2. Footer lists the wrong keys for the focused row
- What I tried: launch cold on q1 (a choice row) and read the footer. Answer q1 with `1`, then read the footer. `j` to q6 (text row) after typing on a confirm row, read the footer, press `y`. `j` to q10 (notice row), read the footer.
- What I expected: the footer shows the keys that work on the focused row.
- What happened: on cold launch the footer has no `i FreeText`, although the card says `i free text` and `i` works. After an answer the status bar says `u undo` and the footer has no `u Undo`. On the text row q6 the footer shows `y Yes  n No`, and pressing `y` does nothing. On the notice row the card says `d dismiss` and the footer has no `d`. The footer seems to show the keys for an earlier row.
- Why it surprised me: labeling. The footer disagrees with the card hint and with what the keys do.

### 3. `s Skip` answers the question and removes it
- What I tried: on q5 (`Run the migration`), pressed `s`.
- What I expected: skip means "not now": move to the next row and leave q5 open.
- What happened: q5 left the rail, the project count dropped from 3 to 2 open, and the status bar said `skipped q5 · u undo`. `cactus get q5` shows `status: answered, skipped: true`.
- Why it surprised me: labeling. In a list, "skip" means "pass over"; here it is a final answer sent to the agent.

### 4. An empty text box submits an empty answer
- What I tried: on q9 (plan row), `enter` to type, then `enter` again with nothing typed.
- What I expected: nothing is sent, or a message says the answer is empty.
- What happened: status `answered q9 · u undo`. `cactus get q9` shows an answer with `selected: [], text: null, skipped: false`.
- Why it surprised me: feedback/validation. An accidental double `enter` sends a blank answer that is not marked as skipped.

### 5. A review row never shows the verdict you gave it
- What I tried: on q8 (`review · live`), pressed `y`, then `n`.
- What I expected: the card shows the current verdict (`last: pass`, then `last: fail`).
- What happened: after each key the card is unchanged and the status bar says `answered q8`. The screen cannot show which verdict is recorded. The CLI shows two answers; the latest is `fail`.
- Why it surprised me: feedback. On a row that takes repeated answers, the screen should show the current state.

### 6. `d dismiss` reports "skipped"
- What I tried: on q10 (`seen` notice), pressed `d`.
- What I expected: status says `dismissed q10`.
- What happened: status says `skipped q10 · u undo`.
- Why it surprised me: labeling. The key is called dismiss and the confirmation calls it skip.

### 7. Counts leave out live rows while the rail shows them
- What I tried: `]` to projB after answering q7, with q8/q9 (live) still on the rail.
- What I expected: the header count matches the rows below it, and the status bar counts the project I am looking at.
- What happened: the header says `projB  0 open` above two rows. The status bar says `4 open / 1 project` while projB is on screen. Earlier the header said `projB  2 open` above four rows.
- Why it surprised me: labeling. The number under the project name does not count the rows under it.

### 8. Empty inbox advertises actions with nothing to act on
- What I tried: launched on an empty DB, pressed `j 1 s c u`.
- What I expected: the footer lists only `q Quit` and maybe `r Refresh`.
- What happened: the footer lists `j Down  k Up  s Skip  c Clear  [ PrevProj  ] NextProj  r Refresh  q Quit`. Every key does nothing and shows no message.
- Why it surprised me: labeling. The footer lists keys that cannot do anything here.

### 9. Pressed keys that do nothing give no feedback
- What I tried: `x` on any row; `9` on q7 (2 choices); `enter` on q7 with no draft; `u` twice after one undo.
- What I expected: a short status message (`no choice 9`, `nothing to undo`).
- What happened: no change on screen and no message.
- Why it surprised me: feedback. I cannot tell whether the key failed or the app missed the press.

### 10. Confirm-row hint does not match the option names
- What I tried: read the card on q5 (`run`) and q8 (`review`).
- What I expected: the hint uses the same words as the options.
- What happened: the options say `approve / deny` and `pass / fail`; the hint below says `y/1 yes   n/2 no`.
- Why it surprised me: labeling (minor).

### 11. Window title is the class name
- What I tried: open cold.
- What I expected: `cactus` or `cactus — answering`.
- What happened: the title bar says `CactusApp`. The header also shows `[ ]` with no label; it turns out to be the project-switch keys.
- Why it surprised me: labeling (minor).

### 12. Absolute path takes two lines of every card
- What I tried: open any row at 110 columns.
- What I expected: a short project name, like the rail header (`projA`).
- What happened: the full `/private/tmp/.../projA` path wraps to two lines above the question text.
- Why it surprised me: labeling. The rail shows the short name and the card shows the full path (minor).

## Code-cause mapping (after the walk)

	#	Surprise	Cause (file:line)
	1	checkout launch traceback	src/cactus/cli.py:867 — `from .tui import run_tui` is not guarded; system python has no textual
	2	stale footer	src/cactus/tui.py:482 — `check_action` is correct, but nothing calls `refresh_bindings()` when `focused_key` changes (tui.py:674 `on_list_view_highlighted`, `_advance_after`), so the footer keeps the last focus-change result
	3	skip is terminal	src/cactus/tui.py:905-909 — `action_skip` → `_submit_answer(..., skipped=True)`; label at tui.py:266
	4	empty text submits	src/cactus/tui.py:823-825 — `text=value or None` submits even when `value` is empty
	5	no verdict on card	src/cactus/tui.py:44-137 — `_card_lines` never renders `q.answer` / `answers`
	6	dismiss says skipped	src/cactus/tui.py:616 + 926 — dismiss reuses `skipped=True`; undo label derives from `skipped`
	7	counts exclude live	src/cactus/tui.py:411-412 (header) and 644-647 (status bar) use `open_count` only; rail loads `ACTIONABLE` incl. live
	8	empty-state footer	src/cactus/tui.py:489-495 — `always` set returns True for skip/clear/nav before the `q is None` check
	9	silent no-ops	src/cactus/tui.py:510, 516-520 — `check_action` returns False with no flash; `_confirm`/`action_submit` return silently
	10	yes/no hint	src/cactus/tui.py:35 — `HINTS["confirm"]` fixed text vs labels from `q.choices` at tui.py:109
	11	CactusApp title	src/cactus/tui.py:195 — no `TITLE`; `Header()` falls back to class name
	12	path in card	src/cactus/tui.py:56 — `project_display(q.project)` vs `project_label` used by the rail header (tui.py:414)
