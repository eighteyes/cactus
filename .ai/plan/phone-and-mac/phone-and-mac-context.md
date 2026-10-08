# phone-and-mac context

**Key files**
- src/cactus/www.py: board. `PAGE` inline HTML (53-454), `@media 640px` (121), `_Handler` (457), `_guard` (514-552), SSE `/api/events` (612), `run_www` (725). No token auth, no PWA.
- src/cactus/cli.py:1681-2034: `--www`, `--port` 8642, `--host` 127.0.0.1, `--open`.
- tests/test_www.py: 7 tests (guard, site link, pass closes review).
- mac/Package.swift: Swift 5.9, macOS 14, one executable target, no deps. `swift build` passes.
- mac/Sources/cactus-mac/CactusCLI.swift: finds cactus via `zsh -lc "command -v cactus"`, runs feed/answer/clear with --json.
- mac/Sources/cactus-mac/Views.swift: single-choice + skip + clear only. Model.swift already decodes answers/steps/recommend.

**Decisions**
- Phone reaches the Mac over Tailscale, not a hosted backend: the database stays local; run-row approval executes commands, so the board never faces the public internet.
- Token cookie on non-loopback binds; loopback unchanged so existing tests and habits hold.
- Mac app extends mac/, does not wrap the web board.
- iOS store app parked: no Xcode, no confirmed Apple account, App Review 4.2 risk.
- No full Xcode on this machine: B2 uses swift build + codesign + iconutil (CLT has them); notarytool needs Xcode or CLT 13+, gated behind env.
- Tests: `uv run python -m pytest` (the rtk wrapper eats plain `pytest` output: "No tests collected").
