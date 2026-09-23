# TODO

## herdr identity thread (cactus q104, q114, q115, q124, q125, q126)

- [x] Hook identity source per q115: session token, stdout only. 84cb3a9.
- [x] `--agent` required, owner-gated clears, poke.py comment. cactus-ba, 62c5d27. `--agent ""` refused, ebde2cc.
- [x] Columns workspace, tab, pane, session stamped from HERDR_* at ask; filters on list, feed, monitor; `--word` capped at 16; `--title` capped at 60; AGENT_HELP SCOPE and STAMPS. da2aff8.
- [x] TUI plan row: Enter records typed text as a verdict, never closes; `c` is the only close. q125. 450c8a4.
- [x] Commit trailer dropped per q126: decisions are stored as files in another thread. Removed in the commit after 450c8a4.
- [x] .ai/tmp/test_recommend_plan.py updated to the enter-never-closes plan behaviour; 17/0. q131.
- [ ] TUI sibling of `--here` for workspace. Not decided; raise only if a projector needs it.
- [ ] Re-home path: a row whose agent matches no live identity is offered to the identity now at its stamped session + pane. Needs c100's identity_for_pane or an equivalent; design not decided.

## Findings

- [x] Monitor emitted `answered` twice for q114. Root cause: `Store.answer` ran its INSERT and UPDATE as two autocommits; another row's write in the gap woke the poller mid-flight. Now one transaction. 9ebfe7d. q132.
- [x] Cleared rows restore: `cactus reopen KEY --agent ID`; persistent rows return live with steps and verdicts; TUI `u` reachable after clearing the last row. 8486310. q132.
- [ ] TUI undo walks back one level only; `u` past the latest action does nothing. Deferred from 8486310.
- [ ] `cactus plan KEY --step X` replaces every step and carries a stale done flag onto the new list. user-monkey pass. q133.
- [ ] A second `cactus review KEY --pass X` wipes `--run` set by the first call. user-monkey pass. q133.
- [ ] 39 further surprises in .ai/tests/user-monkey-cactus-cli.md, untriaged. q134.
