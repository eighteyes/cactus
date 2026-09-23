# user-monkey: cactus (CLI + TUI edge cases)

subject: `cactus` console script (editable install of this checkout)
date: 2026-09-22
driver: CLI via bash subprocesses against a scratch db; TUI and watch via tmux `send-keys` / `capture-pane` at 110x34 then 170x34
env: `CACTUS_DB=<scratch>/monkey.db CACTUS_POKE=true CACTUS_RECORDS=0`
scope: second pass. The first pass (user-monkey-cactus-tui.md) covered the happy path in the TUI; this pass drives every verb with wrong, empty, duplicate and contradictory input. Nothing from the first pass is repeated here.

Replay: `bash <scratch>/walk1.sh`, `walk2.sh`, `walk3.sh` in order on a fresh db reproduce every CLI entry in key order (q-numbers below assume that order).

## Surprises — ask

### 1. Whitespace-only question accepted
- What I tried: `cactus ask "" --agent A` then `cactus ask "   " --agent A`
- What I expected: both refused the same way.
- What happened: the empty one says `refusing to ask an empty question`; the spaces one creates q2, which `list` renders as a blank line.
- Why it surprised me: feedback — the guard names the case but does not cover it.

### 2. Duplicate choice labels accepted
- What I tried: `cactus ask "dup" --agent A -c yes -c yes`
- What I expected: refusal, or a de-dupe.
- What happened: q3 created with `choices: yes | yes`. In the TUI both `1` and `2` record `yes`.
- Why it surprised me: labeling — two buttons with one name.

### 3. `--multi --confirm` both accepted
- What I tried: `cactus ask "x" --agent A -c a -c b --multi --confirm`
- What I expected: an argparse conflict like `--blocked/--no-block` gives.
- What happened: q6 created, kind `confirm`, no warning. `answer q6 -s a -s b` then records two picks on a confirm row.
- Why it surprised me: feedback — contradictory shape flags silently resolved.

### 4. `--confirm` with three choices
- What I tried: `cactus ask "x" --agent A -c a -c b -c c --confirm`
- What I expected: refusal; help says confirm is yes/no.
- What happened: q7 created. TUI later shows `y`/`n` for the first two and `3` for the third.
- Why it surprised me: labeling — confirm no longer means confirm.

### 5. `--act run -c go` makes a one-button confirm
- What I tried: `cactus ask "run" --agent A --act run -c go`
- What I expected: either approve/deny is forced, or the custom labels replace both.
- What happened: q10 has one choice `go` and no deny. Without `-c` the row gets `approve | deny`.
- Why it surprised me: symmetry — a run row you cannot deny.

### 6. `--act seen` keeps choices on a text row
- What I tried: `cactus ask "seen" --agent A --act seen -c a -c b`
- What I expected: refusal (ACTS table says seen is text) or the choices dropped.
- What happened: q11 is kind `text` but carries both choices; `list` prints them.
- Why it surprised me: labeling — a text row advertising buttons.

### 7. `--no-free` does nothing at the CLI
- What I tried: `cactus ask "t" --agent A --no-free` (q17); `cactus ask "c" --agent A --no-free -c a -c b` (q18); then `cactus answer q17 "text"` and `cactus answer q18 "free text"`
- What I expected: q17 refused at ask (a text question that forbids text is unanswerable); q18 refuses free text at answer.
- What happened: all four succeed. q17 and q18 are answered with free text.
- Why it surprised me: feedback — the flag is stored and never enforced.

### 8. `--wait` on a non-blocking act creates the row, then errors
- What I tried: `cactus ask "x" --agent A --act seen --wait --timeout 1`
- What I expected: refused before anything is written, or the wait honored.
- What happened: `q19 was posted with blocked=false; it is created, watch --monitor` and exit 1.
- Why it surprised me: feedback — exit 1 with a side effect the caller has to clean up.

### 9. `--timeout` without `--wait` is ignored
- What I tried: `cactus ask "x" --agent A --timeout 5`
- What I expected: a complaint, or an implied wait.
- What happened: q21 created immediately, no message.
- Why it surprised me: feedback — a flag that does nothing.

### 10. Validation exit codes collide with the documented contract
- What I tried: `--confidence medium`, `--act frobnicate`, `--blocked --no-block`
- What I expected: exit 1, like every other cactus validation error.
- What happened: exit 2 with argparse usage. `--agent-help` says `2 --wait timeout`.
- Why it surprised me: labeling — a script cannot tell a typo from a timeout.

