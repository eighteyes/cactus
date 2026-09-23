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
cactus — ask a human without stopping work

WORKFLOW — REQUIRED

  1  monitor   start `cactus --monitor` in the background before your first
               ask; keep it running while any row of yours is open
  2  ask       post every decision the human makes here, not in chat;
               --recommend when you have a pick
  3  work      do everything the answer does not block
  4  act       on each event as it lands: answered, reopened, cleared
  5  clear     your own rows, by key, once acted on

ASK

  One question per ask; one -c per choice, taken verbatim

  cactus ask "Which auth backend?" \\
    -c "oidc: existing IdP" \\
    -c "local: bcrypt table" \\
    --context "Staging tenant exists. Local means owning password reset." \\
    -t auth --by "$CACTUS_AGENT"
  q7

  choice     -c a -c b              one label
  multi      -c a -c b --multi      several labels
  confirm    --confirm              yes / no
  text       no choices             free entry

  A choice splits on its first colon: label, then description
  An answer may carry a pick and typed text; --no-free drops the text

AUTHORING

  Options: two or three, mutually exclusive, each a thing that happens. No
  "Other"; reframe the question instead. Cut each until it needs no explanation

  Context: what the human cannot see
    what you tried, and what it cost
    the measurement, with numbers
    what breaks under each option
    what is hard to reverse
    what you do if nobody answers

  Omit restated labels, reasoning chains, reassurance, apology
  --context - reads stdin

BLOCKING

  Collect later by default; --wait only when the work cannot go on

  cactus ask "Safe to drop the legacy column?" --confirm --wait --timeout 600

  --wait returns when the row leaves open; a clear means declined
  On exit 2, proceed on the stated default
  On a non-blocking row --wait errors; watch --monitor instead

ACTS

    act      blocks by default   shape                       for
    ask      yes                 choice/multi/text/confirm   a decision you need
    run      yes                 confirm (approve/deny)      approve a command
    steer    no                  choice, text                what you do anyway
    seen     no                  text                        an FYI, dismissed
    review   no                  confirm (pass/fail)         a verify block
    plan     no                  text                        a checklist

  --blocked / --no-block override on any row
  Block only on what you cannot answer yourself; cursor.blocked counts it

  steer: --chosen LABEL required; you proceed with it, a tap redirects. Ask
  instead when proceeding on a guess is unsafe
  run, review: attach the command with cactus review
  review, plan: persistent — live until cleared, answered on every re-check,
  never blocking. Every verdict is kept; `answer` is the latest

  cactus ask "Deploy staging?" --act run -t ship
  q8
  cactus review q8 --run "make deploy-staging"

  cactus ask "Does the build verify?" --act review -t ship
  q9
  cactus review q9 --look-at "the diff" --run "pytest -q" \\
    --pass "0 failures" --fail "any failure" --then "tag the release"

  cactus ask "Release steps" --act plan -t ship
  q10
  cactus plan q10 --step "build" --step "test" --step "tag"
  cactus plan q10 --done 1       # 1-based

RECOMMEND

  Recommend a pick when you have one; the row still waits

  cactus ask "Which auth backend?" \\
    -c "oidc: existing IdP" -c "local: bcrypt table" \\
    --recommend oidc --confidence high --why "staging tenant is provisioned"

  --recommend LABEL    a real option, confirm rows included; repeatable on multi
  --confidence LEVEL   required: low / med / high → ○ ◐ ●
  --why TEXT           one line

  The TUI preselects it: enter submits, a tap redirects

OWNERSHIP

  --agent ID    the declared session token; never a pane id, which outlives its
                conversation and hands its rows to a resumed session. No
                default; unset rows are unowned. Filters only
  --word SHORT  board-key label; without it, rows starting "check" or "should"
                collide

THREADS

  One thread per decision; post the whole batch up front

  -t NAME     group
  -p KEY      follow up; inherits the parent's thread

COLLECT

  cactus get q7 --json
  cactus list -s answered -t auth --json
  cactus list -s open

  An answered row carries selected[], text, skipped; skipped means seen and
  left undecided
  Re-read rather than cache; an undo reopens a row

