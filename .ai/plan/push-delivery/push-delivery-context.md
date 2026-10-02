# context
- src/cactus/poke.py: DEFAULT_WEBHOOKS_PATH, poke_webhook_if_mapped, poke, reachable
- callers of poke_webhook_if_mapped: cli.cmd_answer, cli.cmd_exec, www, tui._auto_poke_webhook
- plugins/cactus/hooks/ (Codex session-start), skills/cactus/WEBHOOK_SETUP.md, CODEX.md
- decisions: q430 (wait-only, herdr not auto-poked), q462 (client owns delivery), q464, q477 push, q481/q483 approved
