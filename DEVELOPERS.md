# DEVELOPERS

Contributor map. Users start at [README.md](README.md). Invariants live in [CLAUDE.md](CLAUDE.md).

## Architecture

Agents write rows, humans answer them, one SQLite file between them. Dependency runs one way: scope -> store -> cli -> surfaces.

    src/cactus/
      scope.py       cwd -> (project_root, cwd)
      __main__.py    `python -m cactus` entry
      store.py       all SQLite; the only module that touches the database
      cli.py         argparse verbs (cmd_*), exit codes, ownership gates, --wait, AGENT_HELP
      poke.py        delivery map + poke/visit transports (side leaf, lazy import)
      tui.py         Textual answering surface (human)
      watch.py       read-only Textual feed (human)
      www.py         HTTP board (--www)
      monitor.py     plain-stdout event stream (agent)
      mcp.py         stdio MCP server; each tool shells one `cactus --json`
      record.py      decision records -> <project>/.ai/cactus/q{N}-{id}-{slug}.md
      shell.py       clipboard, command run/spill, file preview
      tradeoffs.py   pro/con mark parser (side leaf)
      acp.py         ACP form-elicitation bridge onto blocking rows
      field.py sky.py fieldproc.py garden.py   decorative sky + seed garden
      rank.py decide.py clef_serve.py          auto-decider (proposes, never answers)
    hooks/           Claude plugin hooks (hooks.json, cactus_identity.py, stop_fork.py, frontier.py ...)
    plugins/cactus/  Codex plugin: hooks/ (hooks.json, session-start, frontier, stop, permission-request), tests/test-hooks.sh
    server/cactus-mcp  MCP launcher, referenced by .mcp.json
    scripts/package-plugin.sh  builds the Claude Desktop plugin bundle
    tests/           pytest suite, one file per module

**The mod** (push delivery) is a per-agent delivery map, not a DB table. File: `CACTUS_POKE_WEBHOOKS`, default `~/.config/cactus/poke-webhooks.json`. Entries:

    {"<agent-id>": {"herdr": true}}        prompt the row's herdr pane after an answer
    {"<agent-id>": {"url": "https://..."}} POST a webhook after an answer

Reference: [docs/delivery.md](docs/delivery.md), [docs/hooks.md](docs/hooks.md), [docs/codex-mod-mode.md](docs/codex-mod-mode.md).

## Dev setup

    git clone https://github.com/eighteyes/cactus && cd cactus
    uv sync --group dev
    uv run pytest
    uv tool install --editable .     # cactus, cac, cactus-mcp

Run from the checkout against a scratch inbox. Never the default DB: it is the live inbox.

    CACTUS_DB=$(mktemp -d)/s.db CACTUS_POKE=true CACTUS_RECORDS=0 PYTHONPATH=src python3 -m cactus --help

## Conventions

- New files open with a name / description / Responsibilities header (`src/cactus/poke.py`, `hooks/stop_fork.py`). Older files lack one (`plugins/cactus/hooks/*.sh`, `src/cactus/acp.py`).
- `Store` is the only SQLite caller. Read-then-insert runs under `BEGIN IMMEDIATE` (`src/cactus/store.py` `Store.ask`). Multi-write state changes share one transaction so pollers never see half (`Store.answer`).
- cli validates and gates ownership; Store stays mechanism (`src/cactus/cli.py` `_refuse_if_not_owner`).
- Exit codes: 0 ok, 1 error, 2 `--wait` timeout, 3 no match (`src/cactus/cli.py` `EXIT_OK`, `EXIT_ERROR`, `EXIT_TIMEOUT`, `EXIT_EMPTY`). argparse errors forced to 1 (`cli.py` `_ArgumentParser`).
- Errors: one `cactus: ...` stderr line through `_msg(exc)` (`cli.py` `_msg`).
- Side leaves and Textual import lazily at the call site (`cli.py` `cmd_answer`, `main`).
- Program launches take an env override with `{placeholders}`: `CACTUS_POKE`, `CACTUS_VISIT`, `CACTUS_PAGER`, `CACTUS_EDITOR`, `CACTUS_OPEN`. `CACTUS_POKE_WEBHOOKS` moves the delivery map file. No override: clipboard (`shell.copy`), webhook POST (`poke.py` `_post_webhook`).
- Schema changes are additive on open; rebuilds sit behind `cactus migrate --yes` (`store.py` `Store._migrate`, `Store.needs_key_rebuild`).
- After-commit side effects fail soft: records and delivery never roll back the write (`store.py` `Store._record`; `cli.py` `cmd_answer`).
- Shared config writes are atomic temp + `os.replace` (`poke.py` `write_delivery`).
- Renames keep an alias (`poke_webhook_if_mapped = deliver_if_mapped`, `poke.py` `poke_webhook_if_mapped`).
- Decisions cite the row key: `q469` in `hooks/stop_fork.py`, `q430` in CLAUDE.md.
- Hooks read stdin into `input` before importing `cactus_identity`. Most exit 0 when `cactus` is missing or `cactus project-status --json` says disabled; Codex `session-start.sh` prints a disabled line instead.