MONITOR

  One line per change; point a line watcher at it

  cactus --monitor

  q7  asked     Which auth backend?  (2 choices)
  q7  answered  [oidc] staging first
  q8  skipped   (no answer given)
  q8  cleared   Drop the legacy column?
  q7  reopened  Which auth backend?
  q9  gone

  reopened   an answer was undone; drop any verdict read earlier
  verdict    a persistent row took another verdict
  stepped    a plan step changed
  gone       purged
  Handle every event; a withdrawn question otherwise reads as a quiet inbox

  --all         every project, lines prefixed with its label
  --json        one object per line, with an event field
  --replay      emit the current inbox first
  --interval N  poll seconds (default 1.0)

POKE

  A poke carries no instruction; the agent decides what the moved inbox means

  cactus poke KEY            nudge the row's owner
  cactus poke --agent ID     nudge an agent directly

  The human presses p in the TUI; the agent re-reads
  `cactus feed --json --agent ID`
  Transport: `herdr agent prompt`, or CACTUS_POKE with {agent} and {message},
  substituted per argument, never through a shell
  A poke PROMPTS A LIVE AGENT — set CACTUS_POKE inert before testing

FEED

  The actionable inbox as one JSON document, for a board

  cactus feed --json
  {"cursor": {"max_id": 41, "max_updated": "...", "count": 12},
   "questions": [{"key": "q7", "act": "review", "agent": "herdr:pane-3",
                  "review": {...}, "steps": [], "answers": [...], ...}]}

  Rows embed review block, steps, full answer log
  Steps carry idx (0-based) and n (1-based, for `plan --done`)
  Re-read rows only when the cursor moves; step ticks move it too
  Filters: --act NAME (repeatable), --agent ID, -t THREAD, -s STATUS, --here
  Answer with `cactus answer KEY -s LABEL`, never by writing the database

SCOPE

  A question records its project — the git toplevel, else the directory — and
  persists across sessions. Agent verbs see the current project; human
  surfaces see all

  cactus where       project and database path
  cactus projects    projects with live questions

RETIRE

  cactus clear KEY           retire; the transcript stays readable
  cactus clear --purge KEY   delete

  Clear only keys you posted. -t, --here and --all reach every agent's rows

EXIT CODES

  0  ok
  1  error
  2  --wait timed out
  3  nothing matched
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

    try:
        q = store.ask(
            text,
            project=project,
            cwd=cwd,
            kind=kind,
            act=act,
            # No default. A pane id is not an identity: herdr's own resolver
            # treats `session:pane_id` as the last-resort fallback precisely
            # because it never changes, so it outlives the conversation it
            # named. Defaulting to $HERDR_PANE_ID would address a row to
            # whatever conversation later occupies that pane. The writer is
            # inside the pane and knows its resolved id; it passes --agent or
            # the row stays unowned.
            agent=args.agent or None,
            word=args.word,
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

    if args.wait and not q.blocked:
        print(
            f"cactus: {q.key} was posted with blocked=false; it is created, "
            f"watch `cactus --monitor` for its disposition",
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
    except AlreadyAnswered as exc:
        # Exit 3, not 1: a projector renders this as a stale cell rather than
        # an error, because nothing went wrong — it was simply beaten to it.
        print(f"cactus: {exc}", file=sys.stderr)
        return EXIT_EMPTY
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
        if args.step:
            store.set_steps(args.key, args.step)
        q = store.get(args.key)
        if q is None:
            raise KeyError(f"no such question: {args.key}")
        for n in args.done or []:
            store.set_step_done(args.key, _plan_index(n, len(q.steps)), True)
        for n in args.undone or []:
            store.set_step_done(args.key, _plan_index(n, len(q.steps)), False)
        q = store.get(args.key)
    except (KeyError, ValueError) as exc:
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
    ask.add_argument("--agent",
                     help="owning agent, as a RESOLVED identity — not a bare pane id")
    ask.add_argument("--word",
                     help="short label a projector derives its key from")
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

    fd = verb("feed", help="the actionable inbox as one JSON document, for a projector")
    fd.add_argument("--act", action="append", choices=list(ACTS),
                    help="only this act, repeatable")
    fd.add_argument("--agent", help="only rows owned by this agent/pane")
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
