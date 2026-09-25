# q295 — seen -> notify: keep 'seen' as an alias?

status: answered
act: ask
kind: choice
thread: acts
agent: 76295708-dc65-45c3-9bf4-9f8a9edabc89
cwd: .
asked at: 2026-09-25T05:55:08.800909+00:00

## Context

Existing live rows in ~/.local/share/cactus/cactus.db carry act='seen'; either option rewrites them on open (an UPDATE, not a schema change, so no migrate gate). Alias only matters for other agents' skills/docs still saying seen. Default if unanswered: hard.

## Options

- hard — rename everywhere, rewrite existing act='seen' rows to notify on store open, --act seen refused  (★●)
- alias — same rename plus --act seen accepted and mapped to notify for one release

## Recommendation

hard — high
one name, docs all in this repo

## Answer

hard
answered at: 2026-09-25T06:17:31.100566+00:00
