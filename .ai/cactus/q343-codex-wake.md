# q343 — Codex does not wake when its background --once exits. How should Codex rows wake it?

status: answered
act: ask
kind: choice
thread: durability
agent: 61b93eb6-af33-46a9-ae97-9aa508895e5f
cwd: .
asked at: 2026-09-28T05:23:26.788753+00:00

## Context

Evidence (q342): Codex armed 'cactus --monitor --once' as a background
command at 21:51 and ended its turn. At ~21:55 the process was still
alive, so it survived the turn end. You answered at 22:19; the process
exited on the event, but Codex stayed idle and never cleared the row.
Codex has no 'background command exit re-invokes the agent' semantic.

auto-poke: cactus already stamps the herdr pane on every row and the
TUI 'p' key prompts it via 'herdr agent prompt {pane}'. Make answer()
(TUI and CLI) fire that poke automatically when the owner's host cannot
self-wake. Needs a host marker on the row: the Codex hook can stamp
source=codex (store.py already has a 'source' column in flight from
the ACP work). Cost: one poke per answer, a herdr prompt lands in the
Codex conversation as a user turn.

human-poke: zero code, the human presses p after answering; forgets.

poll: Codex blocks in the foreground up to a timeout; the user's turn is
what re-arms it, so an answer during idle still waits for the next turn.

Default if unanswered: auto-poke.

## Options

- auto-poke — on answer, cactus pokes the row's herdr pane (herdr agent prompt) when the owner is a Codex session  (★●)
- human-poke — leave the TUI 'p' key as the wake; CODEX.md says so, no auto
- poll — Codex hook tells it to cactus get --wait in the foreground with a timeout, re-issuing each turn

## Recommendation

auto-poke — high
pane stamp and poke transport already exist; only the trigger is missing

## Answer

we had monitor with codex before, no? i don't like auto-poke, it requires herdr.
answered at: 2026-09-28T05:48:57.214046+00:00
