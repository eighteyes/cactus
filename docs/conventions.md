# Conventions

House rules collected from the code. Collection only: nothing here is enforced by lint or CI.

Machine copy: .ai/conventions.json (generated from 32fecc9). The two files agree.

Tiers: no enforced tier (no linter, formatter, type-checker or CI config). No declared tier (no `CONVENTION:` markers). Every rule below is observed: 3+ conforming sites, at most 1 exception.

**module-header-responsibilities**

Open every Python module and root hook script with a header naming the file, a one-line description, and a Responsibilities list.

- tier: observed
- scope: `src/cactus/*.py`, `hooks/*.sh`, `tests/conftest.py`
- exemplar: src/cactus/poke.py:1
- exceptions: src/cactus/acp.py (docstring has no name line or Responsibilities list)

**sqlite-only-in-store**

Import sqlite3 and run SQL only in store.py; every other module goes through Store methods.

- tier: observed
- scope: `src/cactus/*.py`
- exemplar: src/cactus/store.py:19

**store-read-then-write-begin-immediate**

Wrap a Store write that reads then writes, or makes several writes, in an explicit BEGIN IMMEDIATE on the autocommit connection.

- tier: observed
- scope: `src/cactus/store.py`
- exemplar: src/cactus/store.py:897

**schema-additive-on-open**

Change the schema on open with ALTER TABLE ADD COLUMN only; put any table rebuild behind needs_* checks and `cactus migrate --yes` / CACTUS_MIGRATE=1.

- tier: observed
- scope: `src/cactus/store.py`
- exemplar: src/cactus/store.py:498

**cli-exit-constants**

Return EXIT_OK/EXIT_ERROR/EXIT_TIMEOUT/EXIT_EMPTY (0/1/2/3) from cmd_* functions, never bare integer literals.

- tier: observed
- scope: `src/cactus/cli.py`
- exemplar: src/cactus/cli.py:302

**cli-stderr-one-line**

Report a CLI refusal or failure as one stderr line prefixed `cactus: `, routing exception text through _msg(exc).

- tier: observed
- scope: `src/cactus/cli.py`
- exemplar: src/cactus/cli.py:749

**cli-gates-ownership**

Check row ownership in cli.py (_refuse_if_not_owner and cmd_* gates); Store methods take at most an agent filter and never refuse on ownership.

- tier: observed
- scope: `src/cactus/cli.py`, `src/cactus/store.py`
- exemplar: src/cactus/cli.py:1000

**lazy-side-leaf-imports**

Import poke, shell, and the Textual/web surfaces (tui, watch, www, monitor) inside the function that uses them, not at module top.

- tier: observed
- scope: `src/cactus/cli.py`, `src/cactus/tui.py`
- exemplar: src/cactus/cli.py:743
- exceptions: src/cactus/www.py:26 imports poke at top level (outside scope)

**delivery-fails-soft-after-answer**

Deliver/poke after a saved answer inside try/except PokeError and report the failure without undoing the answer.

- tier: observed
- scope: `src/cactus/cli.py`, `src/cactus/tui.py`, `src/cactus/www.py`
- exemplar: src/cactus/cli.py:748

**tests-isolated-via-conftest**

Run tests against conftest's scratch CACTUS_DB, inert CACTUS_POKE, and records/rank/decide off, using the store/project/cli fixtures.

- tier: observed
- scope: `tests/**/*.py`
- exemplar: tests/test_deliver.py:45

**Conflicts**

None.

**Observed but unconfirmed**

NOT BINDING. Below the evidence bar; a reviewer does not enforce these.

*atomic-shared-file-writes*

Write files other processes read with a same-directory temp file then os.replace.

- scope: `src/cactus/*.py`
- exemplar: src/cactus/poke.py:143
- below bar: 3 conforming sites (poke.py:143, garden.py:75, record.py:310) but 2+ exceptions: tui.py:131 tui.json and sky.py:588 sky.toml write in place

*renamed-api-keeps-alias*

Keep a back-compat alias when renaming a public function.

- scope: `src/cactus/*.py`
- exemplar: src/cactus/poke.py:183
- below bar: 1 site (poke_webhook_if_mapped = deliver_if_mapped)

*xfail-not-delete*

Mark a bug-exposing test xfail with its reason; never delete it.

- scope: `tests/**/*.py`
- exemplar: tests/test_field.py:677
- below bar: 1 xfail site in tests; stated in CLAUDE.md, not a CONVENTION: marker

*one-test-file-per-module*

Keep one tests/test_<module>.py per src module.

- scope: `tests/*.py`
- exemplar: tests/test_poke.py:1
- below bar: exceptions exceed 1: test_deliver.py, test_puffs.py, test_hooks.py do not map one-to-one to modules

*cite-row-key-in-comments*

Cite the deciding cactus row key (qNNN) in comments that explain a design choice.

- scope: `src/cactus/*.py`, `hooks/*.sh`
- exemplar: hooks/stop_fork.py (header block)
- below bar: widespread (94 hits across src/cactus/*.py and hooks/*.sh) but a citation habit, not checkable behavior

*from-future-annotations*

Import `from __future__ import annotations` in every module after the header.

- scope: `src/cactus/*.py`
- exemplar: src/cactus/store.py:14
- below bar: 2 exceptions: src/cactus/__init__.py and src/cactus/__main__.py lack it; style, not behavior

*env-override-external-commands*

Give every external command a CACTUS_* env override holding a template with {placeholder} substitution, falling back to the built-in default.

- scope: `src/cactus/poke.py`, `src/cactus/shell.py`, `src/cactus/cli.py`
- exemplar: src/cactus/poke.py:193
- below bar: 2 exceptions: src/cactus/shell.py:30 clipboard copy (pbcopy/wl-copy/xclip/xsel) and src/cactus/shell.py:204 `_vcs` (git) have no override

*hook-stdin-first-and-gates*

Read stdin into $input, exit 0 silently when cactus or jq is missing, and exit 0 when `cactus project-status --json` reports the project disabled.

- scope: `hooks/*.sh`, `plugins/cactus/hooks/*.sh`
- exemplar: plugins/cactus/hooks/stop.sh:6
- below bar: 4 exceptions: hooks/cactus_identity.py (imported helper module); hooks/pretooluse_wait.py (no `command -v cactus` check, no project-status gate); hooks/session_start.py and hooks/stop_fork.py (no jq)
