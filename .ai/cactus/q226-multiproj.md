# q226 — Multi-project TUI display: what replaces it?

status: answered
act: ask
kind: choice
thread: multiproj
agent: patches-here
cwd: .
asked at: 2026-09-23T20:57:15.854113+00:00

## Context

Today with no --here: a header row (current project + [ ] switch hint), a strip row listing every live project as 'label N', LABEL:qN keys on cards, and [ ] to rotate projects. Just fixed separately (06eb4a2): the strip leaked every project under --here. 'Stinks' doesn't say which part; these are three distinct directions. Say in free text if it's something else (e.g. the LABEL:qN keys). Default if unanswered: no change.

## Options

- here-default — --tui opens on the current project only; --all spans projects  (★○)
- no-strip — drop the project strip row; keep the header and [ ] switching
- flat — one rail across every project; each row tagged with its project, no switching

## Recommendation

here-default — low
removes the multi-project display from the common path without deleting it

## Answer

no-strip
answered at: 2026-09-23T21:40:27.594234+00:00
