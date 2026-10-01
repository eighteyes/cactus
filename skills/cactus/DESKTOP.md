# Cactus on Claude Desktop and other MCP hosts

A chat host is a poor fit for cactus because it has no herdr pane, no
webhook and no background command: nothing can wake the agent when the human
answers, so an answer is only ever found by polling. Chat turns also carry few decisions, and the human is already
present, so most questions belong in the reply, not on the board. Post a
row only when the decision outlives the conversation: a verify block, a
plan, a command that needs approval, or a fork another agent or a later
session will act on. Reading the board is the common case here, not
writing to it.

On an MCP host the cactus verbs are tools, not shell commands. Every verb in
[SKILL.md](SKILL.md) maps to one tool with the same name and flags spelled as
arguments:

    cactus ask ...      cactus_ask       cactus review ...   cactus_review
    cactus run ...      cactus_run       cactus plan ...     cactus_plan
    cactus get ...      cactus_get       cactus clear ...    cactus_clear
    cactus list ...     cactus_list      cactus reopen ...   cactus_reopen
    cactus feed ...     cactus_feed      cactus edit ...     cactus_edit
    cactus answer ...   cactus_answer    cactus --agent-help cactus_help

Do not run `cactus` in a shell here, and never start `cactus --monitor`: it
is a foreground stream that only returns when killed, and a host with no
background command will sit on it forever.

## Identity

The server stamps every row with `CACTUS_AGENT` from its config, so `agent`
is optional on every tool. Pass it only to act as a different owner.

## Project

The server has no working directory of yours. Pass `project` (the absolute
path of the repository) on every call that concerns one; rows without it
file under the server's `CACTUS_PROJECT`, else the home directory. Keys are
`qN` within a project, so `cactus_get` needs the same `project` the row was
posted under, or the row's `ref` (`LABEL:qN`) which works from anywhere.

## Workflow

    1  ask       cactus_ask for every decision; choices one per direction,
                 recommend with confidence when you have a pick
    2  work      everything the answer does not block
    3  collect   cactus_get with wait=true when you reach the fork; a
                 {"timeout": true} result means call it again
    4  clear     cactus_clear on your own keys once acted on

Nothing wakes this host. Answers arrive when you read them, so read
at the fork, not before. `cactus_feed` returns the whole actionable inbox in
one call when you need the board rather than one row.

`wait` is clamped to 50 seconds by the server so a call never outlives the
host's tool cap. A long wait is a loop: call, read `timeout`, call again,
and do other work between calls.

## Commands that need approval

Post them with `cactus_run`. Read the row back with `cactus_get` before doing
anything: `result` non-null means the human already ran it from the TUI;
null after `approve` means run it yourself, if the host gives you a shell.

## Elaborate

No wake delivers an `elaborate` request here. A row in status
`elaborate` shows up in `cactus_get` and `cactus_feed` with the human's hint
under `elaborate`; rewrite it with `cactus_edit` and it returns to `open`.
