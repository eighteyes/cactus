# Production Readiness — cactus 0.3.0 — 2026-10-04

Scope: distribution readiness of a local CLI/TUI (no hosted service). Reviewer: Claude + Sean.
Verdict: ready-with-risks — code and tests are sound; release is gated on pushing and a green CI run.

Workload: per-invocation CLI (agents), long-running local surfaces (TUI, `--www`, MCP stdio), one SQLite file per user. No server, so SLOs, alerting, dashboards and an on-call runbook do not apply.

| # | Item | Status | Notes |
|---|------|--------|-------|
| C1 | Config via env, sane defaults | pass | `CACTUS_*` env; boots with no config |
| C2 | No secrets in repo | pass | none tracked; no gitleaks run |
| C3 | Webhook auth stored safely | pass | `poke-webhooks.json` written 0600, temp + `os.replace` |
| R1 | Timeouts on external calls | pass | git 5s, herdr 5-10s, webhooks 5s, decider 3s, open 10s, sqlite 10s, `run` 600s |
| R2 | Retries | accepted-risk | none; a failure returns to the calling agent, which retries at its layer |
| R3 | Concurrent writers | pass | WAL, `busy_timeout`, `BEGIN IMMEDIATE` on key numbering |
| S1 | `--www` CSRF / DNS rebinding | pass | fixed in bc055cc: Host, JSON content type, Origin checks |
| S2 | `--www` auth | accepted-risk | none; loopback by default, a wider `--host` is the user's choice |
| S3 | Dependency scan | pass | `pip-audit` in CI; clean on 2026-10-04 |
| S4 | Local file permissions | gap | only the webhook map is 0600; db, garden, sky, tui.json, mcp.log, decider logs use umask |
| D1 | CI gates | gap | `.github/workflows/ci.yml` committed, never run on GitHub |
| D2 | Version single-sourced | gap | hand-edited in 7 files; Codex `+codex.<ts>` stamped by hand |
| D3 | Rollback | gap | reinstall a tag works until `cactus migrate --yes`; an older cactus cannot open a rebuilt db |
| D4 | Release published | gap | 32 commits ahead (after this one) of `origin/cactus-v1`; no `main`; no `v0.3.0` tag |
| D5 | Plugin manifests consistent | pass | Claude plugin, marketplace, Codex plugin, cactus-pane all 0.3.0 |
| O1 | Bug-report diagnostics | gap | no `--debug`; `cactus --version` and `cactus where` exist, not named in an issue template |
| O2 | Tests | pass | pytest suite green; `plugins/cactus/tests/test-hooks.sh` |
| O3 | cactus-pane tests | gap | `mods/cactus-pane/tests/pane.test.tsx` has no runner wired |
| O4 | Linux | pass | `xdg-open`, `wl-copy`/`xclip`/`xsel`, XDG paths |
| H1 | Tree hygiene | gap | stray `a.txt`, a screenshot in `skills/cactus/`, another session's edits in two hook files |

## Fix order

1. Tree hygiene (H1): delete or commit the strays; land or drop the two hook edits.
2. Push `cactus-v1`, watch CI go green (D1, D4).
3. Tag `v0.3.0`; decide whether `main` should exist (D4).
4. Downgrade note (D3): say in CHANGELOG/DEPLOYMENT that `cactus migrate --yes` is one-way; back up the db first.
5. File permissions (S4): create the data dir 0700.
6. Single-source the version (D2): read `__version__` from package metadata; a script stamps the manifests.
7. Wire cactus-pane tests (O3) and an issue template asking for `cactus --version` and `cactus where` (O1).
