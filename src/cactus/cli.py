"""
cli.py — command-line surface for cactus, covering both the agent and human modes.

Responsibilities:
- Parse the agent-facing verbs (ask, get, list, answer, edit, clear, purge,
  threads, projects) and the human verbs the TUI also has (answer, elaborate,
  undo, exec), none of them ownership-gated.
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
import textwrap
from typing import Any, Sequence

from . import __version__, tradeoffs
from .scope import project_display, resolve_project
from .store import (ACTS, ACT_SHAPES, CONFIDENCE, CONFIDENCE_GLYPH,
                    DECOMPOSE_INSTRUCTION, DEFAULT_BLOCKED, AlreadyAnswered, Answer, Choice,
                    Question, Store, default_db_path)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_TIMEOUT = 2
EXIT_EMPTY = 3

# A blocking row waits this long for its answer unless --timeout says otherwise.
DEFAULT_WAIT_TIMEOUT = 3600.0
# Acts that wait for the human by default; the rest never block the agent.
WAITING_ACTS = ("ask", "run")

QUESTION_WIDTH = 80
MAX_QUESTION_LINES = 3


def _wrapped_line_count(text: str, *, width: int = QUESTION_WIDTH) -> int:
    """How many terminal lines a question occupies at the target width."""
    logical_lines = text.splitlines() or [""]
    return sum(
        max(
            1,
            len(textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
            )),
        )
        for line in logical_lines
    )


def _warn_long_question(q: Question) -> None:
    """Nudge agents to split a question before it becomes a tall card."""
    lines = _wrapped_line_count(q.text)
    if lines <= MAX_QUESTION_LINES:
        return
    print(
        f"cactus: {q.key} wraps to {lines} lines at {QUESTION_WIDTH} columns; "
        f"keep questions to {MAX_QUESTION_LINES} lines or decompose them.",
        file=sys.stderr,
    )

AGENT_HELP = """\
NAME
  cactus — durable question inbox between agents and a human

WORKFLOW (required)
  1  cactus ask ... --agent ID        every decision, not chat
  2  a blocking ask (ask, run) waits for the human by default. Run it as ONE
     backgrounded command (Bash run_in_background); its exit is your wake-up.
     Do the rest of the work meanwhile. --no-wait posts and returns.
     Steers and persistent rows (review/plan/data) never wait at ask time:
     collect them with one backgrounded cactus get KEY... --wait (returns on
     the next verdict, tap, or clear).
     A fresh review/plan is cactus ask --act review|plan; cactus review KEY /
     cactus plan KEY only update an existing row.
  3  on each wake, read the row with cactus get KEY (answered, elaborate,
     reopened, cleared)
     review/plan verdict: read it with cactus get KEY --agent ID (that
     tells the human you heard), then respond with cactus plan / review /
     edit KEY --agent ID
  4  cactus clear KEY --agent ID      own rows only

  blocked by a permission prompt -> the PermissionDenied hook already posted a
     run row (cactus list -s open -t denied --agent ID); wait on it backgrounded
     with cactus get KEY --wait. No hook row -> cactus run CMD --agent ID
  a batch posted --no-wait -> one backgrounded cactus get KEY... --wait
  elaborate event -> cactus edit KEY --agent ID

SYNOPSIS
  cactus ask TEXT --agent ID [-c LABEL[: DESC]]... [-f PATH]... [options]
  cactus run CMD --agent ID [--cwd DIR] [--why X] [-t T] [--no-wait] [--timeout S]
             [--recommend approve|deny --confidence L]
  cactus get KEY... [-w] [--timeout S] [--agent ID]
  cactus list [-s STATUS] [-t THREAD] [--act A] [--agent ID] [SCOPE]
  cactus review KEY [--look-at X] [--run CMD] [--pass X] [--fail X] [--then X] [-f PATH]... [--agent ID]
  cactus plan KEY [--step TEXT]... [--reset-steps] [--done N] [--undone N] [-f PATH]... [--agent ID]
  cactus answer KEY [TEXT] [-s LABEL]... [--skip | --dismiss]
  cactus elaborate KEY [HINT] [--decompose | --withdraw]   human verb, no --agent
  cactus undo KEY                    human verb: withdraw the latest answer/verdict
  cactus exec KEY                    human verb: run the row's command, record the result
  cactus edit KEY --agent ID [--text T] [--context C] [-c LABEL[: DESC]]... [-f PATH]...
                             (-f replaces the whole file list; omit to keep it)
  cactus clear KEY... | -t THREAD | --here | --all  [--purge] --agent ID
  cactus reopen KEY... --agent ID
  cactus poke KEY | --agent ID
  cactus deliver [herdr | webhook URL | off] --agent ID [--json]
                             how answers reach this agent (herdr pane prompt or webhook);
                             bare prints the entry, exit 3 if none
  cactus rehome --agent NEW [--json]
  cactus feed --json [--act A] [--agent ID] [SCOPE] [-t T] [-s S] [--here]
  cactus --monitor --json --agent ID [--once]  plain event stream; --once exits on the first event
  cactus where | projects | threads

  KEY  qN in this project, or LABEL:qN / /abs/path:qN for another one

  SCOPE  --workspace ID | --tab ID | --pane ID

ACTS
  act      blocks   shape
  ask      yes      choice | multi | text | confirm
  run      yes      confirm   approve / deny
  steer    no       choice    --chosen required
  notify   no       text
  review   no       confirm   pass / fail; persistent
  plan     no       text      persistent; steps 1-based
  data     no       choice    chunks via -c 'label: body'; copy appends verdict; persistent

ASK OPTIONS
  -c LABEL[: DESC]           one choice, verbatim; repeat. DESC lines '+ pro' / '- con' show as marks
  -f PATH                    a file to preview/edit from the TUI; repeat
  --multi | --confirm        shape; text when no -c
  --kind choice|multi|text|confirm   override the inferred shape
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
  --no-wait                  post and return; ask and run otherwise wait
  --timeout S                wait limit, default 3600

FORMATTING
  Write questions for an 80-column terminal. Keep a question within three
  rendered lines (240 columns total); cactus warns after an ask or edit that
  would wrap past that. Decompose a larger decision into follow-up questions.
  Hard-wrap context and choice descriptions at 80 columns, and keep labels
  short enough to leave room for their descriptions.

STAMPS
  workspace tab pane session   from HERDR_WORKSPACE_ID HERDR_TAB_ID
                                     HERDR_PANE_ID HERDR_SESSION at ask

EVENTS
  asked  answered  skipped  cleared  reopened  verdict  stepped
  elaborate  edited  withdrawn  gone

EXIT STATUS
  0 ok   1 error   2 wait timeout   3 no match

FILES
  .ai/cactus/qN-SLUG.md   decision record, rewritten on each answer, undo,
                          verdict, clear, elaborate; commit it. `edit`
                          updates one only if it already exists.

ENVIRONMENT
  CACTUS_DB       database path
  CACTUS_POKE     override poke transport for every agent; {agent} {message}
  CACTUS_POKE_WEBHOOKS  agent→delivery JSON map, webhook or herdr (default ~/.config/cactus/poke-webhooks.json)
  CACTUS_AGENT    default --by
  CACTUS_RECORDS  0 disables records
  CACTUS_SCOPE    worktree keeps a linked git worktree its own project;
                  default files it under the main repo's toplevel
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


