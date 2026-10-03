# q323 — Where did the poke fail with 'herdr is not on PATH'?

status: answered
act: ask
kind: choice
thread: poke
agent: 83155dd4-270a-444a-bf43-8d9e8a6dfa37
cwd: .
asked at: 2026-09-26T06:00:44.613461+00:00

## Context

herdr resolves to ~/.local/bin/herdr in this shell. poke.py refuses with that
message when shutil.which fails, so the failing process had a stripped PATH.
launchd apps get /usr/bin:/bin:/usr/sbin:/sbin only.

## Options

- mac — the menu-bar app; fix its PATH when it shells out to cactus  (★◐)
- tui-www — TUI or web board started outside a login shell; poke.py falls back to ~/.local/bin and /opt/homebrew/bin
- cli — cactus poke in a terminal; PATH itself is broken there

## Recommendation

mac — med
newest surface, launchd PATH matches the symptom

## Answer

tui-www
answered at: 2026-09-26T06:19:09.727411+00:00
