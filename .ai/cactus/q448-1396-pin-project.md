# q448 — Pin a project in the projects page (P): what does a pin do?

status: answered
act: ask
kind: multi
thread: projects
agent: ba0e449f-5b57-43a2-ab56-38ed74a3b035
cwd: .
asked at: 2026-10-02T07:13:39.029089+00:00

## Context

Today: P page and projects pane rank by due_count then last activity; [ ] rotates over projects with open questions only; --here pins one project per launch.

Storage proposal: tui_settings (per human, persisted, like projects_pane); key on the P page (e.g. space or *), marked with a pin glyph.

Default if unanswered: top.

## Options

- top — pinned projects sort first on the P page and the projects pane, above due ranking
+ your projects never sink below busier ones
- ranking is no longer purely due-first  (★○)
- rotate — [ ] rotation in the inbox visits only pinned projects (when any are pinned)
+ focus on a working set
- unpinned questions hide until you unpin
- stay — a pinned project stays in rotation even when drained (0 due)
+ it never vanishes from [ ]
- empty projects in the rotation

## Recommendation

top — low
the narrowest meaning of pin

## Answer

there's already some flag mechanism to only select one project
answered at: 2026-10-02T07:24:23.347885+00:00
