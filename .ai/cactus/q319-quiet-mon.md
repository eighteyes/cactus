# q319 — Dropping the asked echo from --monitor --agent streams

status: open
act: ask
kind: choice
thread: footer
agent: 83155dd4-270a-444a-bf43-8d9e8a6dfa37
cwd: .
asked at: 2026-09-25T23:07:01.246194+00:00

## Context

Every asked on an --agent stream is a row that agent posted itself, so the
line only repeats what it already knows. Same for the cleared echo of its
own clear, but a human clear from the TUI looks identical on the row, so
that one stays. Proceeding with drop; a tap on flag redirects.

## Options

- drop — an --agent stream never emits asked; --replay still lists the inbox first
- flag — keep asked by default, add --no-asked, the hooks pass it

## Rewrite

was: Quiet the cactus monitor in chat?

Today every monitor line is a chat notification, including the asked echo of
each row I post and the 30-minute expiry notice. The stop hook counts any process
carrying --agent ID as a monitor, so a courier's stream satisfies it too.
Default if unanswered: filter.

options were:
- filter — pipe the monitor through jq, drop asked echoes; this session only
- hook — same filter, but baked into session-start.sh and frontier.sh for every session
- courier — park a cactus-courier per batch, one notification when answers land
