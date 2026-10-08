# Glossary

One name per concept. The name is the one the code uses. Sites are `file:line`.

**Inbox**

row
: One question an agent posted. The code type is `Question`. `src/cactus/store.py` `Question`

key
: `qN`, numbered per project after `cactus migrate --yes`; global `q{rowid}` before. `LABEL:qN` or `/abs/path:qN` names a row in another project. `src/cactus/store.py` `Store.ask`, `Store.resolve_ref`

project
: Git toplevel of the asking cwd, or the cwd itself. `src/cactus/scope.py` `resolve_project`

thread
: Named group of rows, unique per agent, not per project. `src/cactus/store.py` `Question.thread`

agent
: The row's owner: the conversation id passed as `--agent`. `src/cactus/store.py` `Question.agent`

pane
: The herdr pane id stamped on a row at ask time (`w3B:p3`). Poke and visit target it. `src/cactus/store.py` `Question.pane`

act
: What the row asks for: `ask`, `steer`, `run`, `notify`, `review`, `plan`, `data`. `src/cactus/store.py` `ACTS`

kind
: How the answer is collected: `choice`, `multi`, `text`, `confirm`. `src/cactus/store.py` `KINDS`

status
: `open`, `live`, `elaborate`, `answered`, `cleared`. `src/cactus/store.py` `STATUSES`

persistent row
: A `review`, `plan`, or `data` row. Born `live`, answerable repeatedly. `src/cactus/store.py` `PERSISTENT_ACTS`

one-shot row
: Any other act. One answer moves it to `answered`. `src/cactus/store.py` `Store.answer`

blocked
: Whether the agent waits on the row. Defaults per act; `--no-block` overrides. `src/cactus/store.py` `DEFAULT_BLOCKED`

answer
: One entry in a row's append-only answers log. `src/cactus/store.py` `Answer`

verdict
: An answer on a persistent row. The latest one is the row's answer. `src/cactus/store.py` `SCHEMA`

chosen
: The option a `steer` row already acts on. The human only vetoes. `src/cactus/store.py` `Question.chosen`

recommend
: The agent's advisory pick. Still waits for the human. `src/cactus/store.py` `Question.recommend`

elaborate
: Status: the human asked for a rewrite. Takes no answer until `cactus edit` or a withdraw (`u`, `cactus elaborate --withdraw`). `src/cactus/store.py` `Store.elaborate_request`, `Store.unelaborate`

heard state
: `sent` / `heard` / responded, measured against the latest verdict. `src/cactus/store.py` `Question.heard_state`

cursor
: Change token `(max id, max updated_at, row count)` pollers compare. `src/cactus/store.py` `Store.cursor`

decision record
: Markdown copy of a row in `<project>/.ai/cactus/q{N}-{id}-{slug}.md`. `src/cactus/record.py` `write_record`

rehome
: Move this pane's rows to a new `--agent`. `src/cactus/store.py` `Store.rehome`

auto pick
: The auto-decider's proposal on a row. Never an answer. `src/cactus/store.py` `Question.auto_pick`

**Delivery (the mod)**

poke
: Contentless nudge to a row's owner: `CACTUS_POKE`, then webhook, then a herdr prompt to the pane. `src/cactus/poke.py` `poke`

reachable
: A row `poke` can reach: an owner plus an override, a webhook, or a pane. `src/cactus/poke.py` `reachable`

visit
: Focus the human's herdr view on a row's pane. `src/cactus/poke.py` `visit`

delivery map
: Per-agent JSON file at `CACTUS_POKE_WEBHOOKS`, default `~/.config/cactus/poke-webhooks.json`. Written atomically, mode 0600. `src/cactus/poke.py` `write_delivery`

delivery entry
: One agent's map value, any JSON object; unknown keys kept. `cactus deliver` writes `{"herdr": true}` or `{"url": URL}`. `src/cactus/poke.py` `delivery_entry`

herdr entry
: `{"herdr": true}` with no `url`. After an answer, prompts the row's pane; `CACTUS_POKE` overrides; no pane, silent skip. `src/cactus/poke.py` `is_herdr_entry`, `deliver_if_mapped`

webhook entry
: Any entry that is not a herdr entry. After an answer, POSTs `{agent, message}`; ignores `CACTUS_POKE`. No string `url`: error. `src/cactus/poke.py` `webhook_entry`, `_post_webhook`

deliver
: After an answer, push to an agent with a delivery entry. Unregistered agents get nothing. `src/cactus/poke.py` `deliver_if_mapped`

`cactus deliver`
: Set, read, or remove an agent's delivery entry. Bare form prints it, exit 3 if none. `src/cactus/cli.py` `cmd_deliver`

**Hooks**

identity
: Hook agent id: payload `session_id`, then herdr, then `CACTUS_AGENT`. `hooks/cactus_identity.py` `resolve_agent`

frontier
: The agent's own rows injected on each user prompt: elaborate, answered, open and live. `hooks/frontier.py` `main`

mod mode
: Codex stand-in for the pane mod: post `--no-wait`, never arm a waiter, read answers from the frontier. `plugins/cactus/hooks/frontier.sh:17`

pane mod
: The live-pane setup mod mode substitutes for under Codex. `plugins/cactus/README.md:3`

auto-clear
: Codex frontier clears the answered one-shot rows it just printed. `plugins/cactus/hooks/frontier.sh:42`

fork
: A decision posted to cactus. The Stop hook blocks a turn that posted none. `hooks/stop_fork.py`

open-row gate
: Stop hook stays silent while the agent has an `open` row in this project (q469). Other projects, `live`, and `elaborate` do not count. `hooks/stop_fork.py` `main`

**Drift**

- delivery map vs webhook map: same file. `poke.py` docstrings, errors, and `CACTUS_POKE_WEBHOOKS` say webhook; it also holds herdr entries. `src/cactus/poke.py` `webhooks_path`, `load_webhooks`
- deliver vs poke: `poke_webhook_if_mapped` is a back-compat alias of `deliver_if_mapped`. `src/cactus/poke.py` `poke_webhook_if_mapped`
- auto delivery vs CLAUDE.md: CLAUDE.md says the poke on an answer reaches webhook-mapped agents only and ignores `CACTUS_POKE`. Code also delivers to herdr entries, and those honor `CACTUS_POKE`. `CLAUDE.md (Invariants, the push-delivery bullet)`, `src/cactus/poke.py` `deliver_if_mapped`
- row vs question: CLI and docs say row; the type and table are `questions`. `src/cactus/store.py` `Question`
