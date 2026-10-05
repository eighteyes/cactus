# Changelog

## 0.3.0 — 2026-10-04

### Added
- Push delivery: per-agent delivery map, herdr entries, `cactus deliver`.
- `cactus elaborate`, `undo`, `exec`: TUI parity from the shell.
- `ask`/`edit --site URL`; `w` opens it in the browser.
- TUI: pin a project from the projects page (`*`); `m` turns a single-choice row into pick-several.
- Auto-decider in the TUI (`[..]` proposal, `A` accepts); clef-flash backend and `cactus decider`.
- Field: sky on numpy, field in a child process, `T` tuning overlay, clumping seeds, pile age ramp, cloud altitude, key bar order setting, root toggles for sky/birds/cactus.
- Codex mod mode substitute in the frontier hook; `mods/cactus-pane`.
- Docs: DEVELOPERS, DEPLOYMENT, `docs/`, README Mods section.

### Changed
- `get --wait` works on non-blocking rows.
- Stop hook stays silent while the agent has an open row.
- Visit and poke pin herdr to the row's session.
- Garden off by default.
- TUI rotates projects newest arrival first; persistent rows marked revised after their latest verdict.
- A linked git worktree scopes to its main repository.

### Fixed
- Fluid perspective no longer crashes when the wind pans.

## 0.2.0 — 2026-10-01

First tagged release.
