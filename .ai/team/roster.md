# team roster

Spec: .ai/plan/phone-and-mac/phone-and-mac-plan.md (read your job's section first; context in phone-and-mac-context.md)
Repo: /Users/god/projects/cactus, branch `cactus-v1`. web tab: worktree per help (.worktrees/<name>, branch <name>). mac tab: shared checkout.

**Message anyone:** `herdr agent prompt <name> "<you>: <text>"`
**Lead:** `lead-cactus` (exact agent name). Ping it when done, blocked, or the spec is unclear.

**Rules**
1. Edit only the files your row lists. Need a change elsewhere → message the owner.
2. Commit only your paths: `git add <paths> && git commit -m "<you>: <what>" -- <paths>`. End the message with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
3. Never push. Never touch `.ai/plan/` or `.ai/team/`.
4. Done = a commit that passes your check. Ping lead with the hash.
5. Run only the commands your row names. No background servers, subagents, browsers or `git pull` unless your row says so.
6. Never use cactus. Questions go to lead.
7. Tests: always `uv run python -m pytest ...` (plain `pytest` output is eaten by a wrapper). CACTUS_DB/CACTUS_POKE come from tests/conftest.py fixtures; never run against the live inbox.
8. Every new code file starts with a comment block: name, one-line description, responsibilities.

**Roster**

web
- web-remote  A1  src/cactus/www.py (`_Handler` routes, `_guard`, `run_www`, new token helpers; not `PAGE`), src/cactus/cli.py (`--www` flags, new `www-token` verb), tests/test_www.py, README.md (one line), CLAUDE.md (one invariant bullet). Check: `uv run python -m pytest tests/test_www.py tests/test_cli.py -q`. When done ping: lead-cactus.
- web-mobile  A2  src/cactus/www.py (`PAGE` string, plus routes for manifest/sw/static files only), src/cactus/www_static/**, scripts/make-icons.py (`uv run --with pillow`, draws a saguaro icon into assets/icon-1024.png and www_static PNGs), assets/icon-1024.png, tests/test_www_mobile.py. Check: `uv run python -m pytest tests/test_www.py tests/test_www_mobile.py -q`. When done ping: lead-cactus.

mac
- mac-parity  B1  mac/Sources/cactus-mac/*.swift. Check: `cd mac && swift build`, plus run the app against a scratch DB (`CACTUS_DB=$(mktemp -d)/s.db`) seeded with one multi, one text, one review, one plan row; report what you saw. When done ping: lead-cactus.
- mac-package  B2  scripts/build-mac-app.sh, mac/Resources/** (Info.plist template), DEPLOYMENT.md (one section). Uses assets/icon-1024.png when present, else builds without an icon and says so. Do not edit mac/Sources. Check: `bash scripts/build-mac-app.sh && codesign -v dist/Cactus.app && plutil -lint dist/Cactus.app/Contents/Info.plist`. When done ping: lead-cactus.

mac (round 2)
- mac-design  B3  mac/Sources/cactus-mac/*.swift, README.md (one line on the hotkey), .ai/tmp/mac-design/** (reference SVGs, scratch). Check: `cd mac && swift build && bash ../scripts/build-mac-app.sh`, then a screenshot of the panel (`screencapture -l <windowid>` or `screencapture -R`) saved to .ai/tmp/mac-design/after.png beside the TUI SVG. When done ping: lead-cactus.
- mac-monkey  user-monkey walk  .ai/tests/user-monkey-cactus-app.md (commit), .ai/tmp/monkey/** (scratch, never commit). Brief: .ai/team/msg-mac-monkey.txt. Check: the file has surprises + cause table. When done ping: lead-cactus.
- mac-keys  B4  mac/Sources/cactus-mac/*.swift, src/cactus/cli.py (new `retire` verb only), tests/test_cli.py (retire tests), CLAUDE.md (one invariant bullet for retire), README.md (key list line). Brief: plan.md section B4 + .ai/tests/user-monkey-cactus-app.md. Check: `uv run python -m pytest tests/test_cli.py -q`, `cd mac && swift build`, `bash scripts/build-mac-app.sh`, then re-run the monkey walk's repro sequences against a scratch DB (launch the binary with CACTUS_DB env, never open(1)); update the .md with a `## Re-run` section (that file is yours too). Before the walk: pkill -x cactus-mac; after: open dist/Cactus.app. Keys only while the panel is confirmed frontmost (screenshot first): the human's live TUI sits behind it. When done ping: lead-cactus.
