# Codex mod mode

Codex has no idle wake: a hook cannot start a turn. The Codex plugin's `UserPromptSubmit` hook, `plugins/cactus/hooks/frontier.sh`, stands in: it re-injects the agent's inbox on every user turn and clears answered rows it has shown.

A delivery entry prompts the session right after an answer: herdr, or a webhook (`cactus deliver webhook URL --agent ID`). `plugins/cactus/hooks/session-start.sh` registers herdr only, when `HERDR_PANE_ID` is set:

    cactus deliver herdr --agent ID

Without an entry, answers surface on the next user turn.

**Runs when**

- `cactus` and `jq` are on `PATH`
- the hook payload carries a `session_id` (used as `--agent`)
- the project is not disabled: `cactus project-status --json --cwd DIR` (DIR from the payload's `cwd`, else `$PWD`) does not report `enabled: false`; a failed or empty check counts as enabled
- `cactus list -s any --agent ID --json` succeeds with output: any row, any status, cleared included

Any miss: exit 0, no output.

**Output**

First line, always:

    Cactus mod mode (plugin loaded): use --agent ID on every row; post decisions with cactus ask --no-wait, never arm a background cactus wait. This hook is the nearest Codex equivalent to the mod prompt injection and live pane: it refreshes on each user turn.

Then, when any row is elaborate, answered, open, or live:

    cactus frontier (--agent ID):
      KEY STATUS WORD
      ...
      N to elaborate, N answered to act on and clear, N open

- Order: elaborate, answered, open/live. First five only.
- `WORD` is the row's word, else the first 60 chars of its text.
- Any row with answers, live review/plan included, gets its latest: ` — skipped; use the stated default`, else ` — answer: ` plus labels joined by `, `, plus ` — TEXT` when both labels and text exist (text alone: ` — answer: TEXT`).
- With open rows, a last line: `Codex has no wake-up from idle: answers surface here on your next turn. If the next step needs one now, block: cactus get KEY --wait --timeout 300 --json`

**Auto-clear**

After printing, each row that is

- among the five printed,
- status `answered`,
- act not `review`, `plan`, or `data`,

runs `cactus clear KEY --agent ID`. A sixth answered row stays until a later turn prints it. Persistent rows (review, plan, data) stay until the agent closes them.

**Posting rule**

From the session-start line: post asks and runs with `--no-wait`; never arm a background monitor or waiter. When the next step needs an answer now, block in the foreground:

    cactus get KEY --wait --timeout 300 --json

Agent workflow: [plugins/cactus/skills/cactus/SKILL.md](../plugins/cactus/skills/cactus/SKILL.md), [skills/cactus/CODEX.md](../skills/cactus/CODEX.md).

**Test**

    bash plugins/cactus/tests/test-hooks.sh

Runs against a `mktemp` inbox. Needs `jq` and an installed `cactus` on `PATH` (`uv tool install --editable .`); it does not run the checkout.
