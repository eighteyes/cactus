# cactus pane

A live [cactus](https://github.com/eighteyes/cactus) inbox inside Claude Code. Your agent's questions show up as a pane; answer them in place.

## Needs

- The `cactus` CLI: `uv tool install git+https://github.com/eighteyes/cactus`
- Claude Code with mods (function hooks) support

## Use

- Opens at session start. `/cactus-pane` opens it again.
- A rail of open rows, a card for the focused one. Answer with the TUI's keys: digits pick, `i` types, enter sends.
- When one of the session's rows moves, the pane starts a turn carrying the answer in full and clears the row. The agent posts `cactus ask --no-wait` and keeps working.

## What it runs and sends

Everything stays on your machine. The pane talks to nothing over the network.

Programs it runs (`process.run`), each with a fixed program name:

- `cactus`: the local CLI, in the session's project directory (`session.cwd`). `feed --json --here` every few seconds to draw the pane; `answer`, `undo`, `elaborate`, `clear`, `get`, `plan`, `review` when you press a key. `exec` runs the command a run or review row carries, only when you press `r` on that row.
- `git diff HEAD -- FILE` and `head -n 40 FILE`: the `o` preview of a file attached to a row.
- `open FILE`: the `f` key, opens an attached file in your default app (macOS).

Prompts it submits (`prompt.submit`): when one of this session's own rows is answered, it submits one prompt to this session holding each moved row's key, its question's first line and your answer, so the agent can act on it. Nothing else goes in.

Hooks that change what passes through:

- `tool.call` on Bash: adds `--no-wait` to a `cactus ask --no-wait` or `cactus run --no-wait` command the agent writes, so the agent never blocks waiting for you; the pane wakes it instead. No other command is touched.
- `prompt.compose`: adds one section to the system prompt describing the cactus workflow in mod mode.
- `command.run` / `command.register`: the `/cactus-pane` command that reopens the pane.

## License

MIT