Full list: [docs/conventions.md](docs/conventions.md). Terms: [docs/glossary.md](docs/glossary.md).

## Key flows

**Ask -> wait -> answer (blocking)**

    cli.py main
      scope.py resolve_project
      store.py Store.__init__        WAL, busy_timeout
      cli.py cmd_ask                 validation refusals
      store.py Store.ask             BEGIN IMMEDIATE, per-project q{N}
      cli.py _post_then_wait         prints key
      store.py Store.wait_for_answer polls until status leaves open/elaborate; exit 2 on timeout

**Human answer -> delivery (the mod)**

    tui.py CactusApp._submit_answer
      store.py Store.answer          BEGIN IMMEDIATE; _record -> record.py write_record
      tui.py CactusApp._auto_poke_webhook
      poke.py deliver_if_mapped
        poke.py delivery_entry       <- poke.py load_webhooks
        herdr entry:   poke.py poke(webhook=False) -> CACTUS_POKE or `herdr agent prompt` to the row's pane
        webhook entry: poke.py _post_webhook

CLI path: `cli.py` `cmd_answer` -> same `deliver_if_mapped` (called from `cmd_answer`); failure prints `cactus: answer saved; webhook poke failed: ...`. HTTP path: `www.py` `_Handler._handle_answer`.

**Register delivery**

    plugins/cactus/hooks/session-start.sh     only when HERDR_PANE_ID is set
      cactus deliver herdr --agent ID
      cli.py cmd_deliver             bare form reads; exit 3 if none
      poke.py write_delivery         atomic, chmod 600, other entries kept

No DB change. Verb: `cactus deliver [herdr | webhook URL | off] --agent ID`.

**Hook frontier + Stop gate**

    Claude  hooks/hooks.json Stop -> hooks/stop_fork.py
      CACTUS_STOP_HOOK=0 -> exit
      no `cactus` -> exit
      project-status disabled -> exit
      cactus_identity.py resolve_agent      payload session_id > herdr > CACTUS_AGENT
      cactus list -s open --agent ID        open row in this project -> silent (q469, stop_fork.py); live/elaborate don't count
      stop_hook_active -> silent
      turn opened by task-notification / cross-session message -> silent
      else transcript has cactus ask|edit|plan|review or AskUserQuestion -> silent
      else {"decision":"block",...}         stop_fork.py

    Codex   plugins/cactus/hooks/frontier.sh (UserPromptSubmit, mod-mode substitute)
      cactus list -s any --agent ID --json
      prints mod-mode line + first 5 rows (elaborate, answered, open/live) with latest answer
      cactus clear KEY --agent ID           printed answered rows, not review/plan/data

Failures and fixes: [docs/troubleshooting.md](docs/troubleshooting.md). Surfaces: [docs/interfaces.md](docs/interfaces.md), [docs/dataflows.md](docs/dataflows.md).

## Testing

    uv run pytest                                   # tests/, asyncio auto, -q
    uv run pytest tests/test_deliver.py tests/test_hooks.py
    uv run pytest -m 'not slow'                     # skip wall-clock probes
    bash plugins/cactus/tests/test-hooks.sh         # Codex hooks, mktemp CACTUS_DB

`tests/conftest.py` `scratch_env` isolates `CACTUS_DB`, `CACTUS_POKE`, `CACTUS_POKE_WEBHOOKS`, records, rank/decide. Use its `store`, `project`, `cli` fixtures. A bug-exposing test is `xfail` with a reason, never deleted.

## Release

    bash scripts/package-plugin.sh    # dist/cactus-<version>.plugin

Codex plugin version: `plugins/cactus/.codex-plugin/plugin.json`. Details: [DEPLOYMENT.md](DEPLOYMENT.md).
