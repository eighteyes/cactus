# q515 — Typing box: what should go?

status: answered
act: ask
kind: choice
thread: mod
agent: e76df619-c30d-487c-84c3-de7f8fc03291
cwd: .
asked at: 2026-10-03T08:14:36.509963+00:00

## Context

Today: a wrapped draft box (3+ rows) mirrors what you type, above the
single Input line, so the text shows twice.

The mod API's Input is single-line only and always shows its own text; it
cannot be hidden while it holds the cursor.

Also check: the next wake should arrive as plain rows, no header, no
"This is how Claude Code surfaces..." line.

Default if unanswered: nobox.

## Options

- nobox — drop the wrapped draft box; keep only the one typing line
+ no text shown twice  (★◐)
- editor — replace both with a real multi-line editor (a custom Client
surface module the mod draws itself)
+ true multi-line answers, newlines included
- a sizeable build; Input has no multiline option
- shortline — keep the box, hide the line's echo is impossible: Input always
shows its own text; pick this if you meant something else (type it)

## Recommendation

nobox — med
the duplicate text is what reads as weird

## Answer

editor
answered at: 2026-10-03T08:15:40.529367+00:00
