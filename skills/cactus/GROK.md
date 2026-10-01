# Cactus on Grok

Grok has no herdr pane to prompt and cannot rely on a local
`cactus --monitor --once` process to re-enter the chat. Use a stable external
agent id and configure Cactus to wake that id through a webhook.

1. Use the same stable id on every `cactus ask --agent ID` and `cactus clear`.
2. Configure the bot's wake routine to run `cactus feed --json --agent ID`,
   act on answered or elaboration rows, clear rows once acted on, and report
   the result in chat.
3. Add that id, webhook URL, and authorization to the per-agent webhook map.
4. Answer a smoke-test row in `cactus --tui`; mapped agents are auto-poked.

Read [WEBHOOK_SETUP.md](WEBHOOK_SETUP.md) for the exact map schema, security
requirements, and round-trip smoke test. There is no Cactus Grok catalog
plugin; install this skill into the shared Grok skill library.
