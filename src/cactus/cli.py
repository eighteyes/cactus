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
from .store import (ACTS, ACT_SHAPES, BLOCKING_ACTS, Choice, Question, Store,
                     default_db_path)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_TIMEOUT = 2
EXIT_EMPTY = 3

AGENT_HELP = """\
cactus — ask a human a question without stopping work.

THE ARC

  1  ask       write the question, get a key back, keep working
  2  work      do everything the answer does not block
  3  get/list  collect answers when you reach the fork
  4  ask -p    follow up in the same thread if the answer opens a new question

  The inbox is durable and scoped to the project. A question asked in one
  session is readable from the next, by any agent in the same repository.

ASK

  cactus ask "Which auth backend?" \\
    -c "oidc: existing IdP" \\
    -c "local: bcrypt table" \\
    --context "Staging tenant is provisioned. Local means owning password reset." \\
    -t auth --by "$CACTUS_AGENT"
  q7

  Exactly one question per ask. Choices are taken verbatim, one -c each.

  choice     -c a -c b              one label
  multi      -c a -c b --multi      several labels
  confirm    --confirm              yes / no
  text       no choices             free entry

  Free text is accepted alongside a pick unless --no-free is passed, so an
  answer may carry a selection, typed text, or both.

CONTEXT CARRIES THE DECISION

  --context is what the human needs to decide without opening the repo:
  the tradeoff the labels hide, what has already been checked, what happens
  by default if nobody answers, and what is hard to reverse. Long detail
  reads from stdin with --context -.

  Leave out restatements of the question, reasoning chains, and anything
  already visible in the choice labels.

BLOCK ONLY WHEN BLOCKED

  cactus ask "Safe to drop the legacy column?" --confirm --wait --timeout 600

  --wait returns the moment the status leaves open, including a clear, which
  means the human declined. Always pair it with --timeout and handle exit 2
  as "proceed on the stated default" rather than as a failure. Prefer asking
  early without --wait and collecting later.

MONITOR

  cactus --monitor

  One line per change, flushed as it happens, until interrupted. Point a
  line-oriented watcher at it and keep working; the frontier moves in both
  directions and every move is a line:

  q7  asked     Which auth backend?  (2 choices)
  q7  answered  [oidc] staging first
  q8  skipped   (no answer given)
  q8  cleared   Drop the legacy column?
  q7  reopened  Which auth backend?
  q9  gone

  reopened means a human undid an answer already given: a verdict read earlier
  is stale. gone means the question was purged. A watcher that listens only for
  `answered` cannot tell a quiet inbox from a withdrawn question.

  --all         span every project, prefixing each line with its label
  --json        one JSON object per line, the question plus an event field
  --replay      emit the current inbox first, then stream
  --interval N  seconds between polls (default 1.0)

  Scoped to the current project unless --all is passed.

COLLECT

  cactus get q7 --json
  cactus list -s answered -t auth --json
  cactus list -s open

  A question in an answered state carries selected[], text, and skipped.
  A skipped answer means the human saw it and chose not to decide.

THREADS AND FOLLOW-UPS

  -t NAME     groups related questions; one thread per decision
  -p KEY      attaches a follow-up, inheriting the parent thread

  Ask the whole batch up front under one thread. The human answers them as a
  set, which is faster for them than a drip of separate interrupts.

ACTS

  An act says what you are asking for. It is orthogonal to the answer shape:
  the shape is how a reply is collected, the act is what the reply is for.

    act      blocks   shape                       what it is for
    ask      yes      choice/multi/text/confirm   a decision you need
    steer    yes      choice, text                approve a direction or redirect
    run      yes      confirm                     approve a command before it runs
    seen     no       text                        an FYI; the human dismisses it
    review   no       confirm (pass/fail)         a verify block, re-run over time
    plan     no       text                        an ordered checklist

  Only ask, steer and run block. `--wait` on any of the others is an error,
  because nothing will ever arrive: watch `cactus --monitor` instead.

  review and plan are persistent. They are born `live`, take a verdict as
  often as the work is re-checked, and stay live until cleared. Their answer
  log keeps every verdict, so `answer` is the latest rather than the only one.

  cactus ask "Does the build verify?" --act review -t ship
  q8
  cactus review q8 --look-at "the diff" --run "pytest -q" \
    --pass "0 failures" --fail "any failure" --then "tag the release"

  cactus ask "Release steps" --act plan -t ship
  q9
  cactus plan q9 --step "build" --step "test" --step "tag"
  cactus plan q9 --done 1        # tick a step; the human can tick it too

  --agent ID tags a row with the pane that owns it, defaulting to
  $HERDR_PANE_ID. It filters, it does not scope: the project is still the key.

SCOPE

  Questions record the project they were asked from: the git toplevel, else
  the working directory. Agent verbs see only the current project. The human
  surfaces span every project at once.

  cactus where       the resolved project and database path
  cactus projects    projects with live questions

EXIT CODES

  0  success
  1  error, including --wait on an act that never blocks
  2  --wait timed out
  3  nothing matched

A question is retired with `clear` and stays readable. Answers a human undoes
return to open, so a key that read answered may read open again; re-read
rather than caching the verdict if it still matters.
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
    if act == "run" and kind == "confirm" and not choices:
        choices = [Choice("approve"), Choice("deny")]
    if act == "review" and kind == "confirm" and not choices:
        choices = [Choice("pass"), Choice("fail")]

    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    if not text:
        print("cactus: refusing to ask an empty question", file=sys.stderr)
        return EXIT_ERROR

    context = args.context
    if context == "-":
        context = sys.stdin.read()

    try:
        q = store.ask(
            text,
            project=project,
            cwd=cwd,
            kind=kind,
            act=act,
            agent=args.agent or os.environ.get("HERDR_PANE_ID"),
            choices=choices,
            allow_free=not args.no_free,
            thread=args.thread,
            parent_key=args.parent,
            context=context,
            asked_by=args.by or os.environ.get("CACTUS_AGENT"),
        )
    except (KeyError, ValueError) as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.wait and act not in BLOCKING_ACTS:
        print(
            f"cactus: act={act!r} never blocks; {q.key} created, watch "
            f"`cactus --monitor` for its disposition",
            file=sys.stderr,
        )
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
    if args.wait:
        pending = list(args.keys)
        for key in pending:
            if store.get(key) is None:
                print(f"cactus: no such question: {key}", file=sys.stderr)
                return EXIT_ERROR
            if store.wait_for_answer(key, timeout=args.timeout) is None:
                if not args.json:
                    print(f"cactus: timed out waiting for {key}", file=sys.stderr)
                return EXIT_TIMEOUT

    found: list[Question] = []
    for key in args.keys:
        q = store.get(key)
        if q is None:
            print(f"cactus: no such question: {key}", file=sys.stderr)
            return EXIT_ERROR
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
    except (KeyError, ValueError) as exc:
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
    except (KeyError, ValueError) as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    _emit_one(q, as_json=args.json)
    return EXIT_OK


def cmd_plan(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Set a plan row's steps, or tick and untick them."""
    try:
        if args.step:
            store.set_steps(args.key, args.step)
        for idx in args.done or []:
            store.set_step_done(args.key, idx, True)
        for idx in args.undone or []:
            store.set_step_done(args.key, idx, False)
        q = store.get(args.key)
    except (KeyError, ValueError) as exc:
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if q is None:
        print(f"cactus: no such question: {args.key}", file=sys.stderr)
        return EXIT_NOMATCH
    if args.json:
        _emit_one(q, as_json=True)
    else:
        for st in q.steps:
            print(f"  [{'x' if st.done else ' '}] {st.idx}  {st.text}")
    return EXIT_OK