### 11. Error text wrapped in quotes
- What I tried: `cactus ask "x" --agent A -p q9999`; `cactus answer q9999 x`
- What I expected: `cactus: no such question: q9999`, as `get` prints.
- What happened: `cactus: 'no such question: q9999'`.
- Why it surprised me: labeling — same error, two spellings.

### 12. `--kind` exists but is undocumented
- What I tried: read `cactus ask -h`
- What I expected: every flag in the usage line explained below it.
- What happened: `[--kind {choice,multi,text,confirm}]` is in the usage line and nowhere in the option list or `--agent-help`.
- Why it surprised me: labeling.

## Surprises — answer / get

### 13. Off-menu label accepted on a choice row
- What I tried: `cactus answer q1 -s maybe` on a row whose choices are `yes | no`
- What I expected: refusal naming the valid labels, as `--recommend zzz` does at ask.
- What happened: `q1 answered -> maybe`, exit 0, and the row is now locked (`already answered with maybe`).
- Why it surprised me: symmetry — ask validates labels, answer does not.

### 14. Empty answer accepted and locks the row
- What I tried: `cactus answer q9` (no text, no `-s`, no `--skip`)
- What I expected: refusal, like the TUI's empty-multi guard.
- What happened: `-> (empty)`, exit 0; then `answer q9 -s approve` is refused as already answered.
- Why it surprised me: feedback — a no-op keystroke consumed a run approval.

### 15. `--skip --dismiss` together accepted
- What I tried: `cactus answer q5 --skip --dismiss`
- What I expected: mutual exclusion, or one flag.
- What happened: `-> (skipped)`.
- Why it surprised me: minor; consistency with the `--blocked/--no-block` exclusion.

### 16. "undo it first" points at a verb that does not exist
- What I tried: `cactus answer q1 -s no` (already answered) then `cactus undo q1`, `cactus reopen q3`, `cactus answer q3 --undo`
- What I expected: the error to name a command I can run.
- What happened: `undo it first if that verdict should change`, then all three attempts are `invalid choice` / `unrecognized arguments`. Undo exists only as `u` in the TUI.
- Why it surprised me: labeling — instruction with no CLI path.

### 17. Answering a cleared row resurrects it
- What I tried: `cactus clear q2 --agent A` then `cactus answer q2 "late"`
- What I expected: refusal; the row was retired.
- What happened: `q2 answered -> late`, exit 0. Status flips cleared → answered.
- Why it surprised me: persistence — clear is not final.

### 18. `get` text output hides most of what a row holds
- What I tried: `cactus get q12` after `answer -s pass`, `answer -s fail`, `answer "just a note"`, `review q12 --run "echo hi" --pass ok`; `cactus get q13` after `plan q13 --step one --step two`
- What I expected: to see the verdict history, the verify block, the steps.
- What happened: `q12 live review -> just a note` and `q13 live plan -> plan note`. Only `--json` shows the rest.
- Why it surprised me: feedback — the persistent rows are the ones with the most state, and `get` shows the least.

### 19. `--wait` on several keys drops the ones that were ready
- What I tried: `cactus get q3 q20 --wait --timeout 0.5` (q3 answered, q20 open)
- What I expected: q3 printed, then the timeout for q20.
- What happened: only `timed out waiting for q20`, exit 2. q3's answer never printed.
- Why it surprised me: feedback — one slow key hides a fast one.

### 20. `get --answered-only` on a non-answered key is silent
- What I tried: `cactus get q20 --answered-only`
- What I expected: a line saying it is still open.
- What happened: no output, exit 3.
- Why it surprised me: feedback.

## Surprises — review / plan

### 21. `plan --step` replaces every existing step and inherits a tick
- What I tried: `cactus plan q13 --step one --step two --step three`, `--done 1`, then `cactus plan q13 --step four`
- What I expected: `four` appended as step 4, or a refusal.
- What happened: the list is now `[x] 1 four`. Steps one–three are gone and `four` is born already done.
- Why it surprised me: persistence — the checklist a plan row exists for was destroyed by adding to it, and the done bit moved onto a step nobody ticked.

