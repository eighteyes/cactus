"""
cli.py — command-line surface for cactus, covering both the agent and human modes.

Responsibilities:
- Parse the agent-facing verbs (ask, get, list, answer, clear, purge, threads, projects).
- Resolve project scope from the working directory for every invocation.
- Render results as human text or JSON, and implement --wait blocking.
- Dispatch the human-facing --tui and --watch modes, and the agent --monitor stream.
- Serve the agent roadmap behind --agent-help.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Sequence

from .scope import project_display, resolve_project
from .store import (ACTS, ACT_SHAPES, CONFIDENCE, CONFIDENCE_GLYPH,
                    DEFAULT_BLOCKED, AlreadyAnswered, Choice,
                    Question, Store, default_db_path)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_TIMEOUT = 2
EXIT_EMPTY = 3

AGENT_HELP = """\
NAME
  cactus — durable question inbox between agents and a human

WORKFLOW (required)
  1  cactus --monitor --agent ID      background, before the first ask
  2  cactus ask ... --agent ID        every decision, not chat
  3  work; act on each event
  4  cactus clear KEY --agent ID      own rows only

SYNOPSIS
  cactus ask TEXT --agent ID [-c LABEL[: DESC]]... [options]
  cactus get KEY... [-w] [--timeout S]
  cactus list [-s STATUS] [-t THREAD] [--act A] [--agent ID] [SCOPE]
  cactus review KEY [--look-at X] [--run CMD] [--pass X] [--fail X] [--then X]
  cactus plan KEY [--step TEXT]... [--reset-steps] [--done N] [--undone N]
  cactus answer KEY [TEXT] [-s LABEL]... [--skip | --dismiss]
  cactus clear KEY... | -t THREAD | --here | --all  [--purge] --agent ID
  cactus reopen KEY... --agent ID
  cactus poke KEY | --agent ID
  cactus feed --json [--act A] [--agent ID] [SCOPE] [-t T] [-s S] [--here]
  cactus --monitor [--agent ID] [SCOPE] [--all] [--json] [--replay]
                   [--interval N]
  cactus where | projects | threads

  SCOPE  --workspace ID | --tab ID | --pane ID

ACTS
  act      blocks   shape
  ask      yes      choice | multi | text | confirm
  run      yes      confirm   approve / deny
  steer    no       choice    --chosen required
  seen     no       text
  review   no       confirm   pass / fail; persistent
  plan     no       text      persistent; steps 1-based

ASK OPTIONS
  -c LABEL[: DESC]           one choice, verbatim; repeat
  --multi | --confirm        shape; text when no -c
  --act ACT                  default ask
  --agent ID                 required; session token, not pane id
  --recommend LABEL          repeat on multi
  --confidence low|med|high  required with --recommend
  --why TEXT
  --chosen LABEL             steer only
  --blocked | --no-block
  --context TEXT | -
  --no-free
  -t THREAD | -p KEY
  --word SHORT               board key; 16 chars max
  --title TEXT               button label; 60 chars max
  --by NAME                  default $CACTUS_AGENT
  --wait --timeout S

STAMPS
  workspace tab pane session   from HERDR_WORKSPACE_ID HERDR_TAB_ID
                                     HERDR_PANE_ID HERDR_SESSION at ask

EVENTS
  asked  answered  skipped  cleared  reopened  verdict  stepped  gone

EXIT STATUS
  0 ok   1 error   2 --wait timeout   3 no match

FILES
  .ai/cactus/qN-SLUG.md   decision record, rewritten on each answer, undo,
                          verdict, clear; commit it

ENVIRONMENT
  CACTUS_DB       database path
  CACTUS_POKE     poke transport; {agent} {message}. Default prompts a live agent
  CACTUS_AGENT    default --by
  CACTUS_RECORDS  0 disables records
  HERDR_*         scope stamps; see STAMPS
