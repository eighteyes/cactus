# cactus

A durable question inbox between coding agents and a human.

An agent posts a question, receives a key, and continues working. The human
answers from a terminal UI on their own schedule. The agent reads the answer
when it reaches the point that depends on it. Questions persist in SQLite, so
they survive the agent's session and remain readable by the next agent working
in the same repository.

cactus replaces a blocking prompt with an inbox. A question that does not gate
the next action is posted and collected later; only a question with no safe
default blocks.

## Install

The CLI requires Python 3.11 or later and installs with [uv](https://docs.astral.sh/uv/):

    uv tool install git+https://github.com/eighteyes/cactus

This provides the `cactus` command and the `cac` alias. From a checkout:

    uv tool install --editable .
    PYTHONPATH=src python3 -m cactus --help

### Claude Code plugin

The repository is also a Claude Code plugin marketplace. The plugin adds a
skill that teaches agents the workflow, a courier agent that waits on answers,
and the hooks described under [Plugin hooks](#plugin-hooks).

    /plugin marketplace add eighteyes/cactus
    /plugin install cactus@cactus

The plugin puts its own `cactus` launcher on `PATH`, so agents need no separate
install; the agent commands require only `python3` 3.11 or later. `--tui` and
`--watch` also need textual: the launcher uses it when installed, otherwise
runs through `uv` with textual added, otherwise prints the install command.
When cactus is also installed with `uv tool install`, both copies read the
same database; keep them at the same version.

## Quick start

Human:

    cactus --tui

Agent:

    cactus --monitor --agent "$AGENT"          # keep running; one line per change
    cactus ask "Which auth backend?" --agent "$AGENT" \
      -c "oidc: existing IdP" -c "local: bcrypt table" \
      --recommend oidc --confidence med \
      --context "Staging tenant exists. Local means owning password reset."
    q7

The TUI shows the question with the recommended option marked and preselected.
When the human answers, the monitor prints `q7  answered  [oidc]`, and the agent
reads the full answer with `cactus get q7 --json`.

`cactus --agent-help` prints the complete agent reference as a man page.

## Agent workflow

1. Start `cactus --monitor --agent ID` before the first question and keep it
   running while any of the agent's rows are open.
2. Post each decision the human must make with `cactus ask … --agent ID`,
   adding `--recommend` and `--confidence` when the agent has a preferred
   option.
3. Continue with work the answer does not block, and act on each monitor event
   as it arrives.
4. Retire rows the agent has acted on with `cactus clear KEY --agent ID`.

`--agent` is required on `ask` and `--monitor`. It should be the agent's
declared session identity rather than a terminal pane id, because a pane id
outlives the conversation that used it.

When a tool's time limit ends a foreground monitor while the human is away,
`cactus --monitor --agent ID --once` runs in the background and exits on the
first event other than `asked`.

## Human surfaces

    cactus --tui       answer the inbox
    cactus --watch     read-only live feed
    cactus --www       localhost web answering surface (no textual needed)

Both span every project; `--here` limits them to the current one. The TUI is
keyboard-driven:

    j / k        move between questions
    1-9          pick or toggle an option; tick a plan step
    enter        submit (a recommended option is preselected)
    y / n        answer a confirm row
    i            type free text
    e            ask the agent to elaborate, with an optional hint
    s            skip (answers with no decision)
    c            clear (retire without answering)
    u            undo, walking back through the session's actions
    R            run a row's command;  C copy it;  O open its full output
    d            dismiss a notice
    p            poke the row's agent
    [ / ]        switch project
    q            quit

A mouse click moves the highlight and never submits.

## MCP server

`server/cactus-mcp` exposes the agent verbs to any Model Context Protocol client
over stdio. It runs from the checkout or the installed plugin with `python3`
alone, the same way `bin/cactus` does: no install step, no dependency beyond
the standard library. Each tool runs one `cactus` verb with `--json`, so
validation, ownership and exit codes are the CLI's. Claude Desktop reads it
from `claude_desktop_config.json`:

    {
      "mcpServers": {
        "cactus": {
          "command": "/Users/you/projects/cactus/server/cactus-mcp",
          "env": {
            "CACTUS_AGENT": "claude-desktop",
            "CACTUS_PROJECT": "/Users/you/projects/repo"
          }
        }
      }
    }

Use an absolute path; the desktop app does not inherit a shell `PATH`. The
plugin's `.mcp.json` registers the same server under `${CLAUDE_PLUGIN_ROOT}`
for any host that installs the plugin.

Claude Desktop can instead install the whole plugin as one file. It accepts a
`.plugin` archive: a zip with `.claude-plugin/plugin.json` at its root, plus
the skill, hooks, the server launcher, `.mcp.json` and source. It leaves
`bin/` out: Desktop refuses a plugin with a top-level `bin/`, since those
executables would join `PATH` without appearing on the admin approval
surface. The hooks exit quietly when no `cactus` is on `PATH`. Build it with

    scripts/package-plugin.sh          # writes dist/cactus-<version>.plugin

and install it from Claude Desktop under Settings > Plugins, or by dropping
the file on the window. Desktop extracts it into its local-uploads
marketplace, enables it, and starts the MCP server from `.mcp.json`; the
launcher finds a Python 3.11+ interpreter on its own, since Desktop starts
servers with the bare system `PATH`. `CACTUS_AGENT` is the `--agent` stamped on every row
the client posts, `CACTUS_PROJECT` is the project rows file under when a call
gives no `project`, and defaults to the home directory. `CACTUS_DB` is honored
the same way as at the CLI.

Tools: `cactus_ask`, `cactus_run`, `cactus_get`, `cactus_list`, `cactus_feed`,
`cactus_answer`, `cactus_edit`, `cactus_review`, `cactus_plan`,
`cactus_clear`, `cactus_reopen`, `cactus_threads`, `cactus_projects`,
`cactus_where`, `cactus_help`. Every tool takes an optional `project` (absolute
path) so one server can file rows under any repository. An MCP host cannot
hold a monitor, so a client reads answers with `cactus_get`; a `wait` there
is clamped to `CACTUS_MCP_MAX_WAIT` seconds (default 50, under a host's tool
cap) and comes back as `{"timeout": true}` rather than an error, so the
client calls again. Exit 3 comes back as `{"match": false}`.

The server appends one line per request and per verb run to `mcp.log` beside
the database (`~/.local/share/cactus/mcp.log`); `CACTUS_MCP_LOG` moves it,
`CACTUS_MCP_LOG=0` turns it off. A host shows no server stderr, so that file
is the only trace of what reached the server when a call appears to hang.

## Concepts

### Answer shapes

    choice    one label           -c a -c b
    multi     several labels      -c a -c b --multi
    confirm   yes / no            --confirm
    text      free entry          no -c

Each `-c` is one option, split on its first colon into label and description.
Free text is accepted alongside a pick unless `--no-free` is given.

### Acts

The act states what the reply is for; the shape states how it is collected.

    act      blocks by default   shape                  use
    ask      yes                 any                    a decision the agent needs
    run      yes                 confirm (approve/deny) approval to run a command
    steer    no                  choice                 what the agent will do unless redirected
    seen     no                  text                   a notice the human dismisses
    review   no                  confirm (pass/fail)    a verification block, re-checked over time
    plan     no                  text                   an ordered checklist both sides tick

`--blocked` and `--no-block` override the default on any row. `review` and
`plan` rows are persistent: they stay live until cleared and keep every verdict.

### Recommendations

`--recommend LABEL --confidence low|med|high [--why TEXT]` marks an option as
the agent's pick. The TUI shows it with ○ ◐ ● and preselects it; the row still
waits for the human. A steer's `--chosen` differs: the agent proceeds with it
and a tap redirects.

### Commands the agent cannot run

When a permission check blocks a command, the agent posts it for the human:

    cactus run "make deploy-staging" --agent ID --why "needs production credentials"

The human reviews the command in the TUI and presses `R` to run it in the
row's working directory, or `n` to deny. The exit code, the last 50 lines of
output and the path to the full log are stored on the row, and the agent reads
them with `cactus get KEY --json`.

### Elaborate and edit

`e` in the TUI asks the agent to rewrite a question, with an optional hint. The
monitor emits an `elaborate` event carrying the hint, or a default instruction
to restate the context plainly and add missing facts. The agent responds with
`cactus edit KEY --agent ID --context …`; the row returns to the inbox.
`cactus edit` also works as a plain in-place edit of an open row.

### Keys, threads and scope

Every question records its project: the git toplevel of the working
directory, or the directory itself. Agent commands see the current project;
the human surfaces see all projects. Keys number per project (`q1`, `q2`, …);
another project's row is addressed as `LABEL:qN`.

`-t THREAD` groups related questions and `-p KEY` attaches a follow-up. Thread
names are scoped to the agent that uses them.

### Ownership

A row belongs to the agent named by `--agent`. Bulk clears (`-t`, `--here`,
`--all`) require `--agent` and affect only that agent's rows; clearing or
reopening another agent's row by key is refused. After `/clear` gives an
agent a new identity, `cactus rehome --agent NEW` reassigns the rows stamped
with the same terminal pane and session.

### Decision records

Each answer, undo, verdict, elaboration and human clear rewrites
`<project>/.ai/cactus/qN-slug.md`: the question, its context and options, the
recommendation, and the answer or verdict log. The records are intended to be
committed with the work they decide. cactus writes the files and never runs
git. An agent clearing its own row does not write a record.

## Plugin hooks

    SessionStart       resolves the agent identity, rehomes rows after /clear,
                       and lists the project's open rows
    UserPromptSubmit   injects a short summary of the agent's open and
                       answered-but-unacted rows
    Stop               blocks a turn that ends without posting a question, so
                       the agent offers its next directions; turns started by
                       background events are exempt
    PermissionDenied   posts a command that auto mode denied as a `cactus run`
                       row

## Configuration

    CACTUS_DB             database path; default ~/.local/share/cactus/cactus.db
    CACTUS_POKE           override poke transport for *every* agent; {agent} and
                         {message} are substituted (tests / forced transport)
    CACTUS_POKE_WEBHOOKS  JSON map of agent id → webhook; default
                         ~/.config/cactus/poke-webhooks.json
    CACTUS_AGENT          default for --by
    CACTUS_RECORDS        0 disables decision records
    HERDR_*               workspace, tab, pane and session stamps recorded at ask time

Poke is question-level: it targets the row's `--agent`. Resolution order is
`CACTUS_POKE` (if set), else a webhook map entry for that agent id, else
`herdr agent prompt`. Webhook map entries look like:

    {
      "AGENT_ID": {
        "url": "https://example.com/wake",
        "authorization": "Bearer …"
      }
    }

The TUI's `p` binding is offered whenever the row has an agent, including
agents outside herdr. Answering a row auto-pokes when that agent is in the
webhook map; herdr/monitor agents are not auto-poked.

Full checklist, smoke test, and gotchas:
[skills/cactus/WEBHOOK_SETUP.md](skills/cactus/WEBHOOK_SETUP.md).

## Testing against cactus

Point `CACTUS_DB` at a scratch file and set `CACTUS_POKE` to an inert command
before exercising cactus from scripts; the defaults are the user's live inbox
and a live agent. An empty `CACTUS_DB` is refused rather than falling back to
the default. Scripts run from inside a repository should also set
`CACTUS_RECORDS=0`, since records are written to the row's project.

## Maintenance

    cactus migrate            report pending schema rebuilds
    cactus migrate --yes      apply them

Additive schema changes apply automatically. Rebuilds that change constraints
run only through `migrate --yes`; back up the database first and restart any
running cactus process afterwards.

## Exit status

    0   success
    1   error
    2   --wait timed out
    3   nothing matched

## License

MIT