### 22. A second `review` call wipes the first call's fields
- What I tried: `cactus review q12 --run "echo hi" --pass ok` then `cactus review q12 --pass again`
- What I expected: `pass_when` updated, `run_cmd` kept.
- What happened: `review.run_cmd` is null; the TUI shows no Run key.
- Why it surprised me: persistence — same replace-everything semantics as #21.

### 23. `review KEY` / `plan KEY` with no flags succeed silently
- What I tried: `cactus review q12`; `cactus plan q13`
- What I expected: usage, or the current block/steps printed.
- What happened: review echoes the row line; plan prints nothing at all, exit 0.
- Why it surprised me: feedback.

## Surprises — clear / poke

### 24. Missing `--agent` reported as "you do not own"
- What I tried: `cactus clear q1` (no `--agent`)
- What I expected: `clear needs --agent`, as `ask` says.
- What happened: `refusing to clear rows you do not own: q1 (owned by monkey1)`.
- Why it surprised me: labeling — I never said who I was.

### 25. Nonexistent key: three verbs, three exit codes
- What I tried: `cactus get q9999`, `cactus clear q9999 --agent A`, `cactus poke q9999`
- What I expected: the same "no match" result.
- What happened: `get` exit 1 with an error; `clear` prints `cleared 0` exit 0; `poke` exit 3.
- Why it surprised me: labeling — the exit-code contract says 3 is "no match".

### 26. Poking a nonexistent agent succeeds
- What I tried: `cactus poke --agent nobody`
- What I expected: refusal; no row names that agent.
- What happened: `poked nobody`, exit 0.
- Why it surprised me: feedback.

## Surprises — scope / db / mode flags

### 27. `--db ""` falls through, `CACTUS_DB=""` refuses
- What I tried: `env CACTUS_DB= cactus list`; `cactus --db "" list`
- What I expected: both refused.
- What happened: the env form is refused with a clear message; the flag form silently opens the default db.
- Why it surprised me: symmetry — the invariant exists to stop this exact accident.

### 28. `--db` in a missing directory: traceback
- What I tried: `cactus --db /nonexistent/dir/x.db list`
- What I expected: `cactus: cannot create /nonexistent/dir`.
- What happened: a Python traceback ending in `FileNotFoundError`.
- Why it surprised me: feedback.

### 29. `--tui --monitor` opens the TUI, even with no TTY
- What I tried: `cactus --tui --monitor > file` in a script
- What I expected: a conflict error, or the monitor stream.
- What happened: the TUI started and drew escape codes into the file until killed.
- Why it surprised me: feedback — the mode flags are not exclusive and there is no TTY check.

### 30. `feed` ignores whether `--json` is given
- What I tried: `cactus feed`
- What I expected: text, since `--agent-help` writes `feed --json`.
- What happened: the same JSON document either way.
- Why it surprised me: minor labeling.

### 31. Counts do not reconcile across verbs
- What I tried: `cactus threads` and `cactus projects` on the same db
- What I expected: totals that add up.
- What happened: threads says `6 open 19 total`; projects says `6 open 11 answered`. Live and cleared rows are counted in one and not the other.
- Why it surprised me: labeling.

### 32. Empty result is silent on three verbs
- What I tried: `cactus list` on a fresh db; `cactus list -t nope`; `cactus get q20 --answered-only`
- What I expected: one line saying nothing matched.
- What happened: no output, exit 3.
- Why it surprised me: feedback — a fresh user cannot tell "empty" from "broken".

## Surprises — TUI

### 33. Flash messages never expire
- What I tried: on q12 press `3` (no such choice), then `u`, `?`, `Escape`, `r`
- What I expected: the `q12 has no choice 3` notice to clear on the next key.
- What happened: it stayed in the status line through four unrelated keys.
- Why it surprised me: feedback — stale error looks like a live one.

### 34. Typing straight after `i` lands letters as hotkeys
- What I tried: on the plan row q13, one tmux `send-keys` of `i` `a note from tui` `Enter` (one burst, as a fast typist would)
- What I expected: the note recorded on q13.
- What happened: no note anywhere. The selection jumped to q12 and its latest verdict `fail` had been withdrawn. The `u` in "tui" ran Undo; `n` ran No; Enter then hit q12 with `pick with y/n or 1-2`.
- Why it surprised me: persistence and feedback — the text was lost and an unrelated row was modified, with no notice. Sending `i`, pausing, then typing works (`hello plan` recorded).