def cmd_clear(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    if not (args.keys or args.thread or args.all or args.here):
        print(
            "cactus: clear needs keys, --thread, --here, or --all — refusing to guess",
            file=sys.stderr,
        )
        return EXIT_ERROR
    fn = store.purge if args.purge else store.clear
    count = fn(
        keys=args.keys or None,
        project=project,
        thread=args.thread,
        all_projects=args.all,
    )
    verb = "purged" if args.purge else "cleared"
    if args.json:
        json.dump({verb: count}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"{verb} {count}")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
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
    ask.add_argument("--agent", help="owning agent/pane (default: $HERDR_PANE_ID)")
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
    clr.set_defaults(fn=cmd_clear)

    rv = verb("review", parents=[common], help="attach a verify block to a review row")
    rv.add_argument("key")
    rv.add_argument("--look-at", help="what a human should look at")
    rv.add_argument("--run", help="the verbatim command to run")
    rv.add_argument("--pass", help="what a good result looks like")
    rv.add_argument("--fail", help="what disqualifies it")
    rv.add_argument("--then", help="what to set up next")
    rv.set_defaults(fn=cmd_review)

    pl = verb("plan", parents=[common], help="set or tick the steps on a plan row")
    pl.add_argument("key")
    pl.add_argument("--step", action="append", help="one step, repeatable; replaces the list")
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

    project, cwd = resolve_project()
    store = Store(args.db)

    try:
        if args.tui:
            from .tui import run_tui
            return run_tui(store, project=None if not args.here else project)
        if args.watch:
            from .watch import run_watch
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
