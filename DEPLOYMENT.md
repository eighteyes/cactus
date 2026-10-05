# DEPLOYMENT

cactus ships as a local tool and three host plugins. No server, no CI, no container. Every deploy is manual.

## Targets

	target            source                                   ships
	CLI               pyproject.toml                           `cactus`, `cac`, `cactus-mcp`
	Claude Code       .claude-plugin/marketplace.json          skill, root hooks/, bundled `cactus`, MCP server (.mcp.json)
	Codex             .agents/plugins/marketplace.json         plugins/cactus: skill, hooks (the mod substitute)
	Claude Desktop    scripts/package-plugin.sh                dist/cactus-<version>.plugin: MCP server, hooks, skills

Versions: `pyproject.toml` and `.claude-plugin/plugin.json` carry `0.3.0`. The Codex plugin carries its own, `0.3.0+codex.<timestamp>` in `plugins/cactus/.codex-plugin/plugin.json`, bumped by hand.

## Deploy

CLI, from a checkout:

	uv tool install --editable . --reinstall

Claude Code:

	/plugin marketplace add eighteyes/cactus
	/plugin install cactus@cactus

Codex (install the CLI first; the plugin ships no launcher):

	codex plugin marketplace add eighteyes/cactus
	codex plugin add cactus@cactus-local

Trust the plugin hooks after install. Start a new Codex thread to load them.

Claude Desktop:

	scripts/package-plugin.sh

Writes `dist/cactus-<version>.plugin`, version read from `.claude-plugin/plugin.json`.

Trigger: none. A commit deploys nothing until one of the commands above runs.

## Configuration & secrets

	name                    source                                  effect
	CACTUS_DB               shell env                               inbox path; set but empty refuses
	CACTUS_POKE_WEBHOOKS    shell env                               delivery map path; default ~/.config/cactus/poke-webhooks.json
	CACTUS_POKE             shell env                               poke transport override; also replaces herdr delivery, never webhook delivery
	CACTUS_STOP_HOOK        shell env                               `0` disables both Stop hooks, Claude and Codex
	CACTUS_AGENT            shell env                               last-resort agent identity in hooks
	CACTUS_AGENT            .mcp.json                               MCP server default agent (`claude-desktop`); hooks never see it
	HERDR_PANE_ID           set by herdr                            Codex SessionStart registers herdr delivery only when set

**Delivery map** (the mod's push route). One JSON object keyed by agent id, file mode 0600, written atomically by `cactus deliver`:

	{"herdr": true}         after an answer, prompt the row's herdr pane; no pane, no prompt
	{"url": URL}            after an answer, POST {agent, message} to URL

A webhook entry may carry `authorization` and `headers`. Those are credentials. They live only in the map file. Never commit it.

	cactus deliver herdr --agent ID
	cactus deliver webhook URL --agent ID
	cactus deliver --agent ID              # read; exit 3 when unset
	cactus deliver off --agent ID          # drop; exit 3 when unset

The Codex `session-start.sh` runs `cactus deliver herdr --agent <session_id>` inside a herdr pane. Nothing removes that entry.

## Health & verification

	cactus --version                                   # cactus 0.3.0
	uv run pytest tests/test_deliver.py tests/test_hooks.py
	bash plugins/cactus/tests/test-hooks.sh            # Codex frontier.sh only, scratch inbox, `cactus` from PATH
	cactus deliver --agent ID                          # ID: herdr | ID: webhook URL

Codex: on each user turn, once the thread's own session owns any row (cleared included), prints `Cactus mod mode (plugin loaded): ...`. The `cactus frontier (--agent ID):` block follows only when it owns an elaborate, answered, open or live row. A new thread prints nothing until it posts one. Answered one-shot rows among the first five printed get cleared.

Claude Code: the Stop hook prints `{"decision":"block",...}` to stdout when a human-opened turn ends with no Bash `cactus`/`cac` `ask|edit|plan|review` and no AskUserQuestion. It posts no row. Silent when the agent has an `open` row in this project (q469), when `stop_hook_active` is set, or when a task-notification or cross-session message opened the turn.

Answer delivery: `cactus answer` (text mode) prints `auto-poke: ...` to stderr when a delivery fired. A failed one prints `cactus: answer saved; webhook poke failed: ...`; the answer stays saved.

## Rollback

No rollback path exists in this repo. Tag `v0.2.0` exists; no script or doc installs from a tag.

Not undone by reinstalling older code:

- `cactus migrate --yes` table rebuilds. Older modules may not read the rebuilt schema.
- Delivery map entries. Drop with `cactus deliver off --agent ID`.
- Decision records already written to `<project>/.ai/cactus/`.
- Pokes and webhook POSTs already sent.
- Rows the Codex frontier hook already cleared. Restore with `cactus reopen KEY --agent ID`.
