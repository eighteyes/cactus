# phone-and-mac

Objective (human, 2026-10-07): "two projects started, mobile-friendly website > app in app store, and mac app". Decisions delegated to lead.

**Product:** the cactus answering board. Phone and Mac become answering surfaces over the same local database.

**Project A — phone.** Website first, App Store app second.

A1 web-remote: reach `cactus --www` from a phone over Tailscale.
- `--host tailscale` resolves the Mac's tailnet IPv4 (`tailscale ip -4`) and binds it. Any other non-loopback host still works as today.
- Token auth whenever the bind is not loopback. Token: 32 random bytes urlsafe, stored `www-token` beside the database (0600), created on first non-loopback start.
- Startup prints the login URL `http://HOST:PORT/login?t=TOKEN` once to stdout.
- `/login?t=` sets cookie `cactus_token` (HttpOnly, SameSite=Strict, Path=/, Max-Age 1 year) and redirects to `/`. Constant-time compare.
- Every other route (GET and POST, SSE included) requires the cookie on a non-loopback bind: 401 plain text otherwise. Loopback bind: unchanged, no token.
- `_guard`'s Host/Origin/content-type rules stay as they are and run first.
- `cactus www-token [--rotate]` prints the token path and login URL hint; `--rotate` replaces it (old cookies die).
- Why: approving a `run` row makes an agent execute a command. A phone is not loopback, so the board needs a credential, and Tailscale keeps it off the public internet.

A2 web-mobile: the board works one-handed on a phone and installs to the home screen.
- Under 640px: one view at a time. Rail is a full-screen list; tapping a row opens its card full-screen with a back control. Desktop layout unchanged.
- Tap targets >= 44px, `env(safe-area-inset-*)` padding, no horizontal scroll at 375px, inputs at 16px (no iOS zoom).
- PWA: `/manifest.webmanifest` (name cactus, display standalone, theme/background colours from the page tokens, icons 192/512 + maskable), `apple-touch-icon` 180, `apple-mobile-web-app-capable`. Icons generated once from `assets/` into `src/cactus/www_static/`, committed as PNGs.
- `/sw.js`: caches the page shell only; never caches `/api/*`. Offline shows a one-line "board offline" state.
- Static files served from `src/cactus/www_static/` (package data in pyproject) under the existing guard.

A3 ios-app: **parked.** Gates: full Xcode installed (only Command Line Tools today) and an Apple Developer account. Watch point: App Review 4.2 rejects bare web wrappers; the app needs a native reason to exist (push on new row via APNs is the candidate). Re-plan when the gates clear.

**Project B — Mac.** Build on mac/ (SwiftPM menu-bar app over the cactus CLI). No rewrite.

B1 mac-parity: answer every row the board can.
- Multi-choice: digits toggle, enter submits all toggled (`answer KEY -s A -s B`).
- Free text: a text field on rows that allow it; enter submits; `--no-free` rows hide it.
- Recommend preselected, as in the TUI.
- Review/plan rows: show verdict history and plan steps; pass/fail on review; text verdict on plan.
- Reopen on answered rows.
- Out: run-row approve/exec, elaborate, poke, files, site.

B2 mac-package: an installable app.
- `scripts/build-mac-app.sh`: `swift build -c release`, assemble `dist/Cactus.app` (Info.plist with `LSUIElement`, bundle id `ai.cactus.mac`, version from pyproject), icon `.icns` from `assets/`, ad-hoc `codesign -s -`, zip to `dist/Cactus-<version>.zip`.
- If `CACTUS_SIGN_ID` is set: Developer ID sign with hardened runtime; if `CACTUS_NOTARY_PROFILE` is set too: `xcrun notarytool submit --wait` and `stapler staple`. Without them: ad-hoc only, and the script says so.
- DEPLOYMENT.md: one section, the build command and the two env vars.

**Order:** A1 and A2 run in parallel in worktrees (both touch www.py, different regions), merged by lead. B1 and B2 run in parallel in the shared checkout (disjoint files).

**Done:** each job a commit with a passing check, verified by lead; a cactus review row per project for the human.

**B3 mac-design** (human, 2026-10-09: "put it on ctrl-space ... basic app design, make it match the tui at least")
- Default hotkey ⌃Space (kVK_Space + controlKey); the `hotkeyKeyCode`/`hotkeyModifiers` defaults override still wins. macOS input-source shortcuts (60/61) are off on this Mac, so ⌃Space is free here; the README line notes the conflict for other Macs.
- Match the TUI: same layout (rail of rows left, card right, key bar docked at the card's bottom), same colours (lifted from tui.py `CSS`, line 699 on), monospace type, rail rows a fixed block height with the active row marked the way the TUI marks it, card titled like the TUI's border title, key bar listing the keys valid for the focused row.
- Reference first: render the TUI headless (Textual `run_test` + `save_screenshot`) against a scratch DB seeded with one choice, multi, text, review and plan row; save SVGs to .ai/tmp/mac-design/. Build the SwiftUI to match them.
- Out: the sky/garden field, settings, projects page, answers view.

**B4 mac-keys** (human, 2026-10-09: arrows don't switch questions; "wire tab for next question")
- Next/previous question: ↓/↑, j/k, Tab/⇧Tab. Tab works from inside the text field too: leaves it, keeps the draft, moves on.
- Rest of the job comes from .ai/tests/user-monkey-cactus-app.md.
- Fix every firm surprise in .ai/tests/user-monkey-cactus-app.md (fb7ac72), lead decisions:
  - #1/#2 movement as above; ⇧Tab previous.
  - #3 Esc in the text field returns key focus to the panel (still visible); a second Esc hides.
  - #4 hide drops typing mode; drafts stay per row.
  - #5 key bar while typing shows only the field's keys (enter submit, esc leave, tab next).
  - #6 a human clear needs a human verb: new `cactus retire KEY...` in cli.py, no `--agent`, no ownership gate, `Store.clear(record=True)` like the TUI's `c`; exits 3 on a missing key. `cactus clear` stays the agent verb. App's `c` calls `retire`.
  - #7 digits toggle plan steps (`cactus plan KEY --done N` / `--undone N`, no --agent).
  - #8 the same digit again unpicks a single choice.
  - #9 a per-session undo stack like the TUI's: answer, skip, retire, step toggle; `u` pops it, whatever row is selected. Undoing a retire: `cactus retire --undo KEY` (Store.reopen, withdraw_pass on a pass-closed row).
  - #10 `p`/`f` on a review row, and enter, submit the highlighted pick with any typed text.
  - #11 hide only when another app becomes active (NSApplication didResignActive), not on window resignKey.
  - #12 an unbound key flashes `no key X here` in the status line.
  - #13/#14 try to reproduce; fix if found, else leave as notes.
  - Human, 2026-10-09: "auto advance on select". Match the TUI (tui.py:3572 action_select_choice, 3883 _advance_after): a digit on a single-choice or confirm row submits at once (with any typed draft) and the cursor moves to the next open row at the same index; answered rows leave the list. Multi rows keep toggle + enter, and enter-submit advances the same way. This replaces #8 (unpick): `u` undoes a wrong pick.
