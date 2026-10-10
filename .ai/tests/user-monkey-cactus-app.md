# user-monkey: cactus-app

subject: Cactus.app (mac/ panel), keyboard navigation
date: 2026-10-09
driver: `CACTUS_DB=<scratch> CACTUS_POKE=true CACTUS_RECORDS=0 dist/Cactus.app/Contents/MacOS/cactus-mac &`; keys via `osascript -e 'tell application "System Events" to keystroke "j"'` / `key code N` (125/126 arrows, 36 return, 48 tab, 53 esc), Ctrl-Space via `key code 49 using control down`; screenshot of the panel after each key (`screencapture -x -R1520,1050,800,460`); effect confirmed with `cactus list -s any --json` on the scratch DB.

Seed (agent `monkey`): q1 choice (red/green/blue), q2 multi (cheese/ham/olives), q3 text, q4 `--no-free` choice (yes/no/later), q5 review (`--run "echo hi"`), q6 plan (one/two/three), q7 answered.

Walk coverage: cold open, hints, toggle test (pick/unpick, answer/undo, skip/undo, open/hide), jumping (digits, arrows, j/k, tab), wrong keys, mixed scopes (typing then j/u/s/1), key bar read back, focus after reopen, focus after answering. Skipped: shift-Tab, `f` (no files), hotkey rebinding.

