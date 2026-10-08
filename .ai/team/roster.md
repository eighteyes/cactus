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
