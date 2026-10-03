# q449 — Pin = the --here scope, toggled from the P page

status: answered
act: steer
kind: choice
thread: projects
parent: q448
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-02T07:25:05.634967+00:00

## Context

Your q448 note: the --here flag already scopes the TUI to one project. This makes it a toggle inside the TUI. Building star now unless you tap session.

## Files

- /Users/god/projects/cactus/src/cactus/tui.py

## Options

- star — `*` on a P-page row pins the inbox to that project (as --here does); `*` again unpins; persisted in tui settings; header shows `pinned`; [ ] stops rotating
+ reuses the --here scope path
- a launch with --here still wins over the saved pin  (doing)
- session — same, but the pin lasts only until the TUI quits
+ no surprise scoped inbox on next launch
- re-pin every launch

## Answer

star
answered at: 2026-10-02T07:40:15.196876+00:00
