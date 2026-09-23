# Elaborate tasks

- [x] q211: verb is `edit`; mechanism proceeds as `status` under steer (veto redirects)
- [x] q207 default instruction answered: `both`
- [x] store: columns, status, `Store.elaborate_request`, `Store.edit`, `Store.unelaborate` (42181f0)
- [x] cli: `cactus edit` verb, `--agent-help` line (42181f0)
- [x] tui: `e` binding, `elaborate:` input mode, marker, undo (b67aa44)
- [x] monitor: `elaborate` event with `hint` and `instruction`, `edited` (d0c298f)
- [x] record: rewrite section (49d6cfc)
- [x] hooks/frontier.sh: `elaborate` rows first with hint, counts line names the verb
- [x] skills/cactus/SKILL.md and session-start: elaborate event and `cactus edit`

Known ambiguity: a human `u` withdrawing an elaborate request reads as
`edited` on the monitor. The skill says re-read the row before rewriting.
