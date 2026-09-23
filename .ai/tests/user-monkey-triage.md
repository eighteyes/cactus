# user-monkey triage

Source: .ai/tests/user-monkey-cactus-cli.md (41 findings). Classes: bug, ux, design, fixed, known.
Totals: 14 bug, 20 ux, 2 design, 2 fixed, 3 known.

## bug — high

	7	--no-free stored, never enforced	store.py allow_free unread
	8	--wait on a non-blocking act inserts the row, then errors	cli.py insert before blocked check
	10	argparse validation exits 2, same as --wait timeout	cli.py parser exit
	13	answer accepts an off-menu label on a choice row	store.py answer() unvalidated
	14	empty CLI answer accepted, locks the row	store.py answer() no empty guard
	17	answering a cleared row resurrects it	store.py answer() no cleared check
	34	keys typed right after i land as hotkeys (unverified)	tui.py input focus

## bug — med

	6	--act seen keeps choices on a text row	cli.py kind forced, choices pass through
	19	--wait timeout drops keys already answered	cli.py early EXIT_TIMEOUT
	25	missing key: three verbs, three exit codes	cli.py get/clear/poke
	26	poke to a nonexistent agent reports success	cli.py poke unvalidated
	27	--db "" falls through to a default	store.py Path() fallback
	28	--db into a missing directory tracebacks	store.py mkdir unguarded
	29	--tui --monitor opens the TUI, no TTY check	cli.py no exclusivity

## ux — med

	18	get text output hides review/plan state	cli.py text renderer
	20	get --answered-only exits 3 silently	cli.py
	32	empty result silent on three verbs	cli.py EXIT_EMPTY no stderr
	33	flash messages never expire	tui.py cleared only on row move
	41	watch header truncates scope, not path	watch.py

## ux — low

	1	whitespace-only question accepted
	2	duplicate choice labels accepted
	3	--multi --confirm both accepted
	4	--confirm with three choices
	5	--act run -c go gives a one-button confirm
	9	--timeout without --wait ignored
	11	error text wrapped in quotes (KeyError str)
	12	--kind undocumented
	15	--skip --dismiss together accepted
	23	review/plan with no flags silent
	30	feed ignores --json
	36	footer binding labelled "1 1"
	37	ctrl-c toast says ctrl+q, footer says q
	39	card and footer name the typing key differently
	40	plan row: y silent, "1 steps"

## design

	31	counts differ across verbs	scope filters per verb
	38	[ with one project jumps to top	TUI rotates projects with open rows only

## fixed

	16	"undo it first" names no verb	8486310 cactus reopen
	24	missing --agent reported as not owner	62c5d27

## known (queued)

	21	plan --step replaces steps, stale done flag	q136 append
	22	second review call wipes fields	review-merge build
	35	TUI undo one level only	multi-undo build