def _revised(q: Question) -> bool:
    """Whether the agent touched a persistent row after the human's latest verdict.

    Mirrors `tui._revised` (q311): `set_review`, `set_steps`/`set_step_done`,
    and `edit` all bump `updated_at`, so the two ISO-with-microsecond UTC
    strings compare lexically against the newest answer's `created_at`.
    """
    return bool(q.answers) and q.updated_at > q.answers[-1].created_at


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
        for p in q.files:
            print(f"\t\t{indent}  {'file':<8}{p}")
        if q.choices and q.status == "open":
            labels = " | ".join(c.label for c in q.choices)
            print(f"\t\t{indent}  choices: {labels}")
        if q.act == "data":
            for i, c in enumerate(q.choices, start=1):
                print(f"\t\t{indent}  {i}) {c.label}")
                for body_line in (c.description or "").splitlines():
                    print(f"\t\t{indent}     {body_line}")
        elif q.kind in ("choice", "multi"):
            for i, c in enumerate(q.choices, start=1):
                marks = tradeoffs.split(c.description)[1]
                if marks:
                    print(f"\t\t{indent}  {i}) {c.label}")
                    for is_pro, text in marks:
                        print(f"\t\t{indent}     {'✓' if is_pro else '✗'} {text}")
        if q.status == "elaborate":
            print(f"\t\t{indent}  wants: {q.elaborate or '(no hint given)'}")
        if q.recommend:
            glyph = CONFIDENCE_GLYPH.get(q.confidence, "")
            why = f" — {q.recommend_why}" if q.recommend_why else ""
            print(f"\t\t{indent}  recommend: {', '.join(q.recommend)} {glyph} {q.confidence}{why}")
        ans = _fmt_answer(q)
        if ans:
            print(f"\t\t{indent}  -> {ans}")
        if q.act == "run" and q.run_exit is not None:
            print(f"\t\t{indent}  exit: {q.run_exit}")
            for line in q.run_tail:
                print(f"\t\t{indent}  | {line}")
        if q.review is not None:
            block = [
                ("look at", q.review.look_at),
                ("run", q.review.run_cmd),
                ("pass", q.review.pass_when),
                ("fail", q.review.fail_when),
                ("then", q.review.then_do),
            ]
            for label, value in block:
                if value:
                    print(f"\t\t{indent}  {label}: {value}")
        if len(q.answers) > 1:
            # The verdict log: a persistent row is answered more than once,
            # so `get`/`list` show every verdict, not just the latest.
            def _verdict(a: Answer) -> str:
                if a.selected and a.text:
                    return f"{', '.join(a.selected)} — {a.text}"
                if a.selected:
                    return ", ".join(a.selected)
                if a.text:
                    return a.text
                return "(skipped)" if a.skipped else "(empty)"
            reprs = ", ".join(_verdict(a) for a in q.answers)
            print(f"\t\t{indent}  verdicts: {reprs}")
        if _revised(q):
            print(f"\t\t{indent}  revised after last verdict")
        if q.act == "plan" and q.steps:
            for st in q.steps:
                mark = "x" if st.done else " "
                print(f"\t\t{indent}  [{mark}] {st.idx + 1}  {st.text}")


def _msg(exc: BaseException) -> str:
    """An exception's text, without str(KeyError(...))'s Python-repr quoting.

    `str(KeyError("no such question: q9"))` renders as `"no such question:
    q9"` — repr'd, quotes and all — because KeyError's __str__ falls back to
    repr(args[0]) when it has exactly one argument. Every other exception
    type here already str()s cleanly.
    """
    if isinstance(exc, KeyError) and len(exc.args) == 1:
        return str(exc.args[0])
    return str(exc)


def _no_match() -> int:
    """One stderr line for every 'nothing matched' exit 3, text or --json alike."""
    print("cactus: no match", file=sys.stderr)
    return EXIT_EMPTY


def _resolve_files(raw: Sequence[str] | None, *, cwd: str) -> list[str]:
    """Resolve `-f/--file` paths to absolute, refusing anything unusable.

    Raises ValueError (caught by every caller the same way as a bad ask())
    for a missing path, a directory, or a duplicate after resolution.
    """
    resolved: list[str] = []
    for original in raw or []:
        path = os.path.abspath(os.path.join(cwd, original))
        if not os.path.exists(path):
            raise ValueError(f"no such file: {original}")
        if os.path.isdir(path):
            raise ValueError(f"not a file: {original}")
        if path in resolved:
            raise ValueError(f"duplicate file: {path}")
        resolved.append(path)
    return resolved