"""


# ---- rendering ------------------------------------------------------------


def _fmt_answer(q: Question) -> str:
    if q.status == "cleared":
        return "(cleared)"
    if q.answer is None:
        return ""
    if q.answer.skipped:
        return "(skipped)"
    parts = []
    if q.answer.selected:
        parts.append(", ".join(q.answer.selected))
    if q.answer.text:
        parts.append(q.answer.text)
    return " — ".join(parts) if parts else "(empty)"


def _print_questions(questions: Sequence[Question], *, as_json: bool, show_project: bool) -> None:
    if as_json:
        json.dump([q.as_dict() for q in questions], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    for q in questions:
        indent = "  " * getattr(q, "depth", 0)
        head = f"{q.key}\t{q.status}\t"
        if show_project:
            head += f"[{project_display(q.project)}]\t"
        if q.thread:
            head += f"({q.thread})\t"
        print(f"{head}{indent}{q.text}")
        if q.choices and q.status == "open":
            labels = " | ".join(c.label for c in q.choices)
            print(f"\t\t{indent}  choices: {labels}")
        if q.recommend:
            glyph = CONFIDENCE_GLYPH.get(q.confidence, "")
            why = f" — {q.recommend_why}" if q.recommend_why else ""
            print(f"\t\t{indent}  recommend: {', '.join(q.recommend)} {glyph} {q.confidence}{why}")
        ans = _fmt_answer(q)
        if ans:
            print(f"\t\t{indent}  -> {ans}")


def _emit_one(q: Question, *, as_json: bool) -> None:
    if as_json:
        json.dump(q.as_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_questions([q], as_json=False, show_project=False)


# ---- verbs ----------------------------------------------------------------


def cmd_ask(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    # Each -c is exactly one choice, taken verbatim. Splitting on commas here
    # would silently shred any description that contains one.
    choices = [Choice.parse(raw.strip()) for raw in (args.choice or []) if raw.strip()]

    act = args.act
    if choices and ACT_SHAPES[act] == ("text",):
        # seen and plan collect text only; silently forcing kind="text" below
        # would strand the -c choices on a row that never reads them.
        print(f"cactus: --act {act} takes no choices; it collects text only", file=sys.stderr)
        return EXIT_ERROR
    kind = args.kind
    if kind is None:
        if args.confirm:
            kind = "confirm"
        elif choices and args.multi:
            kind = "multi"
        elif choices:
            kind = "choice"
        else:
            kind = "text"
        # An act with one legal shape picks it, so `--act run` alone is enough.
        if kind not in ACT_SHAPES[act] and len(ACT_SHAPES[act]) == 1:
            kind = ACT_SHAPES[act][0]

    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    if not text:
        print("cactus: refusing to ask an empty question", file=sys.stderr)
        return EXIT_ERROR

    context = args.context
    if context == "-":
        context = sys.stdin.read()

    # Resolve whether this row will block, the same way Store.ask defaults
    # it, so --wait on a row that will not block is refused before the row
    # is ever inserted — no orphan row left behind by a rejected --wait.
    would_block = args.blocked
    if would_block is None:
        would_block = DEFAULT_BLOCKED.get(act, True)
    if args.wait and not would_block:
        print(
            f"cactus: --wait needs a blocking row; this one would be posted "
            f"with blocked=false — drop --wait or pass --blocked",
            file=sys.stderr,
        )
        return EXIT_ERROR

    # Required, not defaulted. A pane id is not an identity: herdr's own
    # resolver treats `session:pane_id` as the last-resort fallback precisely
    # because it never changes, so it outlives the conversation it named.
    # Defaulting to $HERDR_PANE_ID would address a row to whatever
    # conversation later occupies that pane. The writer is inside the pane
    # and knows its resolved id, so it states it explicitly every time.
    if not (args.agent or "").strip():
        print(
            "cactus: ask needs --agent ID, the declared session identity — "
            "never a pane id",
            file=sys.stderr,
        )
        return EXIT_ERROR

    # Scope stamps, not arguments: herdr resolves a pane to an identity only
    # in the context of its session, so pane and session are stamped together
    # from the environment the writer is actually running in. These are what
    # let a projector scope a row and what a re-home path uses to find a row
    # whose agent no longer exists (a session token rotates on `claude --resume`).
    workspace = os.environ.get("HERDR_WORKSPACE_ID") or None
    tab = os.environ.get("HERDR_TAB_ID") or None
    pane = os.environ.get("HERDR_PANE_ID") or None
    session = os.environ.get("HERDR_SESSION") or None

    try:
        q = store.ask(
            text,
            project=project,
            cwd=cwd,
            kind=kind,
            act=act,
            agent=args.agent or None,
            word=args.word,
            workspace=workspace,
            tab=tab,
            pane=pane,
            session=session,
            title=args.title,
            chosen=args.chosen,
            blocked=args.blocked,
            choices=choices,
            allow_free=not args.no_free,
            recommend=args.recommend,
            confidence=args.confidence,
            recommend_why=args.why,
            thread=args.thread,
            parent_key=args.parent,
            context=context,
            asked_by=args.by or os.environ.get("CACTUS_AGENT"),
        )
    except (KeyError, ValueError) as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not args.wait:
        if args.json:
            _emit_one(q, as_json=True)
        else:
            print(q.key)
        return EXIT_OK

    answered = store.wait_for_answer(q.key, timeout=args.timeout)
    if answered is None:
        if args.json:
            json.dump({"key": q.key, "status": "timeout"}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"cactus: timed out waiting for {q.key}", file=sys.stderr)
        return EXIT_TIMEOUT
    _emit_one(answered, as_json=args.json)
    return EXIT_OK


def cmd_get(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    for key in args.keys:
        if store.get(key) is None:
            print(f"cactus: no such question: {key}", file=sys.stderr)
            return EXIT_EMPTY

    if args.wait:
        timed_out_key = None
        for key in args.keys:
            if store.wait_for_answer(key, timeout=args.timeout) is None:
                timed_out_key = key
                break
        if timed_out_key is not None:
            # Print whatever already resolved before the miss, so a caller
            # waiting on several keys is not left with nothing at all.
            settled = [q for q in (store.get(k) for k in args.keys) if q is not None and q.status != "open"]
            if settled:
                _print_questions(settled, as_json=args.json, show_project=args.all)
            if not args.json:
                print(f"cactus: timed out waiting for {timed_out_key}", file=sys.stderr)
            return EXIT_TIMEOUT

    found: list[Question] = []
    for key in args.keys:
        q = store.get(key)
        assert q is not None
        found.append(q)

    if args.answered_only:
        found = [q for q in found if q.status == "answered"]
        if not found:
            return EXIT_EMPTY

    _print_questions(found, as_json=args.json, show_project=args.all)
    return EXIT_OK


def cmd_list(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    status: Any = None if args.status == "any" else args.status
    questions = store.tree(
        project=project,
        thread=args.thread,
        status=status,
        all_projects=args.all,
        acts=args.act,
        agent=args.agent,
        workspace=args.workspace,
        tab=args.tab,
        pane=args.pane,
    )
    if not questions:
        if args.json:
            print("[]")
        return EXIT_EMPTY
    _print_questions(questions, as_json=args.json, show_project=args.all)
    return EXIT_OK


def cmd_answer(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    try:
        q = store.answer(
            args.key,
            selected=args.select or [],
            text=text,
            skipped=args.skip or args.dismiss,
        )
    except AlreadyAnswered as exc:
        # Exit 3, not 1: a projector renders this as a stale cell rather than
        # an error, because nothing went wrong — it was simply beaten to it.
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_EMPTY
    except KeyError as exc:
        # No such question: exit 3, the same as every other verb that takes
        # a key — a missing row is a miss, not a malformed call.
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    _emit_one(q, as_json=args.json)
    return EXIT_OK


def cmd_review(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Attach or replace the verify block on a review row."""
    try:
        q = store.set_review(
            args.key,
            look_at=args.look_at,
            run_cmd=args.run,
            pass_when=getattr(args, "pass"),
            fail_when=args.fail,
            then_do=args.then,
        )
    except KeyError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    _emit_one(q, as_json=args.json)
    return EXIT_OK


