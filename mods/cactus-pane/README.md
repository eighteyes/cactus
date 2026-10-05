# cactus pane

A live [cactus](https://github.com/eighteyes/cactus) inbox inside Claude Code. Your agent's questions show up as a pane; answer them in place.

## Needs

- The `cactus` CLI: `uv tool install git+https://github.com/eighteyes/cactus`
- Claude Code with mods (function hooks) support

## Use

- Opens at session start. `/cactus-pane` opens it again.
- A rail of open rows, a card for the focused one. Answer with the TUI's keys: digits pick, `i` types, enter sends.
- When one of the session's rows moves, the pane starts a turn carrying the answer in full and clears the row. The agent posts `cactus ask --no-wait` and keeps working.

## Runs locally

The pane shells out to the local `cactus` CLI and reads its SQLite inbox. Nothing leaves the machine.

## License

MIT
