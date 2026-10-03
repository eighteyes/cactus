# q327 — Dig into the session-start identity mismatch?

status: answered
act: ask
kind: choice
thread: poke
agent: 83155dd4-270a-444a-bf43-8d9e8a6dfa37
cwd: .
asked at: 2026-09-26T06:39:17.031901+00:00

## Context

Every row this session posts is owned by 83155dd4-... (from the SessionStart
hook). herdr agent get w3B:p3 reports ec6f3172-... and identity.sh's own jq
yields ec6f3172 when run now. Poke no longer cares (it targets the pane),
but rehome after /clear and ownership gates key on this value. Likely herdr
detection lag at hook time or a stale claude_session_id token. Default if
unanswered: park.

## Options

- dig — find why session-start resolved 83155dd4 while herdr now reports ec6f3172 for this pane, and fix rehome/ownership
- park — note it in .ai/TODO.md, move on  (★◐)

## Recommendation

park — med
not blocking now; needs a repro across /clear

## Answer

dig
answered at: 2026-09-26T06:52:08.806225+00:00
