# Delivery

How an answer reaches the agent that owns a row. One JSON map, one entry per agent.
No entry, no delivery: a Claude agent wakes on its own backgrounded wait; a Codex agent (posts `--no-wait`) sees the answer on its next user turn via the frontier hook.

## Set it

```bash
cactus deliver herdr --agent ID          # answer prompts the row's herdr pane
cactus deliver webhook URL --agent ID    # answer POSTs to URL
cactus deliver --agent ID                # print the entry
cactus deliver off --agent ID            # remove the entry
```

Output:

```
ID: herdr
ID: webhook URL
ID: delivery off
```

- `--json` prints the raw entry, e.g. `{"herdr": true}`. `off --json` prints `null`.
- No entry: `cactus: no match`, exit 3. Bare read and `off` both.
- `deliver herdr URL`: ``cactus: URL only goes with `deliver webhook` ``, exit 1.
- `deliver webhook` with no URL: `cactus: deliver webhook needs a URL`, exit 1.
- `--agent` is required. Blank: `cactus: deliver needs a non-empty --agent`, exit 1.
- Touches no database row. `cactus` still opens (and creates) `CACTUS_DB` first.

Every flag: [interfaces.md](interfaces.md).

## The map

Path: `~/.config/cactus/poke-webhooks.json`. `CACTUS_POKE_WEBHOOKS` overrides it.

A JSON object keyed by agent id:

```json
{
  "agent-a": {"herdr": true},
  "agent-b": {"url": "https://example.test/hook"}
}
```

- `{"herdr": true}` is a herdr entry only when it has no `url` key.
- Any other object is a webhook entry, `url` or not. It may also carry `authorization` (or `Authorization`) and `headers`; see [WEBHOOK_SETUP.md](../skills/cactus/WEBHOOK_SETUP.md).
- A missing file or a JSON `null` reads as empty.
- `cactus deliver` replaces one agent's entry whole and keeps every other entry.
- Writes go to a temp file renamed into place. The parent directory is created. The file is mode 0600.

Read errors:

```
cannot read webhook map PATH: ...
webhook map PATH must be a JSON object keyed by agent id
webhook map entry for 'ID' must be an object
```

At delivery, a webhook entry with no string `url`: `webhook map entry for 'ID' needs a string url`.

## When it fires

After an answer from any surface:

- `cactus answer`: stderr `auto-poke: RESULT` (text mode).
- `cactus exec KEY` on a `run` row: same stderr line, same failure line.
- TUI: flash `answered; auto-poked ID`.
- `cactus --www`: the reply carries `poked` / `poke_error`.

A failed delivery never undoes the answer. `cactus answer` prints
`cactus: answer saved; webhook poke failed: ...`; the TUI flashes
`answered; webhook poke failed: ...`.

## What it sends

herdr entry: prompts the row's stamped pane.

```
cactus: a row was answered — read it with `cactus feed --json --agent ID`.
```

- Row with no pane stamp: skipped, silently.
- `CACTUS_POKE` replaces the herdr transport.

Webhook entry: POSTs JSON `{"agent": ID, "message": ...}`.

```
cactus: your inbox moved — re-read it with `cactus feed --json --agent ID` and act on what changed.
```

- `CACTUS_POKE` is ignored here.

## Who registers

- Codex: the plugin's session-start hook runs `cactus deliver herdr --agent ID` when `HERDR_PANE_ID` is set. On exit 0 it prints `Cactus registered herdr delivery for ID: answers prompt this pane.`; a failure is silent. It skips registration when the payload has no `session_id`, `cactus` or `jq` is missing, or the project is disabled.
- Claude, Grok, anything else: run `cactus deliver` yourself. Webhook walkthrough: [WEBHOOK_SETUP.md](../skills/cactus/WEBHOOK_SETUP.md).

Source: `src/cactus/poke.py`, `cmd_deliver` in `src/cactus/cli.py`, `plugins/cactus/hooks/session-start.sh`.
