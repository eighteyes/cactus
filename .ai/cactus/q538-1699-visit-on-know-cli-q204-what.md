# q538 — Visit on know-cli q204: what does the status bar say after v?

status: answered
act: ask
kind: choice
thread: visit
agent: 2b6594a3-c6ce-4144-8ab5-22d68e8a093d
cwd: .
asked at: 2026-10-05T04:37:19.047157+00:00

## Context

Every layer passes: herdr agent focus w2T:pM exits 0 and the server moves its focused workspace to w2T, tab t3. A headless TUI press of v flashes 'visited w2T:pM' and calls the transport with session estate. So the gap is between herdr's server state and your screen, or an old TUI process.

## Files

- /Users/god/projects/cactus/src/cactus/poke.py

## Options

- visited — says 'visited w2T:pM' but the screen stays put
- failed — says 'visit failed: ...' (type the rest)
- nothing — no flash at all
- stale — TUI was started before today; restart and retry

## Answer

says 'visited, but focus doesnt' change
answered at: 2026-10-05T04:43:20.222600+00:00
