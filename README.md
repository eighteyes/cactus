# cactus

"All the spines without the ouch"

**Ask the human without stopping work.** An agent posts a question, gets a key,
and keeps going; the human answers from a terminal UI on their own schedule;
the agent collects the answer at the step that needs it.

Questions persist in SQLite: they outlive the session and stay readable by the
next agent in the same repository. Block only when no default is safe.

## Install

    uv tool install git+https://github.com/eighteyes/cactus

Python 3.11+. Installs `cactus` and the alias `cac`. From a checkout:

    uv tool install --editable .
    PYTHONPATH=src python3 -m cactus --help

### Claude Code plugin

    /plugin marketplace add eighteyes/cactus
    /plugin install cactus@cactus

Adds a skill that teaches the workflow, a courier agent that waits on answers,
the [hooks](#plugin-hooks), and a `cactus` launcher on `PATH`. Agent commands
need only `python3` 3.11+. `--tui` and `--watch` need textual: the launcher
uses it when installed, else runs through `uv` with textual added, else prints
the install command.

Keep a `uv`-installed cactus and the plugin's copy at the same version; both
read one database.

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

The TUI marks `oidc` as recommended and preselects it. On the answer the
monitor prints `q7  answered  [oidc]`; read the rest with `cactus get q7 --json`.

Full agent reference: `cactus --agent-help`.

## Agent workflow

1. Start `cactus --monitor --agent ID` before the first question; keep it
   running while any of your rows are open
2. Post every decision the human makes with `cactus ask … --agent ID`; add
   `--recommend` and `--confidence` when you have a pick
3. Work on whatever the answer does not block; act on each event as it lands
4. Retire acted-on rows with `cactus clear KEY --agent ID`

`--agent` is required on `ask` and `--monitor`. Use the session identity, not a
terminal pane id: a pane id outlives the conversation that used it.

When a tool's time cap ends the foreground monitor and the human is away, run
`cactus --monitor --agent ID --once` in the background; it exits on the first
event other than `asked`.

## Human surfaces

    cactus --tui       answer the inbox
    cactus --watch     read-only live feed
    cactus --www       localhost web answering surface; no textual needed

All span every project; `--here` limits them to the current one.

TUI keys:

    j / k        move between questions
    1-9          pick or toggle an option; tick a plan step
    enter        submit; a recommended option is preselected
    y / n        answer a confirm row
    i            type free text
    e            ask the agent to elaborate, optional hint
    s            skip: answered, no decision
    c            clear: retired, unanswered
    u            undo, back through the session's actions
    R  C  O      run a row's command, copy it, open its full output
    d            dismiss a notice
    p            poke the row's agent
    [ / ]        switch project
    q            quit

A click moves the highlight; only a key submits.

## MCP server

**`server/cactus-mcp` exposes the agent verbs to any MCP client over stdio.**
It runs from the checkout or the installed plugin with `python3` and the
standard library alone. Each tool runs one `cactus` verb with `--json`, so
validation, ownership and exit codes are the CLI's.

Claude Desktop, in `claude_desktop_config.json`:

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
plugin's `.mcp.json` registers the same server under `${CLAUDE_PLUGIN_ROOT}`.

    CACTUS_AGENT     the --agent stamped on every row the client posts
    CACTUS_PROJECT   project for calls that pass no `project`; default $HOME
    CACTUS_DB        as at the CLI

Tools: `cactus_ask`, `cactus_run`, `cactus_get`, `cactus_list`, `cactus_feed`,
`cactus_answer`, `cactus_edit`, `cactus_review`, `cactus_plan`,
`cactus_clear`, `cactus_reopen`, `cactus_threads`, `cactus_projects`,
`cactus_where`, `cactus_help`. Each takes an optional absolute `project`, so
one server files rows under any repository.

An MCP host cannot hold a monitor: poll with `cactus_get`. Its `wait` is
clamped to `CACTUS_MCP_MAX_WAIT` seconds (default 50, under a host's tool cap)
and returns `{"timeout": true}`; call again. Exit 3 returns `{"match": false}`.

The server logs one line per request and per verb to `mcp.log` beside the
database. `CACTUS_MCP_LOG` moves it; `CACTUS_MCP_LOG=0` disables it. A host
shows no server stderr, so read this file when a call appears to hang.

### Claude Desktop plugin file

    scripts/package-plugin.sh          # writes dist/cactus-<version>.plugin

Install from Settings > Plugins, or drop the file on the window. Desktop
extracts it, enables it, and starts the MCP server from `.mcp.json`; the
launcher finds a Python 3.11+ on its own, since Desktop starts servers with the
bare system `PATH`.

The archive leaves out `bin/`: Desktop refuses a plugin with a top-level
`bin/`, whose executables would join `PATH` without passing admin approval.
The hooks exit quietly when no `cactus` is on `PATH`.

## Other agents: Codex, Grok, Gemini

**Any agent with a shell uses the CLI; any MCP client uses the server.** The
skill and hooks are Claude Code only, so teach the workflow through the
instruction file these agents read: `AGENTS.md` at the repository root
(Codex, Grok and Gemini all load it).

    ## cactus
    Every decision the human makes goes to cactus, not chat.
    - Identity: choose one --agent value for this session; pass it on every call
    - Ask: cactus ask "…" --agent ID -c "a: …" -c "b: …" --context "…"
      add --recommend a --confidence med when you have a pick
    - Collect: cactus get KEY --json at the step that needs the answer;
      cactus get KEY --wait --timeout 50 only when blocked
    - Blocked by a permission prompt: cactus run "CMD" --agent ID
    - Clear acted-on rows: cactus clear KEY --agent ID
    - Reference: cactus --agent-help

**Identity.** These agents have no Claude session id; choose a stable value per
session, such as `codex-<repo>-<date>`. A new value strands earlier rows;
`cactus rehome` recovers them only inside herdr, where rows carry pane and
session stamps.

**Waiting.** Only an agent that can hold a background process and be woken on
its exit keeps a monitor: run `cactus --monitor --agent ID --once` in the
background (Grok documents this). Otherwise poll with `cactus get` or
`cactus list -s answered --agent ID` between steps, and keep each `--wait`
under the agent's command timeout.

**MCP.** Point the client at `server/cactus-mcp` by absolute path, with
`CACTUS_AGENT` and `CACTUS_PROJECT` in its environment:

    Codex    ~/.codex/config.toml, or: codex mcp add
             [mcp_servers.cactus]
             command = "/abs/path/cactus/server/cactus-mcp"
             env = { CACTUS_AGENT = "codex", CACTUS_PROJECT = "/abs/path/repo" }
    Gemini   ~/.gemini/settings.json, "mcpServers" — same shape as the
             Claude Desktop block above
    Grok     grok mcp add, or .grok/config.toml; Grok also imports .mcp.json

Keep `CACTUS_MCP_MAX_WAIT` below the client's tool timeout.

## Concepts

### Answer shapes

    choice    one label          -c a -c b
    multi     several labels     -c a -c b --multi
    confirm   yes / no           --confirm
    text      free entry         no -c

One `-c` per option, split on the first colon into label and description.
Free text rides alongside a pick unless `--no-free`.

### Acts

**The act is what the reply is for; the shape is how it is collected.**

    act      blocks   shape                   use
    ask      yes      any                     a decision the agent needs
    run      yes      confirm: approve/deny   approval to run a command
    steer    no       choice                  what the agent does unless redirected
    seen     no       text                    a notice the human dismisses
    review   no       confirm: pass/fail      a verify block, re-checked over time
    plan     no       text                    a checklist both sides tick

`--blocked` / `--no-block` override the default on any row. `review` and `plan`
stay live until cleared and keep every verdict.

### Recommendations

**A recommendation waits; a steer proceeds.** `--recommend LABEL --confidence
low|med|high [--why TEXT]` marks the agent's pick, shown ○ ◐ ● and preselected
in the TUI; the row still waits for the human. A steer's `--chosen` is what the
agent does unless a tap redirects it.

### Blocked commands

**When a permission check blocks a command, post it to the human:**

    cactus run "make deploy-staging" --agent ID --why "needs production credentials"

`R` in the TUI runs it in the row's working directory; `n` denies. The row
stores the exit code, the last 50 lines of output and the full log's path; read
them with `cactus get KEY --json`.

### Elaborate and edit

`e` in the TUI asks the agent to rewrite a question, optionally with a hint.
The monitor emits `elaborate` with the hint, or a default instruction: restate
the context plainly and add what is missing. Answer with
`cactus edit KEY --agent ID --context …`; the row returns to the inbox.
`cactus edit` also edits any open row in place.

### Keys, threads and scope

A question files under its project: the git toplevel of its working directory,
else the directory. Agent commands see the current project; human surfaces see
all.

    q7                  key in the current project
    LABEL:q7            key in another project
    -t THREAD           group related questions; names are per agent
    -p KEY              attach a follow-up

### Ownership

**An agent clears only its own rows.** Bulk clears (`-t`, `--here`, `--all`)
require `--agent` and touch only that agent's rows; clearing or reopening
another agent's row by key is refused. After `/clear` assigns a new identity,
`cactus rehome --agent NEW` reclaims the rows stamped with the same pane and
session.

### Decision records

**Every human decision lands in `<project>/.ai/cactus/qN-slug.md`**: question,
context, options, recommendation, and the answer or verdict log, rewritten on
each answer, undo, verdict, elaboration and human clear. Commit the records
with the work they decide; cactus never runs git. An agent clearing its own
row writes none.

## Plugin hooks

    SessionStart       resolve identity; rehome rows after /clear; when no
                       monitor runs, open with a ready-to-run Monitor command;
                       list the project's open rows
    UserPromptSubmit   inject the agent's open and answered-but-unacted rows;
                       name the Monitor command when rows are open and no
                       monitor runs
    Stop               hold a turn that ends with open rows and no monitor;
                       hold a turn that ends without posting a question, so
                       the agent offers its next directions; turns opened by
                       background events are exempt from the second rule
    PermissionDenied   post a command auto mode denied as a `cactus run` row

## Configuration

    CACTUS_DB             database; default ~/.local/share/cactus/cactus.db
    CACTUS_POKE           poke transport for every agent; {agent} and
                          {message} substituted; tests and forced transport
    CACTUS_POKE_WEBHOOKS  JSON map of agent id → webhook; default
                          ~/.config/cactus/poke-webhooks.json
    CACTUS_AGENT          default --by
    CACTUS_RECORDS        0 disables decision records
    HERDR_*               workspace, tab, pane and session stamped at ask

**A poke targets the row's `--agent`.** Resolution: `CACTUS_POKE` when set,
else the agent's webhook map entry, else `herdr agent prompt`. A map entry:

    {
      "AGENT_ID": {
        "url": "https://example.com/wake",
        "authorization": "Bearer …"
      }
    }

The TUI offers `p` on any row with an agent. Answering a row auto-pokes agents
in the webhook map; herdr and monitor agents are not auto-poked. Checklist,
smoke test and gotchas:
[skills/cactus/WEBHOOK_SETUP.md](skills/cactus/WEBHOOK_SETUP.md).

## Testing against cactus

**Set `CACTUS_DB` to a scratch file and `CACTUS_POKE` to an inert command before
scripting cactus.** The defaults are the user's live inbox and a live agent; an
empty `CACTUS_DB` is refused. Set `CACTUS_RECORDS=0` in scripts run inside a
repository: records write to the row's project.

## Maintenance

    cactus migrate            report pending schema rebuilds
    cactus migrate --yes      apply them

Additive changes apply on open. Constraint rebuilds run only through
`migrate --yes`: back up the database first, restart every running cactus
process after.

## Exit status

    0   success
    1   error
    2   --wait timed out
    3   nothing matched

## License

MIT
