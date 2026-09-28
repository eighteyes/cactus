# cactus-channel — tasks

- [ ] Probe: throwaway channel server emits one notification after 20 min; does an idle session wake?
- [ ] Probe: `/clear` with a registered channel; queue and registration after.
- [ ] Probe: compaction with queued events.
- [ ] `src/cactus/channel.py`: event loop over `monitor` diff, one notification per event.
- [ ] `mcp.py`: capability flag, background channel thread, agent id from env.
- [ ] `plugins/cactus/.mcp.json`: `cactus-channel` entry.
- [ ] `hooks/session-start.sh`: detect channel, skip the once-loop instruction.
- [ ] `skills/cactus/CLAUDE.md`: channel recipe, once-loop as fallback.
- [ ] herdr pane recipe: `--channels` flag.
- [ ] tests/test_channel.py: notification shape, own-echo filter, agent id.