### 35. `u Undo` shown but inert past the first level
- What I tried: `s` on q15, `c` on q16, `u` (q16 restored, status now `skipped q15 · u undo`), `u` again
- What I expected: q15 skip withdrawn.
- What happened: nothing; q15 stays answered, status unchanged.
- Why it surprised me: labeling — the status line promises an undo it will not perform.

### 36. Footer binding labelled `1 1`
- What I tried: select the review row q12 or the plan row q13
- What I expected: every footer entry to be `key Action`.
- What happened: the footer ends with `1 1`. Disappears on choice/text rows.
- Why it surprised me: labeling.

### 37. Ctrl-C says ctrl+q, footer says q
- What I tried: `C-c`
- What I expected: quit, or a hint naming the quit key the footer shows.
- What happened: toast `Press ctrl+q to quit the app`; footer says `q Quit`; both `q` and `C-q` exit 0.
- Why it surprised me: labeling.

### 38. `[` with one project moves the selection to the top
- What I tried: on q16 press `[`
- What I expected: nothing, there is one project.
- What happened: selection jumped to q12, the first row.
- Why it surprised me: feedback — a no-op that scrolls.

### 39. Card hint and footer name the typing key differently
- What I tried: select a text row (q19)
- What I expected: one key for entering text.
- What happened: card says `enter to type`, footer says `i FreeText`. Both work.
- Why it surprised me: labeling.

### 40. Silent keys on the plan row
- What I tried: on q13 press `y`, then `Enter` with the box empty
- What I expected: a flash for `y` (it is in the footer on other rows); a clean message for Enter.
- What happened: `y` does nothing; Enter says `1 steps open — i for free text`.
- Why it surprised me: feedback; grammar.

### 41. Watch header truncates the scope, not the path
- What I tried: `cactus --watch` at 150 columns
- What I expected: the scope (`all projects`) readable; the db path shortened.
- What happened: `cactus watch — /private/tmp/…/monkey.db — all p…`.
- Why it surprised me: labeling — the part that changes behaviour is the part cut off.

## Walk coverage