def _emit_one(q: Question, *, as_json: bool) -> None:
    if as_json:
        json.dump(q.as_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_questions([q], as_json=False, show_project=False)


# ---- verbs ----------------------------------------------------------------


def _add_wait_flags(p: argparse.ArgumentParser) -> None:
    """--wait / --no-wait / --timeout for the verbs that post a blocking row."""
    w = p.add_mutually_exclusive_group()
    w.add_argument("-w", "--wait", action="store_true",
                   help="block until answered (the default for ask and run; kept for back-compat)")
    w.add_argument("--no-wait", action="store_true",
                   help="post and return at once instead of waiting")
    p.add_argument("--timeout", type=float,
                   help=f"seconds to wait before giving up (default {int(DEFAULT_WAIT_TIMEOUT)})")


def cmd_ask(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    if args.multi and args.confirm:
        # 3: a row cannot be both a checklist and a yes/no at once.
        print("cactus: --multi and --confirm are mutually exclusive", file=sys.stderr)
        return EXIT_ERROR
    if args.multi and ACT_SHAPES[args.act] == ("choice",):
        # A data row hands over one chunk per copy; --multi has nothing to mean.
        print(f"cactus: --act {args.act} takes a single choice; --multi is not supported", file=sys.stderr)
        return EXIT_ERROR

    # Each -c is exactly one choice, taken verbatim. Splitting on commas here
    # would silently shred any description that contains one.
    choices = [Choice.parse(raw.strip()) for raw in (args.choice or []) if raw.strip()]
    labels = [c.label for c in choices]
    if len(labels) != len(set(labels)):
        # 2: two choices with the same label are indistinguishable once picked.
        print(f"cactus: duplicate choice labels: {labels}", file=sys.stderr)
        return EXIT_ERROR
    if choices and (args.confirm or ACT_SHAPES[args.act] == ("confirm",)) and len(choices) != 2:
        # 4, 5: a confirm shape is exactly two options — yes/no, pass/fail,
        # approve/deny — never a one-button or three-button "confirm".
        print(
            f"cactus: a confirm takes exactly 2 choices, got {len(choices)}: {labels}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    act = args.act
    if act == "data" and not choices:
        # A data row hands over chunks; with none, there is nothing to copy.
        print(
            "cactus: --act data needs at least one -c 'label: body' chunk",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if choices and ACT_SHAPES[act] == ("text",):
        # notify and plan collect text only; silently forcing kind="text" below
        # would strand the -c choices on a row that never reads them.
        print(f"cactus: --act {act} takes no choices; it collects text only", file=sys.stderr)
        return EXIT_ERROR
    if args.no_free and not choices:
        # A no-free text row (kind=text, including notify/plan) could never be
        # answered: no choices to pick and free text is refused too.
        print(
            "cactus: --no-free needs choices; a text question with no free "
            "text cannot be answered",
            file=sys.stderr,
        )
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
    if not text or not text.strip():
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
    # A blocking ask waits by default; --no-wait posts and returns.
    wait = args.wait or (not args.no_wait and would_block and act in WAITING_ACTS)
    if args.timeout is not None and not wait:
        # 9: --timeout only means something on a row that waits.
        print("cactus: --timeout needs a waiting row; drop --no-wait", file=sys.stderr)
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
    if not store.project_enabled(project):
        print(
            "cactus: disabled for this project — run `cactus project activate` to reactivate it",
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
        files = _resolve_files(args.file, cwd=cwd)
        # -p accepts a bare key (this project), LABEL:qN, or /abs/path:qN
        # (q166); ambiguous labels and missing parents both raise here and
        # are reported the same way as any other bad ask().
        parent_project, parent_bare = (
            store.resolve_ref(args.parent, project) if args.parent else (None, None)
        )
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
            parent_key=parent_bare,
            parent_project=parent_project,
            context=context,
            asked_by=args.by or os.environ.get("CACTUS_AGENT"),
            files=files,
        )
    except (KeyError, ValueError) as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR

    _warn_long_question(q)
    if not wait:
        if args.json:
            _emit_one(q, as_json=True)
        else:
            print(q.key)
        return EXIT_OK
    return _post_then_wait(store, q, project, args)


def _post_then_wait(store: Store, q: Any, project: str, args: argparse.Namespace) -> int:
    """Print the key at once, then block for the answer and print it like `get --wait`.

    The key goes out first (flushed) so a caller watching the output sees the
    row exists before the block starts. Under --json it goes to stderr, so
    stdout stays one parseable document.
    """
    if args.json:
        print(q.key, file=sys.stderr, flush=True)
    else:
        print(q.key, flush=True)
    timeout = args.timeout if args.timeout is not None else DEFAULT_WAIT_TIMEOUT
    answered = store.wait_for_answer(q.key, project=project, timeout=timeout)
    if answered is None:
        if args.json:
            json.dump({"key": q.key, "status": "timeout"}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"cactus: timed out waiting for {q.key}", file=sys.stderr)
        return EXIT_TIMEOUT
    _emit_one(answered, as_json=args.json)
    return EXIT_OK


def cmd_run(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Ask approval to run a command: one step instead of ask --act run + review --run."""
    if not (args.agent or "").strip():
        print(
            "cactus: run needs --agent ID, the declared session identity — "
            "never a pane id",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if not store.project_enabled(project):
        print(
            "cactus: disabled for this project — run `cactus project activate` to reactivate it",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if bool(args.recommend) != bool(args.confidence):
        print(
            "cactus: --recommend needs --confidence, and --confidence needs --recommend",
            file=sys.stderr,
        )
        return EXIT_ERROR
    text = args.cmd
    if not text or not text.strip():
        print("cactus: refusing to run an empty command", file=sys.stderr)
        return EXIT_ERROR
    wait = not args.no_wait
    if args.timeout is not None and not wait:
        print("cactus: --timeout needs a waiting row; drop --no-wait", file=sys.stderr)
        return EXIT_ERROR

    workspace = os.environ.get("HERDR_WORKSPACE_ID") or None
    tab = os.environ.get("HERDR_TAB_ID") or None
    pane = os.environ.get("HERDR_PANE_ID") or None
    session = os.environ.get("HERDR_SESSION") or None

    try:
        q = store.ask(
            text,
            project=project,
            cwd=args.cwd or cwd,
            kind="confirm",
            act="run",
            agent=args.agent,
            workspace=workspace,
            tab=tab,
            pane=pane,
            session=session,
            recommend=[args.recommend] if args.recommend else None,
            confidence=args.confidence,
            thread=args.thread,
            context=args.why,
            asked_by=os.environ.get("CACTUS_AGENT"),
        )
        store.set_review(q.key, project=project, run_cmd=text)
        q = store.get(q.key, project=project)
        assert q is not None
    except (KeyError, ValueError) as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR

    if wait:
        return _post_then_wait(store, q, project, args)
    if args.json:
        _emit_one(q, as_json=True)
    else:
        print(q.key)
    return EXIT_OK


def cmd_get(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    if args.timeout is not None and not args.wait:
        print("cactus: --timeout needs --wait", file=sys.stderr)
        return EXIT_ERROR
    # Each ref resolves independently (q166): a bare qN in this project, or a
    # qualified LABEL:qN / /abs/path:qN naming another one.
    try:
        refs = [(k, *store.resolve_ref(k, project)) for k in args.keys]
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    for raw, rproj, rkey in refs:
        if store.get(rkey, project=rproj) is None:
            print(f"cactus: no such question: {raw}", file=sys.stderr)
            return EXIT_EMPTY

    if args.wait:
        timed_out_key = None
        settled_keys: list[tuple[str, str]] = []
        try:
            for raw, rproj, rkey in refs:
                if store.wait_for_answer(rkey, project=rproj, timeout=args.timeout) is None:
                    timed_out_key = raw
                    break
                settled_keys.append((rproj, rkey))
        except (KeyError, ValueError) as exc:
            print(f"cactus: {_msg(exc)}", file=sys.stderr)
            return EXIT_ERROR
        if timed_out_key is not None:
            # Print whatever already settled before the miss, so a caller
            # waiting on several keys is not left with nothing at all.
            settled = [
                q for q in (store.get(rkey, project=rproj) for rproj, rkey in settled_keys)
                if q is not None
            ]
            if settled:
                _print_questions(settled, as_json=args.json, show_project=args.all)
            if not args.json:
                print(f"cactus: timed out waiting for {timed_out_key}", file=sys.stderr)
            return EXIT_TIMEOUT

    found: list[Question] = []
    for _, rproj, rkey in refs:
        q = store.get(rkey, project=rproj)
        assert q is not None
        found.append(q)

    if args.answered_only:
        found = [q for q in found if q.status == "answered"]
        if not found:
            return _no_match()

    if args.agent:
        # The owner's read is what the human sees as `heard ✓` (q406). Stamped
        # after the fetch, so the printed rows are exactly what `get` returned
        # before; a non-owner or a bare `get` never stamps.
        for q in found:
            if q.agent == args.agent and q.act in ("review", "plan"):
                store.mark_heard(q.id)

    _print_questions(found, as_json=args.json, show_project=args.all)
    return EXIT_OK


def cmd_list(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    status: Any = None if args.status == "any" else args.status
    if isinstance(status, str) and "," in status:
        status = [x.strip() for x in status.split(",") if x.strip()]
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
        return _no_match()
    _print_questions(questions, as_json=args.json, show_project=args.all)
    return EXIT_OK


def cmd_answer(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    try:
        rproj, rkey = store.resolve_ref(args.key, project)
        q = store.answer(
            rkey,
            project=rproj,
            selected=args.select or [],
            text=text,
            skipped=args.skip or args.dismiss,
        )
    except AlreadyAnswered as exc:
        # Exit 3, not 1: a projector renders this as a stale cell rather than
        # an error, because nothing went wrong — it was simply beaten to it.
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except KeyError as exc:
        # No such question: exit 3, the same as every other verb that takes
        # a key — a missing row is a miss, not a malformed call.
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    # Webhook-mapped owners need a wake; other agents wake on their own backgrounded wait.
    try:
        from .poke import deliver_if_mapped, PokeError

        woke = deliver_if_mapped(q.agent, pane=q.pane, session=q.session)
        if woke and not args.json:
            print(f"auto-poke: {woke}", file=sys.stderr)
    except PokeError as exc:
        print(f"cactus: answer saved; webhook poke failed: {_msg(exc)}", file=sys.stderr)
    _emit_one(q, as_json=args.json)
    return EXIT_OK


def _human_ref(args: argparse.Namespace, store: Store, project: str) -> tuple[str, str] | int:
    """Resolve a human verb's KEY, or return the exit code after printing why."""
    try:
        return store.resolve_ref(args.key, project)
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR


def cmd_elaborate(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Ask the owner to rewrite a row (TUI `e`), split it (`D`), or take it back (`u`).

    A human verb like `answer`: no --agent, no ownership gate.
    """
    if args.decompose and args.hint:
        print("cactus: --decompose takes no HINT", file=sys.stderr)
        return EXIT_ERROR
    if args.withdraw and args.hint:
        print("cactus: --withdraw takes no HINT", file=sys.stderr)
        return EXIT_ERROR
    ref = _human_ref(args, store, project)
    if isinstance(ref, int):
        return ref
    rproj, rkey = ref
    try:
        if args.withdraw:
            q = store.unelaborate(rkey, project=rproj)
        else:
            hint = args.hint
            if args.decompose:
                hint = DECOMPOSE_INSTRUCTION.format(key=rkey)
            q = store.elaborate_request(rkey, hint=hint or None, project=rproj)
    except KeyError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    _emit_one(q, as_json=args.json)
    return EXIT_OK


def cmd_undo(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Withdraw the latest answer or verdict on an answered or live row (TUI `u`).

    A human verb: no ownership gate. It cannot recall an answer an agent
    already read. A cleared row restores through `reopen`, which is gated.
    """
    ref = _human_ref(args, store, project)
    if isinstance(ref, int):
        return ref
    rproj, rkey = ref
    q = store.get(rkey, project=rproj)
    if q is None:
        print(f"cactus: no such question: {args.key}", file=sys.stderr)
        return EXIT_EMPTY
    if q.status == "cleared":
        print(f"cactus: {q.key} is cleared; restore it with `cactus reopen {q.key} --agent ID`",
              file=sys.stderr)
        return EXIT_ERROR
    if q.status not in ("answered", "live") or q.answer is None:
        print(f"cactus: {q.key} has no answer to undo", file=sys.stderr)
        return EXIT_ERROR
    try:
        q = store.reopen(rkey, project=rproj)
    except KeyError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    _emit_one(q, as_json=args.json)
    return EXIT_OK


def cmd_exec(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Run a row's command in its own directory and record the result (TUI `R`).

    A `run` row also records `approve` and pokes a webhook-mapped owner, as
    approving in the TUI does; a review row gets the result only, its verdict
    stays the human's. Exit 0 once the result is recorded, whatever the
    command's own exit code. Under --json the live output goes to stderr so
    stdout stays one document.
    """
    from .shell import ShellError, parse_exit_code, run, spill

    ref = _human_ref(args, store, project)
    if isinstance(ref, int):
        return ref
    rproj, rkey = ref
    q = store.get(rkey, project=rproj)
    if q is None:
        print(f"cactus: no such question: {args.key}", file=sys.stderr)
        return EXIT_EMPTY
    command = q.review.run_cmd if q.review is not None else None
    if not command:
        print(f"cactus: {q.key} carries no command", file=sys.stderr)
        return EXIT_ERROR
    if q.act not in ("run", "review"):
        print(f"cactus: {q.key} is act={q.act!r}, not 'run' or 'review'", file=sys.stderr)
        return EXIT_ERROR
    if q.status == "cleared":
        print(f"cactus: {q.key} is cleared; restore it with `cactus reopen {q.key} --agent ID`",
              file=sys.stderr)
        return EXIT_ERROR

    out = sys.stderr if args.json else sys.stdout
    lines: list[str] = []
    try:
        for line in run(command, cwd=q.cwd):
            lines.append(line)
            print(line, file=out, flush=True)
    except ShellError as exc:
        lines.append(f"— {exc} —")
        print(lines[-1], file=out, flush=True)
    exit_code = parse_exit_code(lines)
    try:
        log_path = spill(lines, key=q.key)
        q = store.set_run_result(
            rkey, project=rproj, exit_code=exit_code, tail=lines[-50:], log=str(log_path)
        )
        if q.act == "run":
            q = store.answer(rkey, project=rproj, selected=["approve"], text=None)
    except AlreadyAnswered as exc:
        print(f"cactus: result saved; {_msg(exc)}", file=sys.stderr)
        q = store.get(rkey, project=rproj) or q
    except (KeyError, ValueError, OSError) as exc:
        print(f"cactus: result not recorded: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    else:
        if q.act == "run":
            try:
                from .poke import deliver_if_mapped, PokeError

                woke = deliver_if_mapped(q.agent, pane=q.pane, session=q.session)
                if woke and not args.json:
                    print(f"auto-poke: {woke}", file=sys.stderr)
            except PokeError as exc:
                print(f"cactus: answer saved; webhook poke failed: {_msg(exc)}", file=sys.stderr)
    if args.json:
        json.dump(q.as_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return EXIT_OK


def cmd_edit(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Replace fields on an open/live/elaborate row; also how an agent answers
    an `elaborate` request.

    Owner-gated like keyed `clear`: an unowned row edits with `--agent`, an
    owned one refuses unless `--agent` matches. `--agent` itself is always
    required here (unlike `clear`) — an edit is never a bulk, unowned sweep.
    """
    if not (args.agent or "").strip():
        print(
            "cactus: edit needs --agent ID, the declared session identity — "
            "never a pane id",
            file=sys.stderr,
        )
        return EXIT_ERROR
    try:
        rproj, rkey = store.resolve_ref(args.key, project)
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    q = store.get(rkey, project=rproj)
    if q is None:
        print(f"cactus: no such question: {args.key}", file=sys.stderr)
        return EXIT_EMPTY
    if q.agent is not None and q.agent != args.agent:
        print(
            f"cactus: refusing to edit a row you do not own: {args.key} "
            f"(owned by {q.agent})",
            file=sys.stderr,
        )
        return EXIT_ERROR

    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    context = args.context
    if context == "-":
        context = sys.stdin.read()

    choices = None
    if args.choice is not None:
        choices = [Choice.parse(raw.strip()) for raw in args.choice if raw.strip()]
        labels = [c.label for c in choices]
        if len(labels) != len(set(labels)):
            print(f"cactus: duplicate choice labels: {labels}", file=sys.stderr)
            return EXIT_ERROR

    files = None
    try:
        if args.file is not None:
            files = _resolve_files(args.file, cwd=cwd)
        result = store.edit(
            rkey, agent=args.agent, project=rproj,
            text=text, context=context, choices=choices, files=files,
        )
    except KeyError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    _warn_long_question(result)
    _mark_responded(store, result, args.agent)
    _emit_one(result, as_json=args.json)
    return EXIT_OK


def _refuse_if_not_owner(action: str, key: str, q, agent: str | None) -> str | None:
    """Ownership message for a keyed verb, or None when it may proceed.

    Unlike `clear`/`reopen`/`edit`, an omitted --agent here is not a bulk-safety
    gate — it means "behave as today": no ownership check at all. The check only
    fires when --agent is given and the row is owned by someone else.
    """
    if agent and q.agent is not None and q.agent != agent:
        return (
            f"cactus: refusing to {action} a row you do not own: {key} "
            f"(owned by {q.agent})"
        )
    return None


def _mark_responded(store: Store, q: Question, agent: str | None) -> None:
    """Stamp `responded_at` when the row's owner writes to a review/plan row.

    Lives here, not in `Store`, so a TUI write through the same store methods
    never counts as the agent answering (q406).
    """
    if agent and q.agent == agent and q.act in ("review", "plan"):
        store.mark_responded(q.id)


def cmd_review(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Attach or replace the verify block on a review row."""
    try:
        rproj, rkey = store.resolve_ref(args.key, project)
        q = store.get(rkey, project=rproj)
        if q is None:
            raise KeyError(f"no such question: {args.key}")
        msg = _refuse_if_not_owner("review", args.key, q, args.agent)
        if msg is not None:
            print(msg, file=sys.stderr)
            return EXIT_ERROR
        if args.file is not None:
            store.set_files(rkey, _resolve_files(args.file, cwd=cwd), project=rproj)
        q = store.set_review(
            rkey,
            project=rproj,
            look_at=args.look_at,
            run_cmd=args.run,
            pass_when=getattr(args, "pass"),
            fail_when=args.fail,
            then_do=args.then,
        )
        _mark_responded(store, q, args.agent)
    except KeyError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
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
    if args.reset_steps and not args.step:
        print("cactus: --reset-steps needs at least one --step", file=sys.stderr)
        return EXIT_ERROR
    clash = sorted(set(args.done or []) & set(args.undone or []))
    if clash:
        print(f"cactus: --done and --undone both name step {clash}", file=sys.stderr)
        return EXIT_ERROR
    try:
        rproj, rkey = store.resolve_ref(args.key, project)
        q0 = store.get(rkey, project=rproj)
        if q0 is None:
            raise KeyError(f"no such question: {args.key}")
        msg = _refuse_if_not_owner("plan", args.key, q0, args.agent)
        if msg is not None:
            print(msg, file=sys.stderr)
            return EXIT_ERROR
        if args.file is not None:
            store.set_files(rkey, _resolve_files(args.file, cwd=cwd), project=rproj)
        if args.step or args.reset_steps:
            store.set_steps(rkey, args.step or [], project=rproj, reset=args.reset_steps)
        q = store.get(rkey, project=rproj)
        if q is None:
            raise KeyError(f"no such question: {args.key}")
        if (args.done or args.undone) and q.act != "plan":
            raise ValueError(f"{args.key} is act={q.act!r}, not 'plan'")
        for n in args.done or []:
            store.set_step_done(rkey, _plan_index(n, len(q.steps)), project=rproj)
        for n in args.undone or []:
            store.set_step_done(rkey, _plan_index(n, len(q.steps)), False, project=rproj)
        q = store.get(rkey, project=rproj)
        if q is not None:
            _mark_responded(store, q, args.agent)
    except KeyError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_EMPTY
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
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
        kw = {} if args.purge else {"record": False}
        count = fn(
            keys=args.keys or None,
            project=project,
            thread=args.thread,
            all_projects=args.all,
            agent=args.agent,
            **kw,
        )
    else:
        # Explicit KEY form: an unowned row clears by key with or without
        # --agent; an owned one refuses unless --agent matches. One refused
        # key refuses the whole call, so a batch never clears part of itself.
        # Each ref resolves independently (q166) — a bare qN in this project,
        # or a qualified LABEL:qN / /abs/path:qN naming another one.
        try:
            refs = [(k, *store.resolve_ref(k, project)) for k in args.keys]
        except ValueError as exc:
            print(f"cactus: {_msg(exc)}", file=sys.stderr)
            return EXIT_ERROR
        missing = [raw for raw, rproj, rkey in refs if store.get(rkey, project=rproj) is None]
        if missing:
            print(f"cactus: no such question: {', '.join(missing)}", file=sys.stderr)
            return EXIT_EMPTY
        refused = []
        for raw, rproj, rkey in refs:
            q = store.get(rkey, project=rproj)
            if q is not None and q.agent is not None and q.agent != args.agent:
                refused.append((raw, q.agent))
        if refused:
            detail = ", ".join(f"{k} (owned by {owner})" for k, owner in refused)
            print(
                f"cactus: refusing to {action} rows you do not own: {detail}",
                file=sys.stderr,
            )
            return EXIT_ERROR
        kw = {} if args.purge else {"record": False}
        # Batched per resolved project — `keys=` combines with `project=` as
        # one AND'd filter, so a call spanning two projects has to run once
        # per project rather than lump every bare key under the caller's own.
        count = 0
        by_project: dict[str, list[str]] = {}
        for _, rproj, rkey in refs:
            by_project.setdefault(rproj, []).append(rkey)
        for rproj, rkeys in by_project.items():
            count += fn(keys=rkeys, project=rproj, **kw)

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
    try:
        refs = [(k, *store.resolve_ref(k, project)) for k in args.keys]
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR

    missing = [raw for raw, rproj, rkey in refs if store.get(rkey, project=rproj) is None]
    if missing:
        print(f"cactus: no such question: {', '.join(missing)}", file=sys.stderr)
        return EXIT_EMPTY

    refused = [
        (raw, q.agent) for raw, rproj, rkey in refs
        if (q := store.get(rkey, project=rproj)).agent is not None and q.agent != args.agent
    ]
    if refused:
        detail = ", ".join(f"{k} (owned by {owner})" for k, owner in refused)
        print(f"cactus: refusing to reopen rows you do not own: {detail}", file=sys.stderr)
        return EXIT_ERROR

    not_cleared = [
        raw for raw, rproj, rkey in refs if store.get(rkey, project=rproj).status != "cleared"
    ]
    if not_cleared:
        print(f"cactus: not cleared, nothing to reopen: {', '.join(not_cleared)}", file=sys.stderr)
        return EXIT_ERROR

    results = [store.reopen(rkey, project=rproj) for _, rproj, rkey in refs]
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
    return EXIT_OK if questions else _no_match()


def cmd_poke(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Nudge the agent that owns a row, so it re-reads the feed."""
    from .poke import poke, PokeError

    agent = args.agent
    pane = session = None
    if agent is None:
        if not args.key:
            print("cactus: poke needs a key or --agent", file=sys.stderr)
            return EXIT_ERROR
        try:
            rproj, rkey = store.resolve_ref(args.key, project)
        except ValueError as exc:
            print(f"cactus: {_msg(exc)}", file=sys.stderr)
            return EXIT_ERROR
        q = store.get(rkey, project=rproj)
        if q is None:
            print(f"cactus: no such question: {args.key}", file=sys.stderr)
            return EXIT_EMPTY
        agent, pane, session = q.agent, q.pane, q.session

    try:
        ran = poke(agent, pane=pane, session=session, message=args.message)
    except PokeError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        json.dump({"agent": agent, "ran": ran}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"poked {agent}")
    return EXIT_OK


def cmd_deliver(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Declare (or read, or drop) how answers reach `--agent`: a herdr pane
    prompt or a webhook, in the per-agent delivery map. No database change."""
    from .poke import PokeError, delivery_entry, write_delivery

    agent = args.agent.strip()
    if not agent:
        print("cactus: deliver needs a non-empty --agent", file=sys.stderr)
        return EXIT_ERROR
    mode, url = args.mode, args.url
    if url is not None and mode != "webhook":
        print("cactus: URL only goes with `deliver webhook`", file=sys.stderr)
        return EXIT_ERROR
    try:
        if mode is None:
            entry = delivery_entry(agent)
        elif mode == "off":
            if delivery_entry(agent) is None:
                return _no_match()
            write_delivery(agent, None)
            entry = None
        else:
            if mode == "webhook":
                if not url or not url.strip():
                    print("cactus: deliver webhook needs a URL", file=sys.stderr)
                    return EXIT_ERROR
                entry = {"url": url.strip()}
            else:
                entry = {"herdr": True}
            write_delivery(agent, entry)
    except (PokeError, OSError) as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    if mode is None and entry is None:
        return _no_match()
    if args.json:
        json.dump(entry, sys.stdout)
        sys.stdout.write("\n")
    elif mode == "off":
        print(f"{agent}: delivery off")
    else:
        what = "herdr" if entry.get("herdr") else f"webhook {entry.get('url', '?')}"
        print(f"{agent}: {what}")
    return EXIT_OK


def cmd_rehome(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Move every row this identity asked under its old one onto it (q208).

    Gated to the caller's own herdr pane+session stamp: without both, there
    is no trail to follow, so this refuses rather than guessing which rows
    are "mine". Safe to call on every session start — zero matches is the
    normal case, not an error.
    """
    pane = os.environ.get("HERDR_PANE_ID") or None
    session = os.environ.get("HERDR_SESSION") or None
    if not pane or not session:
        print(
            "cactus: rehome needs HERDR_PANE_ID and HERDR_SESSION set — "
            "without both there is no stamp to rehome from",
            file=sys.stderr,
        )
        return EXIT_ERROR
    keys = store.rehome(project=project, new_agent=args.agent, pane=pane, session=session)
    if args.json:
        json.dump({"agent": args.agent, "count": len(keys), "keys": keys}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"rehomed {len(keys)}")
    return EXIT_OK


def cmd_threads(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    rows = store.threads(project=project, all_projects=args.all)
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return EXIT_OK
    if not rows:
        return _no_match()
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
        return _no_match()
    for r in rows:
        marker = "*" if r["project"] == project else " "
        state = "active" if r["enabled"] else "ignored"
        print(
            f"{marker} {project_display(r['project'])}\t"
            f"{state}\t{r['open_count']} open\t{r['answered_count']} answered\t{r['last_activity']}"
        )
    return EXIT_OK


def cmd_project_status(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Expose the current project's hook switch for plugin hooks and diagnostics."""
    if args.cwd:
        project, _ = resolve_project(args.cwd)
    info = {"project": project, "enabled": store.project_enabled(project)}
    if args.json:
        json.dump(info, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"{project_display(project)}\t{'active' if info['enabled'] else 'ignored'}")
    return EXIT_OK


def cmd_project(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Inspect or change the current project's Cactus switch."""
    if args.cwd:
        project, _ = resolve_project(args.cwd)
    if args.project_action == "activate":
        store.set_project_enabled(project, True)
    elif args.project_action == "ignore":
        store.set_project_enabled(project, False)
    info = {"project": project, "enabled": store.project_enabled(project)}
    if args.json:
        json.dump(info, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"{project_display(project)}\t{'active' if info['enabled'] else 'ignored'}")
    return EXIT_OK


def cmd_migrate(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Run the schema changes that are not safe to do on open.

    Rebuilding `answers` to drop UNIQUE(question_id), and `questions` to drop
    the global UNIQUE(key) that per-project numbering (q166) cannot use, both
    change the schema under every process that already imported an older
    cactus, so this is a deliberate act rather than a side effect of the next
    command that touches the file.
    """
    needed = []
    if store.needs_rebuild():
        needed.append("answers")
    if store.needs_key_rebuild():
        needed.append("questions")
    if not needed:
        print(f"cactus: {store.path} is already current")
        return EXIT_OK
    if not args.yes:
        print(
            f"cactus: {store.path} needs {' and '.join(needed)} rebuilt.\n"
            f"cactus: back it up first:  sqlite-backup {store.path}\n"
            f"cactus: then re-run with --yes. Restart anything holding an "
            f"older cactus module afterwards.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    store._drop_answer_uniqueness()
    store._drop_key_uniqueness()
    print(f"cactus: rebuilt {' and '.join(needed)} in {store.path}")
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


def cmd_sky(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Inspect, write, or benchmark the field's sky tuning config (unrelated
    to the inbox; ignores `store`, kept only for the usual `cmd_*`
    signature)."""
    from .sky import SkyConfig, config_path

    if args.bench:
        from .field import run_bench

        for label, mean_ms in run_bench():
            print(f"{label}: {mean_ms:.3f} ms")
        return EXIT_OK
    if args.dump:
        target = config_path()
        if target.exists() and not args.force:
            print(f"cactus: {target} exists; pass --force to overwrite it", file=sys.stderr)
            return EXIT_ERROR
        path = SkyConfig().dump()
        print(f"wrote defaults (all commented) to {path}")
        return EXIT_OK
    print(str(config_path()))
    return EXIT_OK


def cmd_garden(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Inspect or clear the shared garden file (unrelated to the inbox;
    ignores `project`/`cwd`, kept only for the usual `cmd_*` signature)."""
    from . import garden

    path = garden.garden_path(store.path)
    if args.clear:
        cleared = garden.clear(path)
        if args.json:
            print(json.dumps({"path": str(path), "cleared": cleared}))
        else:
            print(f"cleared {path}" if cleared else "nothing to clear")
        return EXIT_OK

    data = garden.read(path)
    cells = len(data["cells"]) if data else 0
    drops = data["drops"] if data else 0
    if args.json:
        print(json.dumps({"path": str(path), "cells": cells, "drops": drops}))
        return EXIT_OK
    if data is None:
        print(f"{path}  empty")
    else:
        print(f"{path}  {cells} cells  {drops} drops")
    return EXIT_OK


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _decider_argv(backend: str, host: str, port: int) -> tuple[list[str], str | None]:
    """(argv, missing): the server command, and an install hint when its
    binary or modules are absent. CACTUS_DECIDER_CMD is a template over
    {backend}, {host}, {port} and replaces the real command (tests)."""
    import importlib.util
    import shlex
    import shutil

    fields = {"backend": backend, "host": host, "port": port}
    override = os.environ.get("CACTUS_DECIDER_CMD")
    if override:
        argv = [a.format(**fields) for a in shlex.split(override)]
        return argv, None if argv and shutil.which(argv[0]) else f"{argv[0] if argv else '(empty)'} not found"
    if backend == "clef":
        argv = [sys.executable, "-m", "cactus.clef_serve", "--host", host, "--port", str(port)]
        have = all(importlib.util.find_spec(m) for m in ("torch", "transformers", "huggingface_hub"))
        return argv, None if have else "pip install torch transformers huggingface_hub pillow"
    argv = ["strands-decider", "serve", "StrandsAgents/strands-decider-2B-hobson-v19",
            "--host", host, "--port", str(port)]
    return argv, None if shutil.which(argv[0]) else "pip install strands-decider"


def cmd_decider(args: argparse.Namespace, store: Store, project: str, cwd: str) -> int:
    """Start, check or stop the local model server behind the auto-decider.
    Never installs anything; ignores `project`/`cwd`."""
    import signal
    import subprocess
    from urllib.parse import urlsplit

    from . import decide

    backend = args.backend or decide.resolve_backend()
    url = decide.base_url(backend)
    pid_path = store.path.parent / f"decider-{backend}.pid"
    log_path = store.path.parent / f"decider-{backend}.log"
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        pid = None
    if pid is not None and not _pid_alive(pid):
        pid = None

    def report(up: bool, note: str = "") -> None:
        if args.json:
            print(json.dumps({"backend": backend, "url": url, "up": up, "pid": pid,
                              "log": str(log_path), "note": note}))
        else:
            print(f"{backend}  {url}  {'up' if up else 'down'}  pid {pid or '-'}  log {log_path}"
                  + (f"  {note}" if note else ""))

    action = args.decider_action
    if action == "status":
        up = decide.health(backend)
        report(up)
        return EXIT_OK if up else EXIT_EMPTY
    if action == "stop":
        if pid is None:
            pid_path.unlink(missing_ok=True)
            print(f"cactus: {backend} decider not running", file=sys.stderr)
            return EXIT_EMPTY
        os.kill(pid, signal.SIGTERM)
        pid_path.unlink(missing_ok=True)
        report(False, "stopped")
        return EXIT_OK
    if decide.health(backend):
        report(True, "already running")
        return EXIT_OK
    parts = urlsplit(url)
    argv, missing = _decider_argv(backend, parts.hostname or "127.0.0.1", parts.port or 8000)
    if missing:
        print(f"cactus: cannot start {backend} decider; install with: {missing}", file=sys.stderr)
        return EXIT_ERROR
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
    pid_path.write_text(f"{proc.pid}\n")
    pid = proc.pid
    report(False, "started")
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
    p.add_argument("--www", action="store_true",
                   help="serve a localhost web answering surface (human)")
    p.add_argument("--port", type=int, default=8642, help="with --www, port to bind (default: 8642)")
    p.add_argument("--host", default="127.0.0.1", help="with --www, host to bind (default: 127.0.0.1)")
    p.add_argument("--open", action="store_true", help="with --www, open the browser once bound")
    p.add_argument("--monitor", action="store_true",
                   help="stream inbox events as plain lines, one per change")
    p.add_argument("--all", action="store_true",
                   help="with --monitor, span every project instead of this one")
    p.add_argument("--replay", action="store_true",
                   help="with --monitor, emit the current inbox before streaming")
    p.add_argument("--once", action="store_true",
                   help="with --monitor, exit 0 right after the first non-asked event")
    p.add_argument("--interval", type=float, default=1.0,
                   help="with --monitor, seconds between polls (default: 1.0)")
    p.add_argument("--agent", help="with --monitor, only events for this agent's rows "
                                   "(never `asked`: those are its own posts)")
    p.add_argument("--workspace", help="with --monitor, only events for this workspace id")
    p.add_argument("--tab", help="with --monitor, only events for this tab id")
    p.add_argument("--pane", help="with --monitor, only events for this pane id")
    p.add_argument("--here", action="store_true",
                   help="with --tui/--watch/--www, scope to the current project (git toplevel of pwd)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--version", action="version", version=f"cactus {__version__}")
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
    ask.add_argument("-f", "--file", action="append",
                     help="a file the human may preview or edit; repeat for more")
    _add_wait_flags(ask)
    ask.set_defaults(fn=cmd_ask)

    rn = verb("run", help="ask approval to run a command, one step")
    rn.add_argument("cmd", help="the command to run, verbatim")
    rn.add_argument("--agent", required=True,
                    help="required: owning agent, a RESOLVED identity — not a bare pane id")
    rn.add_argument("--cwd", help="directory to run in (default: caller's cwd)")
    rn.add_argument("--why", help="context for the request")
    rn.add_argument("-t", "--thread", help="group under a named thread")
    rn.add_argument("--recommend", choices=["approve", "deny"],
                    help="an option to recommend")
    rn.add_argument("--confidence", choices=list(CONFIDENCE),
                    help="how sure the recommendation is; required with --recommend")
    _add_wait_flags(rn)
    rn.set_defaults(fn=cmd_run)

    get = verb("get", help="read questions by key")
    get.add_argument("keys", nargs="+")
    get.add_argument("-w", "--wait", action="store_true", help="block until answered (non-blocking rows: until the next change)")
    get.add_argument("--timeout", type=float)
    get.add_argument("--answered-only", action="store_true",
                     help="drop anything still open or cleared")
    get.add_argument("--all", action="store_true", help="show the owning project")
    get.add_argument("--agent", help="declare who is reading; the owner's read of a "
                     "review/plan row tells the human it was heard")
    get.set_defaults(fn=cmd_get)

    ls = verb("list", aliases=["ls"], help="list questions in this project")
    ls.add_argument("-t", "--thread")
    ls.add_argument("--act", action="append", choices=list(ACTS),
                    help="only this act, repeatable")
    ls.add_argument("--agent", help="only rows owned by this agent/pane")
    ls.add_argument("--workspace", help="only rows stamped with this workspace id")
    ls.add_argument("--tab", help="only rows stamped with this tab id")
    ls.add_argument("--pane", help="only rows stamped with this pane id")
    ls.add_argument("-s", "--status", default="open,live,elaborate",
                    help="statuses to include, comma-separated ('open', 'live', "
                         "'elaborate', 'answered', 'cleared'), or 'any'")
    ls.add_argument("--all", action="store_true", help="every project, not just this one")
    ls.set_defaults(fn=cmd_list)

    ans = verb("answer", help="answer a question without the TUI")
    ans.add_argument("key")
    ans.add_argument("-s", "--select", action="append", help="a chosen label, repeatable")
    ans.add_argument("text", nargs="?", help="free-text answer, or -")
    skip_grp = ans.add_mutually_exclusive_group()
    skip_grp.add_argument("--skip", action="store_true", help="record a deliberate non-answer")
    skip_grp.add_argument("--dismiss", action="store_true",
                          help="dismiss a notify row without choosing (alias of --skip)")
    ans.set_defaults(fn=cmd_answer)

    el = verb("elaborate", help="ask the owner to rewrite a row, or withdraw the request")
    el.add_argument("key")
    el.add_argument("hint", nargs="?", help="what to rewrite")
    el_grp = el.add_mutually_exclusive_group()
    el_grp.add_argument("--decompose", action="store_true",
                        help="ask the owner to split the row into smaller questions (TUI D)")
    el_grp.add_argument("--withdraw", action="store_true",
                        help="take back a pending request (TUI u)")
    el.set_defaults(fn=cmd_elaborate)

    ud = verb("undo", help="withdraw the latest answer or verdict on a row")
    ud.add_argument("key")
    ud.set_defaults(fn=cmd_undo)

    ex = verb("exec", help="run a row's command, record the result (a run row also approves)")
    ex.add_argument("key")
    ex.set_defaults(fn=cmd_exec)

    ed = verb("edit", help="replace fields on a row; also answers an elaborate request")
    ed.add_argument("key")
    ed.add_argument("--agent", required=True,
                    help="required: owning agent, a RESOLVED identity — not a bare pane id")
    ed.add_argument("--text", help="replacement question text, or -")
    ed.add_argument("--context", help="replacement context, or -")
    ed.add_argument("-c", "--choice", action="append",
                    help="one choice, taken verbatim; repeat. Replaces the whole "
                         "list; a recommendation naming a dropped label is cleared")
    ed.add_argument("-f", "--file", action="append",
                    help="a file the human may preview or edit; repeat. Replaces "
                         "the whole list")
    ed.set_defaults(fn=cmd_edit)

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

    fd = verb(
        "feed", help="the actionable inbox as one JSON document, for a projector",
        description="Always emits JSON. --json is accepted as a no-op, for a "
                     "caller that passes it to every verb uniformly.",
    )
    fd.add_argument("--act", action="append", choices=list(ACTS),
                    help="only this act, repeatable")
    fd.add_argument("--agent", help="only rows owned by this agent/pane")
    fd.add_argument("--workspace", help="only rows stamped with this workspace id")
    fd.add_argument("--tab", help="only rows stamped with this tab id")
    fd.add_argument("--pane", help="only rows stamped with this pane id")
    fd.add_argument("-t", "--thread")
    fd.add_argument("-s", "--status", default="open,live,elaborate",
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

    dl = verb("deliver", parents=[common],
              help="declare how answers reach an agent: herdr, webhook URL, or off")
    dl.add_argument("mode", nargs="?", choices=["herdr", "webhook", "off"],
                    help="omit to print the agent's current entry")
    dl.add_argument("url", nargs="?", help="webhook URL (webhook mode only)")
    dl.add_argument("--agent", required=True, help="the agent id whose entry to set")
    dl.set_defaults(fn=cmd_deliver)

    rh = verb("rehome", parents=[common],
              help="move this session's rows from a prior identity onto --agent")
    rh.add_argument("--agent", required=True, help="the identity to move matching rows onto")
    rh.set_defaults(fn=cmd_rehome)

    mg = verb("migrate", parents=[common], help="apply pending destructive-shaped table rebuilds")
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
    rv.add_argument("--agent", help="refuse if the row is owned by a different agent")
    rv.add_argument("-f", "--file", action="append",
                    help="a file the human may preview or edit; repeat. Replaces "
                         "the whole list; omit to keep it")
    rv.set_defaults(fn=cmd_review)

    pl = verb("plan", parents=[common], help="set or tick the steps on a plan row")
    pl.add_argument("key")
    pl.add_argument("--step", action="append",
                    help="one step, repeatable; appends to the existing steps")
    pl.add_argument("--reset-steps", action="store_true",
                    help="replace the step list with this call's --step values, clearing done flags")
    pl.add_argument("--done", action="append", type=int, help="tick this step, 1-based")
    pl.add_argument("--undone", action="append", type=int, help="untick this step, 1-based")
    pl.add_argument("--agent", help="refuse if the row is owned by a different agent")
    pl.add_argument("-f", "--file", action="append",
                    help="a file the human may preview or edit; repeat. Replaces "
                         "the whole list; omit to keep it")
    pl.set_defaults(fn=cmd_plan)

    th = verb("threads", help="list threads")
    th.add_argument("--all", action="store_true")
    th.set_defaults(fn=cmd_threads)

    pr = verb("projects", help="list projects with questions")
    pr.set_defaults(fn=cmd_projects)

    ps = verb("project-status", help="report whether Cactus hooks are active here")
    ps.add_argument("--cwd", help="project directory to inspect (default: caller's cwd)")
    ps.set_defaults(fn=cmd_project_status)

    pj = verb("project", help="inspect or change this project's Cactus state")
    pj.add_argument("project_action", nargs="?", choices=["status", "activate", "ignore"],
                    default="status")
    pj.add_argument("--cwd", help="project directory to change (default: caller's cwd)")
    pj.set_defaults(fn=cmd_project)

    wh = verb("where", help="print the db path and resolved project")
    wh.set_defaults(fn=cmd_where)

    sk = verb("sky", help="inspect or write the field's sky tuning config")
    sk.add_argument("--dump", action="store_true",
                    help="write the default sky tuning constants to the config path (refuses an existing file)")
    sk.add_argument("--force", action="store_true",
                    help="with --dump, overwrite an existing config file")
    sk.add_argument("--bench", action="store_true",
                    help="run a 50-frame perf probe (100x20, 3 seeds) and print the frame-time breakdown")
    sk.set_defaults(fn=cmd_sky)

    gd = verb("garden", help="inspect or clear the shared landed-pile file")
    gd.add_argument("--clear", action="store_true", help="remove the garden file")
    gd.set_defaults(fn=cmd_garden)

    dc = verb("decider", help="start, check or stop the local auto-decider model server")
    dc.add_argument("decider_action", nargs="?", choices=["start", "status", "stop"],
                    default="status")
    dc.add_argument("--backend", choices=["strands", "clef"],
                    help="which server (default: CACTUS_DECIDER_BACKEND, else strands)")
    dc.set_defaults(fn=cmd_decider)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    try:
        # build_parser resolves the default database path for its help text, so
        # a misconfigured CACTUS_DB surfaces here rather than as a traceback.
        parser = build_parser()
    except ValueError as exc:
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
        return EXIT_ERROR
    args = parser.parse_args(argv)

    if args.agent_help:
        print(AGENT_HELP, end="")
        return EXIT_OK

    surfaces = [name for name, on in
                (("--tui", args.tui), ("--watch", args.watch), ("--www", args.www),
                 ("--monitor", args.monitor))
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
        print(f"cactus: {_msg(exc)}", file=sys.stderr)
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
        if args.www:
            from .www import run_www
            return run_www(
                store,
                project=None if not args.here else project,
                host=args.host,
                port=args.port,
                open_browser=args.open,
            )
        if args.monitor:
            if not (args.agent or "").strip():
                print(
                    "cactus: --monitor needs --agent ID — humans use --tui/--watch",
                    file=sys.stderr,
                )
                return EXIT_ERROR
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
                once=args.once,
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
