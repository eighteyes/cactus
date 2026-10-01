# Webhook poke setup

Poke nudges the **row's owning agent** (`--agent` on that question). It does
not follow the TUI process environment, and it is not the same as answering.

| Action | What it does | Wakes the agent? |
|--------|--------------|------------------|
| Answer in TUI / `cactus answer` | Writes the answer into SQLite | **Yes.** Webhook-mapped agent: its webhook is POSTed. Otherwise the owner's herdr pane is prompted (auto-poke, `poke.wake_owner`). |
| `p` in TUI / `cactus poke` | Runs the poke transport for that row's agent | Yes, if transport succeeds (manual; still useful) |
| `cactus --monitor --once` | Exits on the first inbox event | Fallback for an agent with no pane and no webhook; its exit is the wake |

Answering **auto-pokes** the owner: a webhook-mapped agent by HTTP POST,
any other by its herdr pane. You do not need a separate `p` after the answer. Manual `p` remains
for “nudge without answering” or a failed auto-poke retry.

## Resolution order

1. `CACTUS_POKE` — if set, used for **every** agent (tests / forced override)
2. Webhook map entry for that agent id
3. Default: `herdr agent prompt {agent} {message}`

Do **not** set a global `CACTUS_POKE` in your shell profile for day-to-day use.
That steals poke from herdr agents. Prefer the per-agent map.

## Webhook map

Default path: `~/.config/cactus/poke-webhooks.json`  
Override path: `CACTUS_POKE_WEBHOOKS=/path/to/map.json`

```json
{
  "AGENT_ID_ONE": {
    "url": "https://example.com/automations/webhook/…",
    "authorization": "Bearer …"
  },
  "AGENT_ID_TWO": {
    "url": "https://example.com/automations/webhook/…",
    "authorization": "Bearer …"
  }
}
```

Field notes:

- Key = the exact string passed as `cactus ask --agent …` (stable agent id).
- `url` — required; POST target for that agent only.
- `authorization` — optional; sent as the `Authorization` header as written
  (include the `Bearer ` prefix when the receiver expects it).
- `headers` — optional object; merged into the request headers.
- Body is always JSON: `{"agent":"<id>","message":"<poke text>"}`.

One file can list many agents. Each external agent needs **its own** webhook
URL (and usually its own sender key / token). Sharing one URL across agents
only works if that receiver fans out by the `agent` field in the body.

Do not commit this file. `chmod 600` is appropriate.

## Behaviour

- `cactus poke KEY` and TUI `p` call `poke(row.agent)`.
- Mapped agent → HTTP POST (no herdr required; pane/session may be null).
- Unmapped agent → herdr (needs a real herdr agent id).
- After `cactus answer` / TUI answer (including skip, elaborate/decompose
  request, run approve/deny, review/plan verdict): a webhook-mapped owner gets
  its webhook; a herdr owner gets its pane prompted. Data chunk copies,
  clears and undo never wake.
- `CACTUS_POKE`, when set, overrides both for auto-poke too.
- TUI offers `p` whenever the row has an `--agent`, including webhook-only
  agents. Restart the TUI after upgrading cactus so answer auto-poke and
  `_pokeable` pick up.

## Checklist: wake an external agent (e.g. Grok Bot)

1. **Stable id** — pick the agent's id and use that exact string on every
   `cactus ask --agent` / `clear --agent` for that bot.
2. **Webhook receiver** — create a wake routine (or equivalent) on that agent
   that runs when its webhook is POSTed. The routine should re-read the cactus
   feed for that agent id, act on answered/elaborate rows, clear when done,
   and report in chat.
3. **Map entry** — put that agent's `url` + `authorization` under its id in
   `~/.config/cactus/poke-webhooks.json`.
4. **CLI on PATH** — `command -v cactus` on the machine where asks/pokes run
   (human TUI and any agent shells that post rows).
5. **Human loop** — open `cactus --tui` and answer the row. Webhook agents
   are auto-poked on answer, and so are herdr agents (their pane).
   Press **`p`** only for a manual nudge.

Repeat steps 2–3 for each additional Grok Bot (or other webhook agent). Herdr
agents need no map entry.

## Smoke test (full round-trip)

Prove answer → poke → wake with the answer already present:

```bash
cd /path/to/project   # rows file under this project
# Map must already list AGENT_ID

cactus ask "webhook poke round-trip — answer, then press p" \
  --agent AGENT_ID --by "My Bot" \
  -c "Wake worked" -c "No wake" \
  --recommend "Wake worked" --confidence high

# Note the key (qN). In cactus --tui: select Wake worked (auto-poke fires).
# Or from CLI (also auto-pokes when AGENT_ID is mapped):
cactus answer qN -s "Wake worked"
```

Expect:

1. Webhook receiver wakes on the answer (no separate `p` required).
2. `cactus get qN --json` shows the selection. Open inbox may be empty after
   answer — that is normal; answered rows leave the open list.
3. Agent clears the row after acting.

`cactus poke qN` without answering only proves the webhook path; the agent
will correctly report “still open.”

## Gotchas

- **Answer should auto-wake webhook agents.** If chat never updates after you
  pick a choice for a mapped agent, check the map, HTTP status, and TUI flash
  (`answered; auto-poked …` or `webhook poke failed`). Unmapped agents are
  poked through their herdr pane; one with no pane has no wake but
  `--monitor --once`.
- **“I don’t see qN.”** Status is already `answered` or `cleared`. Use
  `cactus get cactus:qN --json` or filter by status; the TUI open list hides
  them.
- **Wrong project.** `cactus where` shows where the row is filed. `cd` to the
  intended project (or use `LABEL:qN` / absolute `project:qN` keys).
- **Stale TUI.** After upgrading poke/`_pokeable` behaviour, quit and restart
  `cactus --tui`.
- **Global `CACTUS_POKE`.** Fine for tests; bad as a login-shell default when
  herdr and webhook agents share one machine.
- **`--monitor --once` is not a substitute** for webhook wake on agents that
  cannot keep a local background process attached to chat.


## Install as a Grok Bot skill

There is no cactus entry in the Grok Bot plugin catalog. Ship the agent recipe
as a **shared user skill** (visible to every assistant on the account).

1. Open `skills/cactus/SKILL.md` in this repo (frontmatter `name` + `description`,
   markdown body = recipe).
2. Ask any Grok Bot to save it: skill write with that name, description, and
   body (the bot uses its skill-authoring / `update_state` path). Companion
   files such as this one are not attached automatically — either keep the
   webhook checklist in the skill body appendix or leave this file in the repo
   for humans.
3. Confirm it appears as a skill pill (e.g. invoked with `/` or `@`). New and
   existing Grok Bots on the account can then load it.

Still required outside the skill file:

- `cactus` on PATH on machines where asks/answers/pokes run
- Per Grok Bot: webhook wake routine + map entry under that bot's agent id
  (see checklist above)

Claude Code continues to use `/plugin marketplace add eighteyes/cactus` and
`/plugin install cactus@cactus` — that path does not install into Grok Bot.

## Skill pointer

Agents: keep using the workflow in [SKILL.md](SKILL.md). Webhook poke is only
how some owners get woken; ask / clear / identity rules are unchanged.