def _plan_index(n: int, count: int) -> int:
    """Convert a 1-based CLI step number to the store's 0-based idx."""
    if n < 1 or n > count:
        valid = f"1-{count}" if count else "none — the plan has no steps"
        raise ValueError(f"step {n} out of range: valid steps are {valid}")
    return n - 1


def cmd_plan(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Set a plan row's steps, or tick and untick them.

    Steps are numbered from 1 here, matching what a human reads off the card
    and the rail; the store keeps them 0-based internally.
    """
    try:
        if args.step or args.reset_steps:
            store.set_steps(args.key, args.step or [], reset=args.reset_steps)
        q = store.get(args.key)
        if q is None:
            raise KeyError(f"no such question: {args.key}")
        for n in args.done or []:
            store.set_step_done(args.key, _plan_index(n, len(q.steps)), True)
        for n in args.undone or []:
            store.set_step_done(args.key, _plan_index(n, len(q.steps)), False)
        q = store.get(args.key)
    except KeyError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if q is None:
        print(f"cactus: no such question: {args.key}", file=sys.stderr)
        return EXIT_EMPTY
    if args.json:
        _emit_one(q, as_json=True)
    else:
        for st in q.steps:
            print(f"  [{'x' if st.done else ' '}] {st.idx + 1}  {st.text}")
    return EXIT_OK


def cmd_clear(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    if not (args.keys or args.thread or args.all or args.here):
        print(
            "cactus: clear needs keys, --thread, --here, or --all — refusing to guess",
            file=sys.stderr,
        )
        return EXIT_ERROR
    action = "purge" if args.purge else "clear"
    fn = store.purge if args.purge else store.clear

    if args.thread or args.all or args.here:
        # Bulk form: touches every matching row across agents unless scoped to
        # one, so it needs an owner named up front rather than after the fact.
        if not args.agent:
            print(
                f"cactus: bulk {action}s are limited to your own rows and "
                f"need --agent",
                file=sys.stderr,
            )
            return EXIT_ERROR
        count = fn(
            keys=args.keys or None,
            project=project,
            thread=args.thread,
            all_projects=args.all,
            agent=args.agent,
        )
    else:
        # Explicit KEY form: an unowned row clears by key with or without
        # --agent; an owned one refuses unless --agent matches. One refused
        # key refuses the whole call, so a batch never clears part of itself.
        missing = [key for key in args.keys if store.get(key) is None]
        if missing:
            print(f"cactus: no such question: {', '.join(missing)}", file=sys.stderr)
            return EXIT_EMPTY
        refused = []
        for key in args.keys:
            q = store.get(key)
            if q is not None and q.agent is not None and q.agent != args.agent:
                refused.append((key, q.agent))
        if refused:
            detail = ", ".join(f"{k} (owned by {owner})" for k, owner in refused)
            print(
                f"cactus: refusing to {action} rows you do not own: {detail}",
                file=sys.stderr,
            )
            return EXIT_ERROR
        count = fn(keys=args.keys, project=project)

    verb = "purged" if args.purge else "cleared"
    if args.json:
        json.dump({verb: count}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"{verb} {count}")
    return EXIT_OK


def cmd_reopen(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Restore cleared rows: persistent acts to `live`, one-shot rows to their prior state.

    Owner-gated exactly like keyed `clear`: an unowned row reopens by key with
    or without --agent, an owned one refuses unless --agent matches. Missing
    keys and rows that were never cleared are refused up front, the same way a
    batch clear never touches part of itself.
    """
    missing = [key for key in args.keys if store.get(key) is None]
    if missing:
        print(f"cactus: no such question: {', '.join(missing)}", file=sys.stderr)
        return EXIT_EMPTY

    refused = [
        (key, q.agent) for key in args.keys
        if (q := store.get(key)).agent is not None and q.agent != args.agent
    ]
    if refused:
        detail = ", ".join(f"{k} (owned by {owner})" for k, owner in refused)
        print(f"cactus: refusing to reopen rows you do not own: {detail}", file=sys.stderr)
        return EXIT_ERROR

    not_cleared = [key for key in args.keys if store.get(key).status != "cleared"]
    if not_cleared:
        print(f"cactus: not cleared, nothing to reopen: {', '.join(not_cleared)}", file=sys.stderr)
        return EXIT_ERROR

    results = [store.reopen(key) for key in args.keys]
    if args.json:
        json.dump([q.as_dict() for q in results], sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_questions(results, as_json=False, show_project=False)
    return EXIT_OK


def cmd_feed(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Emit the actionable inbox as one document, for a projector to render.

    Scope defaults to every project, matching the human surfaces rather than the
    agent verbs: a board renders whatever the human can reach, and narrows with
    --here or --agent.

    The cursor block is the store's existing change token. A projector compares
    it against its last value and only re-reads rows when it moves, so a poll
    that finds nothing new costs one query.
    """
    status: Any = None if args.status == "any" else args.status
    if isinstance(status, str) and "," in status:
        status = [x.strip() for x in status.split(",") if x.strip()]

    questions = store.list(
        project=project,
        thread=args.thread,
        status=status,
        all_projects=not args.here,
        acts=args.act,
        agent=args.agent,
        workspace=args.workspace,
        tab=args.tab,
        pane=args.pane,
    )
    mid, mts, count = store.cursor()
    # Per-agent rollup of rows still waiting on a human. A board paints a cell
    # by whether its agent is blocked; without this it walks every row to learn
    # one boolean.
    blocked: dict[str, int] = {}
    for q in questions:
        if q.agent and q.blocked and q.status == "open":
            blocked[q.agent] = blocked.get(q.agent, 0) + 1
    doc = {
        "cursor": {
            "max_id": mid,
            "max_updated": mts,
            "count": count,
            "blocked": blocked,
        },
        # Ordered by rowid. A projector may assign board letters from this
        # order and rely on it not shifting between polls.
        "questions": [q.as_dict() for q in questions],
    }
    json.dump(doc, sys.stdout, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return EXIT_OK if questions else EXIT_EMPTY


def cmd_poke(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Nudge the agent that owns a row, so it re-reads the feed."""
    from .poke import poke, PokeError

    agent = args.agent
    if agent is None:
        if not args.key:
            print("cactus: poke needs a key or --agent", file=sys.stderr)
            return EXIT_ERROR
        q = store.get(args.key)
        if q is None:
            print(f"cactus: no such question: {args.key}", file=sys.stderr)
            return EXIT_EMPTY
        agent = q.agent

    try:
        ran = poke(agent, message=args.message)
    except PokeError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        json.dump({"agent": agent, "ran": ran}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"poked {agent}")
    return EXIT_OK


def cmd_threads(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    rows = store.threads(project=project, all_projects=args.all)
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return EXIT_OK
    if not rows:
        return EXIT_EMPTY
    for r in rows:
        name = r["thread"] or "(unthreaded)"
        proj = f"[{project_display(r['project'])}]\t" if args.all else ""
        print(f"{proj}{name}\t{r['open_count']} open\t{r['total']} total\t{r['last_activity']}")
    return EXIT_OK


def cmd_projects(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    rows = store.projects()
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return EXIT_OK
    if not rows:
        return EXIT_EMPTY
    for r in rows:
        marker = "*" if r["project"] == project else " "
        print(
            f"{marker} {project_display(r['project'])}\t"
            f"{r['open_count']} open\t{r['answered_count']} answered\t{r['last_activity']}"
        )
    return EXIT_OK


def cmd_migrate(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Run the one schema change that is not safe to do on open.

    Rebuilding `answers` to drop UNIQUE(question_id) changes the schema under
    every process that already imported an older cactus, so it is a deliberate
    act rather than a side effect of the next command that touches the file.
    """
    if not store.needs_rebuild():
        print(f"cactus: {store.path} is already current")
        return EXIT_OK
    if not args.yes:
        print(
            f"cactus: {store.path} needs the answers table rebuilt.\n"
            f"cactus: back it up first:  sqlite-backup {store.path}\n"
            f"cactus: then re-run with --yes. Restart anything holding an "
            f"older cactus module afterwards.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    store._drop_answer_uniqueness()
    print(f"cactus: rebuilt answers in {store.path}")
    return EXIT_OK


def cmd_where(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    info = {"db": str(store.path), "project": project, "cwd": cwd}
    if args.json:
        json.dump(info, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for k, v in info.items():
            print(f"{k}\t{v}")
    return EXIT_OK


# ---- parser ---------------------------------------------------------------


class _ArgumentParser(argparse.ArgumentParser):
    """argparse's usage-error path exits 2; that code is reserved for --wait
    timeout everywhere else in cactus, so a bad flag has to exit 1 instead.

    `add_subparsers` hands this class down to every subparser it creates
    (via `parser_class=type(self)`), so `cactus ask --nope` exits 1 the same
    way `cactus --nope` does.
    """

    def error(self, message: str) -> "None":  # pragma: no cover - argparse calls this then exits
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _ArgumentParser(
        prog="cactus",
        description="Transitory question/answer interface between agents and a human.",
    )
    p.add_argument("--db", help=f"database path (default: {default_db_path()})")
    p.add_argument("--tui", action="store_true", help="open the interactive answering TUI")
    p.add_argument("--watch", action="store_true", help="open the live read-only feed")
    p.add_argument("--monitor", action="store_true",
                   help="stream inbox events as plain lines, one per change")
    p.add_argument("--all", action="store_true",
                   help="with --monitor, span every project instead of this one")
    p.add_argument("--replay", action="store_true",
                   help="with --monitor, emit the current inbox before streaming")
    p.add_argument("--interval", type=float, default=1.0,
                   help="with --monitor, seconds between polls (default: 1.0)")
    p.add_argument("--agent", help="with --monitor, only events for this agent's rows")
    p.add_argument("--workspace", help="with --monitor, only events for this workspace id")
    p.add_argument("--tab", help="with --monitor, only events for this tab id")
    p.add_argument("--pane", help="with --monitor, only events for this pane id")
    p.add_argument("--here", action="store_true",
                   help="with --tui/--watch, scope to the current project only")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--agent-help", action="store_true",
                   help="how an agent should use cactus, end to end")

    # --json is accepted both before and after the verb; argparse needs it declared
    # on every parser for the trailing form to work.
    # SUPPRESS keeps an omitted trailing --json from clobbering a leading one:
    # a subparser default would otherwise overwrite the value already parsed.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    sub = p.add_subparsers(dest="command")

    def verb(name: str, **kw: Any) -> argparse.ArgumentParser:
        kw.setdefault("parents", [common])
        return sub.add_parser(name, **kw)

    ask = verb("ask", help="add a question to the inbox")
    ask.add_argument("text", help="the question, or - to read stdin")
    ask.add_argument("-c", "--choice", action="append",
                     help="one choice, taken verbatim; repeat for more. Format: 'label: description'")
    ask.add_argument("--multi", action="store_true", help="allow selecting several choices")
    ask.add_argument("--confirm", action="store_true", help="yes/no question")
    ask.add_argument("--act", choices=list(ACTS), default="ask",
                     help="what is being asked for (default: ask)")
    ask.add_argument("--agent",
                     help="required: owning agent, a RESOLVED identity — not a bare pane id")
    ask.add_argument("--word",
                     help="short label a projector derives its key from")
    ask.add_argument("--title",
                     help="short button label for a board with no room for the question")
    ask.add_argument("--chosen",
                     help="the option that happens anyway unless a tap redirects")
    ask.add_argument("--recommend", action="append",
                     help="an option to recommend, taken verbatim; repeat for --multi rows")
    ask.add_argument("--confidence", choices=list(CONFIDENCE),
                     help="how sure the recommendation is; required with --recommend")
    ask.add_argument("--why", help="why this is recommended")
    blk = ask.add_mutually_exclusive_group()
    blk.add_argument("--blocked", dest="blocked", action="store_true", default=None,
                     help="this row parks the agent until it is answered")
    blk.add_argument("--no-block", dest="blocked", action="store_false",
                     help="the agent proceeds; the answer redirects it later")
    ask.add_argument("--kind", choices=["choice", "multi", "text", "confirm"],
                     help="override the inferred kind")
    ask.add_argument("--no-free", action="store_true",
                     help="disallow free-text alongside the choices")
    ask.add_argument("-t", "--thread", help="group under a named thread")
    ask.add_argument("-p", "--parent", help="attach as a follow-up to this question key")
    ask.add_argument("--context", help="supporting detail shown under the question, or -")
    ask.add_argument("--by", help="who is asking (default: $CACTUS_AGENT)")
    ask.add_argument("-w", "--wait", action="store_true", help="block until answered")
    ask.add_argument("--timeout", type=float, help="seconds to wait before giving up")
    ask.set_defaults(fn=cmd_ask)

    get = verb("get", help="read questions by key")
    get.add_argument("keys", nargs="+")
    get.add_argument("-w", "--wait", action="store_true", help="block until answered")
    get.add_argument("--timeout", type=float)
    get.add_argument("--answered-only", action="store_true",
                     help="drop anything still open or cleared")
    get.add_argument("--all", action="store_true", help="show the owning project")
    get.set_defaults(fn=cmd_get)

    ls = verb("list", aliases=["ls"], help="list questions in this project")
    ls.add_argument("-t", "--thread")
    ls.add_argument("--act", action="append", choices=list(ACTS),
                    help="only this act, repeatable")
    ls.add_argument("--agent", help="only rows owned by this agent/pane")
    ls.add_argument("--workspace", help="only rows stamped with this workspace id")
    ls.add_argument("--tab", help="only rows stamped with this tab id")
    ls.add_argument("--pane", help="only rows stamped with this pane id")
    ls.add_argument("-s", "--status", default="open",
                    choices=["open", "answered", "cleared", "any"])
    ls.add_argument("--all", action="store_true", help="every project, not just this one")
    ls.set_defaults(fn=cmd_list)

    ans = verb("answer", help="answer a question without the TUI")
    ans.add_argument("key")
    ans.add_argument("-s", "--select", action="append", help="a chosen label, repeatable")
    ans.add_argument("text", nargs="?", help="free-text answer, or -")
    ans.add_argument("--skip", action="store_true", help="record a deliberate non-answer")
    ans.add_argument("--dismiss", action="store_true",
                     help="dismiss a seen row without choosing (alias of --skip)")
    ans.set_defaults(fn=cmd_answer)

    clr = verb("clear", help="retire questions from the inbox")
    clr.add_argument("keys", nargs="*")
    clr.add_argument("-t", "--thread")
    clr.add_argument("--here", action="store_true", help="everything in this project")
    clr.add_argument("--all", action="store_true", help="every project")
    clr.add_argument("--purge", action="store_true", help="delete rather than mark cleared")
    clr.add_argument("--agent",
                     help="required for -t/--here/--all; also matches an owned key")
    clr.set_defaults(fn=cmd_clear)

    ro = verb("reopen", help="restore cleared rows")
    ro.add_argument("keys", nargs="+")
    ro.add_argument("--agent", help="required to reopen a row you own")
    ro.set_defaults(fn=cmd_reopen)

    fd = verb("feed", help="the actionable inbox as one JSON document, for a projector")
    fd.add_argument("--act", action="append", choices=list(ACTS),
                    help="only this act, repeatable")
    fd.add_argument("--agent", help="only rows owned by this agent/pane")
    fd.add_argument("--workspace", help="only rows stamped with this workspace id")
    fd.add_argument("--tab", help="only rows stamped with this tab id")
    fd.add_argument("--pane", help="only rows stamped with this pane id")
    fd.add_argument("-t", "--thread")
    fd.add_argument("-s", "--status", default="open,live",
                    help="statuses to include, comma-separated, or 'any'")
    fd.add_argument("--here", action="store_true",
                    help="this project only (default: every project)")
    fd.add_argument("--pretty", action="store_true", help="indent the document")
    fd.set_defaults(fn=cmd_feed)

    pk = verb("poke", parents=[common], help="nudge the agent that owns a row")
    pk.add_argument("key", nargs="?", help="row whose owning agent to poke")
    pk.add_argument("--agent", help="poke this agent/pane directly instead")
    pk.add_argument("-m", "--message", help="override the nudge text")
    pk.set_defaults(fn=cmd_poke)

    mg = verb("migrate", parents=[common], help="apply the answers-table rebuild")
    mg.add_argument("--yes", action="store_true", help="actually do it")
    mg.set_defaults(fn=cmd_migrate)

    rv = verb("review", parents=[common],
              help="attach a verify block to a review or run row")
    rv.add_argument("key")
    rv.add_argument("--look-at", help="what a human should look at")
    rv.add_argument("--run", help="the verbatim command to run")
    rv.add_argument("--pass", help="what a good result looks like")
    rv.add_argument("--fail", help="what disqualifies it")
    rv.add_argument("--then", help="what to set up next")
    rv.set_defaults(fn=cmd_review)

    pl = verb("plan", parents=[common], help="set or tick the steps on a plan row")
    pl.add_argument("key")
    pl.add_argument("--step", action="append",
                    help="one step, repeatable; appends to the existing steps")
    pl.add_argument("--reset-steps", action="store_true",
                    help="replace the step list with this call's --step values, clearing done flags")
    pl.add_argument("--done", action="append", type=int, help="tick this step index")
    pl.add_argument("--undone", action="append", type=int, help="untick this step index")
    pl.set_defaults(fn=cmd_plan)

    th = verb("threads", help="list threads")
    th.add_argument("--all", action="store_true")
    th.set_defaults(fn=cmd_threads)

    pr = verb("projects", help="list projects with questions")
    pr.set_defaults(fn=cmd_projects)

    wh = verb("where", help="print the db path and resolved project")
    wh.set_defaults(fn=cmd_where)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    try:
        # build_parser resolves the default database path for its help text, so
        # a misconfigured CACTUS_DB surfaces here rather than as a traceback.
        parser = build_parser()
    except ValueError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    args = parser.parse_args(argv)

    if args.agent_help:
        print(AGENT_HELP, end="")
        return EXIT_OK

    surfaces = [name for name, on in
                (("--tui", args.tui), ("--watch", args.watch), ("--monitor", args.monitor))
                if on]
    if len(surfaces) > 1:
        print(f"cactus: {' and '.join(surfaces)} are mutually exclusive", file=sys.stderr)
        return EXIT_ERROR
    if (args.tui or args.watch) and not sys.stdout.isatty():
        which = "--tui" if args.tui else "--watch"
        print(f"cactus: {which} needs a terminal; stdout is not a tty", file=sys.stderr)
        return EXIT_ERROR

    project, cwd = resolve_project()
    try:
        store = Store(args.db)
    except ValueError as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.tui:
            try:
                from .tui import run_tui
            except ModuleNotFoundError as exc:
                if (exc.name or "").split(".")[0] != "textual":
                    raise
                print(
                    "cactus --tui needs textual; install with: "
                    "uv tool install --editable .",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            return run_tui(store, project=None if not args.here else project)
        if args.watch:
            try:
                from .watch import run_watch
            except ModuleNotFoundError as exc:
                if (exc.name or "").split(".")[0] != "textual":
                    raise
                print(
                    "cactus --watch needs textual; install with: "
                    "uv tool install --editable .",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            return run_watch(store, project=None if not args.here else project)
        if args.monitor:
            from .monitor import run_monitor
            return run_monitor(
                store,
                project=project,
                all_projects=args.all,
                as_json=args.json,
                interval=args.interval,
                replay=args.replay,
                agent=args.agent,
                workspace=args.workspace,
                tab=args.tab,
                pane=args.pane,
            )
        if args.command is None:
            parser.print_help()
            return EXIT_OK
        return int(args.fn(args, store, project, cwd))
    except KeyboardInterrupt:
        return 130
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
