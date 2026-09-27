# macapp — context

## Decisions

- q297 swift-native over kitty-qa and swift-web.
- q304 steer: feed-json read path, chosen. store.py remains the only DB module.
- q301 steer: build the spike now, chosen.
- q302 location: `mac/` in-repo. q303 hotkey: ⇧Space (answered as free text "shift-space").

## Key files

- src/cactus/cli.py — `cmd_feed`, `cmd_answer`, `cmd_clear`; exit codes 0/1/2/3.
- src/cactus/mcp.py — precedent: every tool is one `cactus --json` subprocess.
- src/cactus/www.py — precedent for a second human surface over the same verbs.
- src/cactus/store.py — `ACTIONABLE` statuses; feed emits `cursor` + `questions`.

## feed --json shape

    {"cursor": {"max_id", "max_updated", "count", "blocked": {agent: n}},
     "questions": [{key, ref, project, text, context, kind, act, status,
                    choices: [{label, description}], recommend, confidence,
                    recommend_why, chosen, blocked, thread, parent, agent, ...}]}

## Constraints

- No herdr dependency. Stamps are optional; poke is out of scope.
- `cactus` must be on PATH for the app process; launchd/GUI PATH differs from
  the shell — resolve via `/bin/zsh -lc 'command -v cactus'` once at start.
- Answer refusals arrive as stderr text, exit 1; `AlreadyAnswered` exit 3.
