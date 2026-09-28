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
- [x] TUI undo: `u` walks the full stack; a stack drained by purged rows now flashes "nothing to undo". d85fa85.
- [x] `plan --step` appends; `--reset-steps` rewrites and clears ticks. q136. dce0507.
- [x] `review` merges fields; `--run ""` clears one. cf6d198.
- [x] user-monkey triage: .ai/tests/user-monkey-triage.md. Fixed high, medium bugs and all ux (q137): 62e8fdc, de3350b, cf01a1d, 774bb52. Monitor undo reads `reopened`: dce0507.
- [x] Rail click focuses instead of answering. a977caa.
- [ ] #34 keys after `i` landing as hotkeys: not reproduced under Pilot; may need real terminal timing.
- [ ] #26 poke to an unknown agent: installed herdr exits 1, so cactus already exits 1; premise did not hold.

## Wake-up durability (q338, q339)

- [x] Monitor's 30-min cap is the killer; probes: background Bash lived 35 min, idle session woke 2.5 h later. Once-loop is the recipe. Hook, skill, agent-help, invariant updated.
- [x] Own `edited` never echoes under `--agent` (q334). 6705861.
- [ ] Channel follow-up: .ai/plan/cactus-channel/. Three probes before code.
- [ ] `--once` exit-to-re-arm gap: a `--since CURSOR` on `--monitor` would close it. Only if the gap bites.
- [ ] Own `cleared` via CLI still echoes; needs a `last_change` stamp to tell it from a TUI `c`.
- [ ] `cactus edit` has no `--recommend`; `-c` drops the old one and nothing can set a new one.
- [ ] Codex plugin hook (plugins/cactus/hooks/session-start.sh) still says Monitor; Codex wake-up mechanics unverified.
- [x] q340: keep the unbounded --monitor stream as a CLI mode; docs-only removal. 3b4abac.
- [ ] BUG record collision: per-project keys (q166) reuse qN numbers that old global-key rows already used, and record.py picks up the existing `qN-*.md`, so q340 (mon-scope) overwrote q340-grok-wake.md from fb8ca4b. Records need a key that cannot repeat: the row id, or project-scoped numbering that starts above the old global max.
