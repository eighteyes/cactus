# Glossary

One name per concept. The name is the one the code uses. Sites are `file:line`.

**Inbox**

row
: One question an agent posted. The code type is `Question`. `src/cactus/store.py:317`

key
: `qN`, numbered per project after `cactus migrate --yes`; global `q{rowid}` before. `LABEL:qN` or `/abs/path:qN` names a row in another project. `src/cactus/store.py:896`, `src/cactus/store.py:1707`

project
: Git toplevel of the asking cwd, or the cwd itself. `src/cactus/scope.py:34`

thread
: Named group of rows, unique per agent, not per project. `src/cactus/store.py:322`

agent
: The row's owner: the conversation id passed as `--agent`. `src/cactus/store.py:328`

pane
: The herdr pane id stamped on a row at ask time (`w3B:p3`). Poke and visit target it. `src/cactus/store.py:332`

act
: What the row asks for: `ask`, `steer`, `run`, `notify`, `review`, `plan`, `data`. `src/cactus/store.py:58`

kind
: How the answer is collected: `choice`, `multi`, `text`, `confirm`. `src/cactus/store.py:40`

status
: `open`, `live`, `elaborate`, `answered`, `cleared`. `src/cactus/store.py:43`

persistent row
: A `review`, `plan`, or `data` row. Born `live`, answerable repeatedly. `src/cactus/store.py:62`

one-shot row
: Any other act. One answer moves it to `answered`. `src/cactus/store.py:1004`

blocked
: Whether the agent waits on the row. Defaults per act; `--no-block` overrides. `src/cactus/store.py:69`

answer
: One entry in a row's append-only answers log. `src/cactus/store.py:270`

verdict
: An answer on a persistent row. The latest one is the row's answer. `src/cactus/store.py:155`

chosen
: The option a `steer` row already acts on. The human only vetoes. `src/cactus/store.py:335`

recommend
: The agent's advisory pick. Still waits for the human. `src/cactus/store.py:351`

elaborate
: Status: the human asked for a rewrite. Takes no answer until `cactus edit` or a withdraw (`u`, `cactus elaborate --withdraw`). `src/cactus/store.py:1399`, `src/cactus/store.py:1426`

heard state
: `sent` / `heard` / responded, measured against the latest verdict. `src/cactus/store.py:372`

cursor
: Change token `(max id, max updated_at, row count)` pollers compare. `src/cactus/store.py:1947`

decision record
: Markdown copy of a row in `<project>/.ai/cactus/q{N}-{id}-{slug}.md`. `src/cactus/record.py:293`

rehome
: Move this pane's rows to a new `--agent`. `src/cactus/store.py:2002`

auto pick
: The auto-decider's proposal on a row. Never an answer. `src/cactus/store.py:366`

**Delivery (the mod)**

poke
: Contentless nudge to a row's owner: `CACTUS_POKE`, then webhook, then a herdr prompt to the pane. `src/cactus/poke.py:283`

reachable
: A row `poke` can reach: an owner plus an override, a webhook, or a pane. `src/cactus/poke.py:336`

visit
: Focus the human's herdr view on a row's pane. `src/cactus/poke.py:348`

delivery map
: Per-agent JSON file at `CACTUS_POKE_WEBHOOKS`, default `~/.config/cactus/poke-webhooks.json`. Written atomically, mode 0600. `src/cactus/poke.py:125`

delivery entry
: One agent's map value, any JSON object; unknown keys kept. `cactus deliver` writes `{"herdr": true}` or `{"url": URL}`. `src/cactus/poke.py:102`

herdr entry
: `{"herdr": true}` with no `url`. After an answer, prompts the row's pane; `CACTUS_POKE` overrides; no pane, silent skip. `src/cactus/poke.py:112`, `src/cactus/poke.py:172`

webhook entry
: Any entry that is not a herdr entry. After an answer, POSTs `{agent, message}`; ignores `CACTUS_POKE`. No string `url`: error. `src/cactus/poke.py:117`, `src/cactus/poke.py:197`

deliver
: After an answer, push to an agent with a delivery entry. Unregistered agents get nothing. `src/cactus/poke.py:149`

`cactus deliver`
: Set, read, or remove an agent's delivery entry. Bare form prints it, exit 3 if none. `src/cactus/cli.py:1294`

**Hooks**

identity
: Hook agent id: payload `session_id`, then herdr, then `CACTUS_AGENT`. `hooks/cactus_identity.py:18`

frontier
: The agent's own rows injected on each user prompt: elaborate, answered, open and live. `hooks/frontier.py:40`

mod mode
: Codex stand-in for the pane mod: post `--no-wait`, never arm a waiter, read answers from the frontier. `plugins/cactus/hooks/frontier.sh:17`

pane mod
: The live-pane setup mod mode substitutes for under Codex. `plugins/cactus/README.md:3`

auto-clear
: Codex frontier clears the answered one-shot rows it just printed. `plugins/cactus/hooks/frontier.sh:42`

fork
: A decision posted to cactus. The Stop hook blocks a turn that posted none. `hooks/stop_fork.py:3`

open-row gate
: Stop hook stays silent while the agent has an `open` row in this project (q469). Other projects, `live`, and `elaborate` do not count. `hooks/stop_fork.py:38`

**Drift**

- delivery map vs webhook map: same file. `poke.py` docstrings, errors, and `CACTUS_POKE_WEBHOOKS` say webhook; it also holds herdr entries. `src/cactus/poke.py:81`, `src/cactus/poke.py:95`
- deliver vs poke: `poke_webhook_if_mapped` is a back-compat alias of `deliver_if_mapped`. `src/cactus/poke.py:183`
- auto delivery vs CLAUDE.md: CLAUDE.md says the poke on an answer reaches webhook-mapped agents only and ignores `CACTUS_POKE`. Code also delivers to herdr entries, and those honor `CACTUS_POKE`. `CLAUDE.md:434`, `src/cactus/poke.py:172`
- row vs question: CLI and docs say row; the type and table are `questions`. `src/cactus/store.py:317`