1. Open cold: CLI `--help`, `--agent-help`; TUI, watch, `--tui --here` on an empty project. Done.
2. Obvious path: ask, list, answer, clear per `--agent-help`. Done.
3. Toggle test: answer→undo (no CLI undo, #16); clear→`u` (works once, #35); plan done→undone (works); step add (#21).
4. Jumping: number keys 1–9 in TUI, `[`/`]`, `get` by key. Done (#36, #38).
5. Wrong thing: every verb with a bad/missing/duplicate/contradictory argument. Done (#1–#15, #24–#29).
6. Mix scopes: `--here`, `--all`, `-t`, `-p`, second agent, cleared row re-answered (#17). Done.
7. Labels: footer vs card vs toast vs `--agent-help` (#10, #12, #36, #37, #39). Done.

Skipped: `poke` against a live transport (kept `CACTUS_POKE=true` to avoid interrupting the user's real agents); `migrate` on an old-schema db (none available).

## Code-cause mapping (after the walk)

| # | Surprise | Cause (file:line) |
|---|---|---|
| 1 | Whitespace-only question accepted | cli.py:183 — `if not text`, no `.strip()` on the argv path (stdin path strips) |
| 2 | Duplicate choice labels accepted | store.py:536 — choices stored as given, no dedup |
| 3 | `--multi --confirm` both accepted | cli.py:168 — `args.confirm` tested first, `--multi` never consulted |
| 4 | `--confirm` with three choices | store.py:539 — confirm shape does not bound the choice count |
| 5 | `--act run -c go` one-button confirm | cli.py:177 — `-c` replaces the approve/deny default wholesale |
| 6 | `--act seen` keeps choices | cli.py:174 — kind forced to text, choices passed through |
| 7 | `--no-free` never enforced | store.py:625 — `allow_free` stored; `answer()` never reads it |
| 8 | `--wait` on non-blocking act writes then errors | cli.py:245 — insert precedes the blocked check |
| 9 | `--timeout` without `--wait` ignored | cli.py:253 — timeout only read inside the wait branch |
| 10 | argparse exit 2 collides with timeout | cli.py:787 — argparse default `exit(2)`; EXIT_TIMEOUT is also 2 |
| 11 | Error text in quotes | store.py:643 — `KeyError` raised; `str(KeyError)` adds the quotes |
| 12 | `--kind` undocumented | cli.py:671 — `add_argument('--kind', ...)` with no help text |
| 13 | Off-menu label accepted | store.py:657 — `answer()` never checks `selected` against `q.choices` |
| 14 | Empty answer locks the row | store.py:657 — no "nothing chosen and nothing typed" guard (TUI has one, CLI does not) |
| 15 | `--skip --dismiss` both accepted | cli.py:710 — two `store_true` flags, no exclusive group |
| 16 | "undo it first" names no verb | store.py:654 — message text; no `reopen`/`undo` subparser in cli.py |
| 17 | Answering a cleared row resurrects it | store.py:641 — `answer()` checks only the already-answered case, not `cleared` |
| 18 | `get` text hides review/plan state | cli.py:121 — text renderer prints `answer` only |
| 19 | `--wait` drops ready keys on timeout | cli.py:279 — returns EXIT_TIMEOUT on the first miss before printing the rest |
| 20 | `--answered-only` silent | cli.py:294 — EXIT_EMPTY with no message |
| 21 | `plan --step` replaces steps, carries done bit | store.py:853-858 — `done` keyed by old idx, `DELETE` then re-`INSERT` from the new list |
| 22 | second `review` wipes first | store.py:836 — `ON CONFLICT DO UPDATE` sets every column from `excluded`, absent flags become NULL |
| 23 | `plan KEY` no flags prints nothing | cli.py:378 — output only inside the `--step` branch |
| 24 | missing `--agent` reads as "not owner" | cli.py:441 — ownership check runs with `agent=None`, one message for both cases |
| 25 | nonexistent key, three exit codes | cli.py:288 (get EXIT_ERROR), clear prints count, poke EXIT_EMPTY |
| 26 | poke unknown agent succeeds | cli.py:521 — `poke(agent)` never checks the agent owns a row |
| 27 | `--db ""` falls through | store.py:344 — `Path(path) if path else default_db_path()`; env check lives elsewhere |
| 28 | `--db` bad dir traceback | store.py:345 — `mkdir(parents=True)` unguarded |
| 29 | `--tui --monitor` opens TUI, no TTY check | cli.py:797-849 — mode flags tested in order, no exclusivity, no `isatty()` |
| 30 | `feed` always JSON | cli.py:501 — unconditional `json.dump` |
| 31 | counts disagree | cli.py:536 — `threads` totals every status, `projects` reports open + answered only |
| 32 | empty result silent | cli.py:314 — EXIT_EMPTY without a line on stderr |
| 33 | flash never expires | tui.py:815 — flash cleared only on row move, not on the next key |
| 34 | fast typing after `i` hits hotkeys | tui.py:883 — `inp.focus()` at the end of the handler; keys already queued in the same burst are dispatched against the list bindings ○ |
| 35 | `u` inert past one level | tui.py:1154 — `while undo_stack` pops entries whose `reopen` fails without reporting; label still says `u undo` |
| 36 | footer `1 1` | tui.py:320 — `Binding("1", "select_choice(1)", "1", show=True)` |
| 37 | Ctrl-C toast says ctrl+q | tui.py:304 — Textual default ctrl+c toast; app binds `q` at tui.py:319 |
| 38 | `[` with one project jumps to top | tui.py:849 — project rotate rebuilds the rail and resets selection even with one project |
| 39 | "enter to type" vs "i FreeText" | tui.py:878 — card hint string; footer text comes from the Binding description |
| 40 | plan row `y` silent; "1 steps open" | tui.py:1059 — `y` gated off by `check_action` with no flash; message has no pluralisation |
| 41 | watch header truncates scope | watch.py:101 — `sub_title = f"{db} — {scope}"`, Textual truncates from the right |

> Rows marked ○ are the mapping agent's reading, not confirmed by stepping the code. Lines were read on the working tree at 2026-09-22; another session was editing tui.py, store.py, cli.py and monitor.py concurrently, so numbers may have drifted by the time this is re-run.

## Status

- 8486310 (other session): `cactus reopen KEY --agent ID` exists now; re-run #16 and #35 against it.
- 9ebfe7d (other session): steer double-emit in the monitor, not in this list.
- Open: everything else. Fix order is q135.
