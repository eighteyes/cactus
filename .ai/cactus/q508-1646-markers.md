# q508 — Plant which CONVENTION: markers? (collected, never enforced)

status: answered
act: ask
kind: multi
thread: docs
agent: 0f4be69e-67e5-485b-a467-0d31810683ad
cwd: .
asked at: 2026-10-03T05:16:48.242092+00:00

## Context

Each becomes a one-line source comment at that site. Code review loads them
as highest-trust precedent. Rules live in .ai/conventions.json either way.

## Options

- sql — store.py:19 only store.py imports sqlite3 or runs SQL
- migrate — store.py:489 _migrate adds columns only; rebuilds behind migrate --yes
- exit — cli.py:30 cmd_* return these constants; 2 is --wait timeout
- owner — cli.py:968 ownership gated in cli.py; Store stays mechanism
- replace — poke.py:125 shared config files written temp-then-os.replace
- stdin — plugins/cactus/hooks/stop.sh:6 read stdin into $input first; exit 0 when cactus/jq missing

## Answer

owner, replace, stdin
answered at: 2026-10-03T07:04:55.810582+00:00