Harness note: a visible panel is not reported as the frontmost app by System Events (kitty/Chrome stay frontmost), and when the panel hides itself (#11) the next keys reach whatever app is behind it. Do not send keys unless `count windows of process "cactus-mac"` is 1.

## Surprises

### 1. Arrow keys do not switch question
- What I tried: panel open on q2, pressed Down (key code 125), Up (126), Up (126). Then `j`.
- What I expected: arrows step through the rows like j/k.
- What happened: three arrow presses, cursor stayed on q2, no flash. `j` moved to q3. (The human reported the same: arrows do nothing.)
- Why it surprised me: labeling and convention. The bar says `j/k move`; nothing says arrows are off, and every list I know moves with arrows.

### 2. Tab never moves rows; outside the field it silently jumps into the text box
- What I tried: on q2 (multi) pressed Tab; then `k`. Later on q3 pressed Tab, typed `z`, pressed Tab again. (Shift-Tab untried.)
- What I expected: Tab = next question (the human wants this too).
- What happened: Tab with the field unfocused put the cursor in the answer field (no label, bar unchanged); `k` was typed into the field. Tab with the field focused left it (draft stayed, no row change). Tab never changed the selected row.
- Why it surprised me: feedback and expectation. A navigation key that flips a hidden mode.

### 3. Esc inside the text field kills the keyboard until Tab
- What I tried: q3 text row. Tab (cursor in field), `z`, Esc, then `j`, `k`, `x`. Same on q6: Enter (opens field), `s` typed, Esc, `k`, `k`. Then Tab, then `k`.
- What I expected: Esc leaves the field and j/k move again (or Esc hides the panel).
- What happened: after Esc the field still shows its text, the panel stays open, and j, k, x do nothing, are not typed, and no flash appears. Tab, then `k` worked again. Reproduced three times.
- Why it surprised me: symmetry and feedback. Entering typing mode by `i`/Enter/Tab works; Esc is the obvious way out and leaves the panel dead. This is "can't switch question".

### 4. Typing mode survives hide and reopen, with a stale draft
- What I tried: on q2 with the field focused, Esc (panel hid), Ctrl-Space to reopen, `j`.
- What I expected: reopening starts clean on the row, keys navigate.
- What happened: panel came back on q2 with the field still focused and the old text in it; `j` was typed into the field instead of moving.
- Why it surprised me: persistence of a mode I never chose to keep.

### 5. Key bar keeps advertising keys that now type letters
- What I tried: press `i` on q3, then `j`, `u`, `s`, `1`.
- What I expected: the bar switches to typing hints (enter submit, esc leave).
- What happened: bar still read `enter submit  i type  s skip  c clear  j/k move  esc hide`; the field showed `jus1`, submitted as the answer text.
- Why it surprised me: labeling. The bar says `s skip`, `u`/`j` navigate; they were text.

### 6. `c` clear is refused on a row the app did not create
- What I tried: q3 selected, pressed `c` (bar says `c clear`).
- What I expected: the row retires; `u` brings it back.
- What happened: red status line `cactus: refusing to clear rows you do not own: cactus:q3 (owned by monkey)`. Row unchanged; `u` then said `nothing to undo`.
- Why it surprised me: labeling. A listed key that cannot work on agent rows, and the TUI's `c` can clear any row.

### 7. Digits do nothing on a plan row though steps are numbered
- What I tried: q6 plan card shows `1) [ ] one 2) [ ] two 3) [ ] three`; pressed `1`, `2`.
- What I expected: step 1 and 2 tick; undo with `u`.
- What happened: nothing on screen, no flash; `cactus list` showed all steps still false. Key bar for the plan lists only `i note  s skip  c clear  j/k move  esc hide`.
- Why it surprised me: labeling. The card shows a numbered list that looks pressable and the key does nothing, silently.

### 8. A picked single choice cannot be unpicked
- What I tried: q4 (no-free), `2`, `2`, `3`, Enter, then `u`.
- What I expected: second `2` clears the pick.
- What happened: `no` stayed marked after the second `2`; `3` replaced it; Enter recorded `later`; `u` reopened the row (that part is fine).
- Why it surprised me: symmetry. A multi toggles on repeat press; a single choice does not.

### 9. Undo after a review pass says "nothing to undo"
- What I tried: q5 review. `2` (marks fail), `z`, `p`, then `u`.
- What I expected: `p` records pass; `u` withdraws it and brings the review back.
- What happened: `p` recorded pass and the row vanished from the rail; the cursor moved to q6; `u` flashed `nothing to undo`; q5 stayed `cleared` in the DB.
- Why it surprised me: symmetry. The one-key action that closes a row has no working one-key reverse.

### 10. On a review row, a highlighted pick is ignored by `p`
- What I tried: q5, `2` (fail highlighted with a dot), then `p`.
- What I expected: either `p` is refused while another pick is highlighted, or enter submits the highlight.
- What happened: pass was recorded, the highlighted fail was dropped.
- Why it surprised me: feedback. The card showed `2) ● fail` as the pending pick.

### 11. The panel hides itself, and then keys reach the app behind it
- What I tried: left the panel idle between steps (after a plan-row digit test), then sent `k`, `2`, `z`, `p`, `u`.
- What I expected: panel stays until Esc or Ctrl-Space.
- What happened: screenshots showed the live kitty TUI, not the panel; the keys went to it. No scratch row changed. I found no live row updated afterwards (list of updated rows since the walk began was empty); `p` and `u` were sent to the live TUI, so whoever owns it should glance at its status bar.
- Why it surprised me: persistence and safety. Observed twice (also at the start, after the first Ctrl-Space). Not reproduced on a timer.

### 12. Wrong keys give no feedback
- What I tried: `z` on q5; `y` on q6; Down/Up on q2.
- What I expected: a flash such as `no such key`.
- What happened: nothing visible.
- Why it surprised me: feedback. The TUI flashes why a key is gated.

### 13. (intermittent) `u` right after submitting a typed answer did nothing once
- What I tried: q3 text, `i`, `jus1`, Enter, then `u` immediately.
- What I expected: the answer is withdrawn.
- What happened: card still showed `verdicts 1. jus1`; DB still answered. After Esc and a reopen, `u` worked. The same sequence on q4 and q2 (choices) worked first time.
- Why it surprised me: symmetry, inconsistent. Not reproduced since; may be tied to #3's dead focus.

### 14. (unexplained) q1 was answered `red` without me sending a digit or Enter
- What I tried: at 12:41 I sent Ctrl-Space (several times, toggling the panel), and one `j` while another app may have had focus.
- What I expected: q1 untouched.
- What happened: q1 `answered` with `["red"]` at 12:41:45 in the scratch DB. Later Ctrl-Space toggles with the panel open and closed changed no row.
- Why it surprised me: feedback. Cannot say what caused it; listed so the fixer can try.

## Working as labeled
- Ctrl-Space toggles; Esc (outside the field) hides; cursor stays on the same row across hide/reopen.
- `j`/`k` move; digits toggle on a multi; Enter submits; `s` skips; `u` undoes an answer or skip.
- After answering, the cursor stays on the answered row (it greys, `u undo c clear` shown).

## Code-cause mapping (after the walk)

| # | Surprise | Cause (file:line) |
|---|---|---|
| 1 | arrows dead | `Views.swift:370-399` `handleKeyPress` switches on `"j"`/`"k"`/return/letters only; no `.upArrow`/`.downArrow` case |
| 2 | Tab flips field focus | no `.tab` case in `handleKeyPress`; the system focus ring moves from the `.focusable()` root (`Views.swift:76`) to the `TextField` (`Views.swift:211-221`) |
| 3 | Esc in field dead | `Views.swift:216-219` sets `fieldFocused = false` only; the root `.focusable()`/`@FocusState isFocused` (`Views.swift:76-78`) is not re-set, so no view has key focus until Tab |
| 4 | typing survives hide | `Panel.swift:55-62` `showPanel` and `hidePanel` never touch the view; `resetChoice` (`Views.swift:~362`) clears `draft`/`fieldFocused` only on row or list change |
| 5 | bar ignores typing | `Views.swift:290-316` `keyBarItems` does not read `typing` (`Views.swift:59`) |
| 6 | `c` refused | `CactusCLI.swift:110-114` runs `cactus clear KEY` with no `--agent`; `cli.cmd_clear` refuses rows owned by someone else (CLAUDE.md "cmd_clear gates on ownership"); the TUI calls `Store.clear` directly |
| 7 | plan digits dead | `Views.swift:401-404` routes digits to `selectChoice`, which needs `question.choices` (`Views.swift:~413`); plan rows have `steps`, and `keyBarItems` omits any step key (`Views.swift:296-311`) |
| 8 | no unpick | `Views.swift:~418-421` single-choice branch sets `selectedChoice = label` with no toggle |
| 9 | undo after pass | pass closes the row, `_load` drops cleared rows, `selectedRow` falls to q6; `submitUndo` (`Views.swift:478-482`) acts on the selected row, which has no answers, and flashes `nothing to undo`; there is no per-session undo stack as in `tui.py` |
| 10 | p overrides pick | `Views.swift:469-476` `submitVerdict` ignores `selectedChoice` |
| 11 | self-hide | `Panel.swift:34-37` `resignKey` calls `hidePanel`; any focus change (including a dead-focus state or another app activating) hides it |
| 12 | silent wrong keys | `Views.swift:405-406` falls through to `.ignored`; `errorMessage` only set by explicit refusals |
| 13 | intermittent u | not mapped; candidate: `Views.swift:368` `if typing { return .ignored }`, stale `fieldFocused` after `submitText` (`Views.swift:452-460`) |
| 14 | q1 answered | not mapped |

## Re-run

date: 2026-10-09, after mac-keys (B4). Same driver and seed (`.ai/tmp/monkey/seed.sh`, scratch DB, binary launched with `CACTUS_DB`). Keys sent only while `count windows of process "cactus-mac"` was 1. The walk stopped partway: the human was at the keyboard (HID idle 0-2 s), and every reopen popped the panel up under them.

Spec change during the work: auto-advance, as in the TUI. A digit on a single-choice or confirm row submits at once (with any draft). Answered rows leave the list (the feed no longer asks for `answered`) and the cursor keeps its index, so the next row slides under it. #8 (unpick) is dropped; `u` undoes a wrong pick.

### Tested

| # | Sequence | Result |
|---|---|---|
| 1 | on q1: Down, Down, Up, `s` | q2 skipped. Pass. |
| 1 | `u` | q2 back to open, cursor on q2. Pass. |
| 2 | Tab, Tab, Shift-Tab, `s` | q3 skipped (q2 → q3 → q4 → q3). Pass. |
| 11 | panel open, human switched to VS Code / Chrome / Grok Bot | panel hid each time; the key gate stopped every later key. Pass. |
| 14 | three cold and warm launches, Down/Down/Up | not reproduced. One early run recorded `red` on q1 from the app itself, under the old pick-then-enter code; a key log on the next two runs showed only arrow events. Likely cause: the panel takes key focus on show, so a `1`/Enter the human types in another app lands in it. |

### Untested: human walk

Seed a fresh scratch DB with `.ai/tmp/monkey/seed.sh`, launch the binary with that `CACTUS_DB`, open with Ctrl-Space. Each sequence starts on the row named.

| # | Start | Keys | Pass when |
|---|---|---|---|
| 3 | q3 | `i` `z` Esc `j` | Esc leaves the field (panel stays), `j` moves to q4 |
| 3 | q3 | `i` Esc Esc | first Esc leaves the field, second hides the panel |
| 2/3 | q3 | `i` `y` Tab Shift-Tab | Tab leaves the field and moves to q4; back on q3 the field still holds `y` |
| 4 | q3 | `i` `x` Esc Esc, Ctrl-Space, `j` | panel reopens with the field unfocused; `j` moves, nothing typed |
| 5 | q3 | `i` | key bar reads `enter submit  esc leave  tab next` |
| 13 | q3 | `i` `jus1` Enter `u` | Enter records `jus1`, the row leaves; `u` brings it back open with the cursor on it |
| 6 | q1 | `c` then `u` | `c` retires q1 (flash `retired q1`), `u` restores it |
| 7 | q6 | `1` `2` `u` | steps 1 and 2 ticked; `u` unticks step 2 only |
| 9 | q5 | `p` then `u` | pass closes q5 (it leaves the list); `u` brings it back `live` with no verdict |
| 10 | q5 | `i` `ok` Enter, then `f` | Enter records text `ok`; `f` records `fail` (with any draft); q5 stays live, cursor stays on it |
| 12 | q6 | `z`, `y`, Left | status line flashes `no key z here`, `no key y here`, `no key that here` |
| auto | q1 | `2` | q1 answered `green`, cursor now on q2 |
| auto | q4 | `i`, then `1` | `i` flashes `no key i here` (no-free row has no field); `1` answers `yes` and advances |
| auto | q2 | `1` `3` Enter | q2 answered `cheese, olives`, cursor on the next row |
| auto | any | the above, then `u` repeatedly | each `u` reverses one action, newest first, then `nothing to undo` |

## Sidebar

B5 walk, 2026-10-09. Scratch DB (`.ai/tmp/sidebar/s.db`: choice, multi, text, review), binary launched with `CACTUS_DB`, keys via System Events, front app read with `lsappinfo front`. Human idle (HIDIdleTime 20s+) throughout.

	step	expected	front after	result
	start, Finder active, panel hidden	—	Finder	ok
	⌃Space	slides in, takes focus	Cactus	ok
	click over to Finder	panel stays visible	Finder	ok
	⌃Space	takes focus, no slide	Cactus	ok
	⌃Space	slides out, Finder back	Finder	ok
	⌃Space, then Esc	hides, Finder back	Finder	ok
	⌃Space, switch to Finder, Esc	panel not key, Esc goes to Finder	Finder	ok

Layout: docked right, full visibleFrame height, 420pt; rail on top (40%), card below, key bar wraps to two lines at its bottom, status bar under it.

Not walked: Reduce Motion (no slide), a second display, the status-menu hide (same `hidePanel` as Esc and ⌃Space).

## Commands

B7 walk, 2026-10-09. Scratch DB, two temp git repos (alpha: 10 rows across every act, stamped pane `w9:p9` session `walk`; beta: one row). Binary launched with `CACTUS_DB`, `CACTUS_POKE='true {agent}'`, `CACTUS_VISIT='true {pane}'`, `CACTUS_VISIT_RAISE=off`, `CACTUS_RECORDS=0`. Human idle 679s before the first key; every key sent only while Cactus was front. Effect read back with `cactus get/list/projects --json`.

	key	row	result	verified
	open	-	beta first (newest arrival), header `[ ] switch`, `6 elsewhere`	screenshot
	]	-	rail switches to alpha	screenshot
	m 1 enter	q1 choice (rec blue)	answered `red, blue`; u reopened	DB
	y	q2 confirm	answered `yes`; u reopened	DB
	1 3 enter	q3 multi	answered `cheese, basil`	DB
	R	q4 review	output streams into the card, result exit 0 + log saved; no verdict	DB + screenshot
	C	q4	clipboard = run command	pbpaste
	O	q4	log opens (Console)	front app
	y / u	q4	pass closes the row; u returns it `live`, pass withdrawn	DB
	1 / u	q5 plan	step 1 done / undone	DB
	x / u	q5	cleared / back `live`	DB
	1	q6 data	clipboard `hello world`, verdict `greeting`	DB + pbpaste
	d / u	q7 notify	dismissed (skipped) / reopened	DB
	o	q8 file	inline diff vs HEAD	screenshot
	e hint enter / u	q8	`elaborate` with the hint / withdrawn, `open`	DB
	D / u	q8	`elaborate` with the decompose text / withdrawn	DB
	p	q8	`poked`	inert CACTUS_POKE only
	v	q8	`visited w9:p9`	inert CACTUS_VISIT only
	y	q9 run	exec ran, `approve` recorded, exit 0	DB
	R esc	q11 review (60s loop)	streams, esc kills it, no orphan shell, panel stays	pgrep + screenshot
	P j I / A	projects page	beta ignored / active	projects --json
	*	beta	pinned; rail `BETA pinned`; `]` flashes `pinned — unpin with * on P`	UserDefaults + screenshot
	p	projects page, beta	`poked 1 pane in beta`	inert CACTUS_POKE only
	P * esc	beta	unpinned, UserDefaults key removed	defaults
	a enter ]	answers	alpha history newest first, enter expands, ] rotates to beta (`No answers`)	screenshot
	s / c / i text enter	beta q1	skipped / cleared / text answer; u undoes each	DB
	f / F / w	q8	notes.txt opens (TextEdit), edit opens (TextEdit), site opens (Chrome)	front app

Not walked: `A` (needs an auto-decider proposal; no decider running), a real herdr pane for `p`/`v`/project poke (the GUI app has no `HERDR_*` or `KITTY_LISTEN_ON`; visit and poke run from the row's pane/session and the login shell's PATH, but the herdr call and the kitty window raise were only exercised through the inert transports — the raise is skipped without `KITTY_LISTEN_ON`), multi-file `f1`/`ff`.

Change from B4: `p`/`f` no longer pass/fail on a review row; they are poke and view-file as in the TUI. Pass/fail is `y`/`n` or `1`/`2`.
