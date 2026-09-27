"""
monitor.py — plain-stdout event stream of a cactus inbox, for agents.

Responsibilities:
- Poll the store's change cursor and diff the inbox against the previous tick.
- Emit one line per transition: asked, verdict, answered, skipped, cleared,
  reopened, stepped, changed, elaborate, edited, withdrawn, gone.
- Render each event as a fixed-column line or as one JSON object per line.
- Flush every line immediately so a line-oriented watcher sees events as they land.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Iterable

from .scope import project_label
from .store import ACTIONABLE, CONFIDENCE_GLYPH, Question, Store

DEFAULT_INTERVAL = 1.0

# q207 ("both"): the instruction an `elaborate` event carries when the human
# typed no hint of their own. Settled wording overrides the plan doc's older
# phrasing — this is the text an agent actually reads.
DEFAULT_INSTRUCTION = (
    "Rewrite the context plainly — no jargon — and add what is missing: "
    "what you tried, what each option costs, what happens if nobody answers."
)


def _instruction_for(q: Question) -> str:
    hint = (q.elaborate or "").strip()
    return hint if hint else DEFAULT_INSTRUCTION


def _answer_signature(q: Question) -> tuple[Any, ...]:
    if q.answer is None:
        return (0,)
    # The verdict count is part of the signature: a persistent row can be
    # answered the same way twice, and a watcher that only saw the latest
    # values would hear nothing the second time.
    return (len(q.answers), tuple(q.answer.selected), q.answer.text, q.answer.skipped)


def _sidecar_signature(q: Question) -> tuple[Any, ...]:
    review = () if q.review is None else tuple(sorted(q.review.as_dict().items()))
    steps = tuple((st.idx, st.text, st.done) for st in q.steps)
    return (review, steps)


def _signature(q: Question) -> tuple[Any, ...]:
    """Everything a watcher would want to hear about if it moved."""
    return (
        q.status,
        q.text,
        q.kind,
        q.act,
        q.blocked,
        q.chosen,
        tuple(c.label for c in q.choices),
        q.context,
        tuple(q.recommend),
        q.confidence,
        q.recommend_why,
        tuple(q.files),
        # withdrawn vs edited (q228): which action last moved this row out
        # of `elaborate`. Kept ahead of the last two slots below.
        q.last_change,
        # Kept last: `_transition_event` reads before[-2] and before[-1] as
        # the answer and sidecar signatures.
        _answer_signature(q),
        _sidecar_signature(q),
    )


def _arrival_event(q: Question) -> str:
    if q.status in ("open", "live"):
        return "asked"
    if q.status == "elaborate":
        return "elaborate"
    if q.status == "cleared":
        return "cleared"
    return "skipped" if q.answer is not None and q.answer.skipped else "answered"


def _transition_event(before: tuple[Any, ...], q: Question) -> str:
    """Name the move from a previous signature to the current question.

    A persistent row never changes status, so its verdicts would all read as
    `changed` without the answer-count check below — and a verdict on a live
    row is the single event an agent watching this stream is waiting for.
    """
    was_status, *_ = before
    before_answers = before[-2]
    after_answers = _answer_signature_of(q)
    if before_answers != after_answers:
        before_count = 0 if before_answers == (0,) else before_answers[0]
        after_count = 0 if after_answers == (0,) else after_answers[0]
        if after_count < before_count:
            # Undo: an answer withdrawn (answered -> open) or a verdict
            # withdrawn on a persistent row (the log shrinks by one). Both
            # read as `reopened`, never `asked`/`verdict` again.
            return "reopened"
        if q.persistent:
            return "verdict"
        return _arrival_event(q)
    if before[-1] != _sidecar_signature(q):
        return "stepped" if q.steps else "changed"
    if was_status != "elaborate" and q.status == "elaborate":
        return "elaborate"
    if was_status == "elaborate" and q.status != "elaborate":
        # An agent's `edit` addressing the request and a human withdrawing it
        # (`unelaborate`) are otherwise indistinguishable from a pure
        # before/after diff — both leave the row at the same status — so
        # `last_change` (q228), stamped by whichever of the two ran, tells
        # them apart.
        return "withdrawn" if q.last_change == "withdrawn" else "edited"
    edited_fields = (before[1], before[6], before[7], before[8], before[11])
    after_fields = (
        q.text, tuple(c.label for c in q.choices), q.context, tuple(q.recommend),
        tuple(q.files),
    )
    if was_status == q.status and edited_fields != after_fields:
        # A plain in-place `edit` on a row that never went through
        # `elaborate` — text/context/choices/recommend/files are the only
        # fields `edit` ever touches, and nothing else changes them after
        # `ask` (review/plan -f go through the same files slot).
        return "edited"
    if was_status != q.status:
        # Leaving `cleared` is always a restore, whatever status it lands on —
        # a one-shot row that had already been answered when it was cleared
        # comes back `answered`, not `open`, and that still has to read as
        # `reopened` rather than `answered` a second time.
        if was_status == "cleared" or q.status in ("open", "live"):
            return "reopened"
        return _arrival_event(q)
    return "changed"


def _answer_signature_of(q: Question) -> tuple[Any, ...]:
    return _answer_signature(q)


def _detail(q: Question, event: str) -> str:
    if event == "elaborate":
        return _instruction_for(q)
    if event == "stepped":
        done = sum(1 for st in q.steps if st.done)
        return f"{done}/{len(q.steps)} steps  {q.text}"
    if event == "answered" and q.act == "run" and q.answer is not None:
        picks = f"[{', '.join(q.answer.selected)}]" if q.answer.selected else "[]"
        exit_part = f" exit {q.run_exit}" if q.run_exit is not None else ""
        return f"{picks}{exit_part}"
    if event in ("verdict", "answered", "skipped") and q.answer is not None:
        picks = f"[{', '.join(q.answer.selected)}] " if q.answer.selected else ""
        return f"{picks}{q.answer.text or ''}".strip() or "(no answer given)"
    if event == "asked":
        kinds = {"choice": f"{len(q.choices)} choices",
                 "multi": f"{len(q.choices)} choices, multi",
                 "confirm": "yes / no",
                 "text": "text"}
        note = kinds.get(q.kind, q.kind)
        if not q.blocked:
            note += ", not blocking"
        if q.chosen:
            note += f", doing {q.chosen}"
        if q.recommend:
            glyph = CONFIDENCE_GLYPH.get(q.confidence, "")
            note += f", rec {', '.join(q.recommend)} {glyph}".rstrip()
        return f"{q.text}  ({note})"
    return q.text


def _display_key(project: str, key: str, *, show_project: bool) -> str:
    """`LABEL:qN` when spanning projects (q166), else the bare key."""
    return f"{project_label(project)}:{key}" if show_project else key


def _line(
    q: Question, event: str, *, show_project: bool, open_ids: list[str]
) -> str:
    # The act is on every line: a watcher filtering for its own review rows
    # should not have to fetch each key to learn what kind of row it is.
    key = _display_key(q.project, q.key, show_project=show_project)
    suffix = f"  open: {', '.join(open_ids) or '-'}"
    return f"{key}  {event:<9}{q.act:<7}{_detail(q, event)}{suffix}"


def _record(q: Question, event: str, *, open_ids: list[str]) -> dict[str, Any]:
    payload = q.as_dict()
    payload["event"] = event
    payload["open_ids"] = open_ids
    if event == "elaborate":
        # Named exactly as the spec calls for, alongside the row's own
        # `elaborate`/`elaborate_at` fields already in `payload` — `hint` is
        # the event's name for the same value, `instruction` is derived.
        payload["hint"] = q.elaborate
        payload["instruction"] = _instruction_for(q)
    return payload


def _emit(
    q: Question,
    event: str,
    *,
    as_json: bool,
    show_project: bool,
    open_ids: list[str],
) -> None:
    if as_json:
        print(json.dumps(_record(q, event, open_ids=open_ids)), flush=True)
    else:
        print(_line(q, event, show_project=show_project, open_ids=open_ids), flush=True)


def _emit_gone(
    project: str,
    key: str,
    *,
    as_json: bool,
    show_project: bool,
    open_ids: list[str],
) -> None:
    if as_json:
        payload = {"key": key, "event": "gone", "open_ids": open_ids}
        if show_project:
            payload["ref"] = _display_key(project, key, show_project=True)
        print(json.dumps(payload), flush=True)
    else:
        ident = _display_key(project, key, show_project=show_project)
        print(f"{ident}  gone  open: {', '.join(open_ids) or '-'}", flush=True)


def _scope_of(q: Question) -> tuple[str | None, str | None, str | None, str | None]:
    return (q.agent, q.workspace, q.tab, q.pane)


def _snapshot(
    questions: Iterable[Question],
) -> dict[tuple[str, str], tuple[tuple[str | None, ...], tuple[Any, ...]]]:
    # The owning scope travels with the signature, not just the row's current
    # fields: a purge drops the row before a `gone` event can read its agent,
    # workspace, tab, or pane off it, so filtering for `gone` reads it back
    # from here.
    #
    # Keyed by (project, key), not key alone (q166): once keys number per
    # project, "q1" recurs in every project, and a bare-key dict spanning
    # `--all` would conflate two different rows' signatures.
    return {(q.project, q.key): (_scope_of(q), _signature(q)) for q in questions}


def run_monitor(
    store: Store,
    project: str | None = None,
    *,
    all_projects: bool = False,
    as_json: bool = False,
    interval: float = DEFAULT_INTERVAL,
    replay: bool = False,
    agent: str | None = None,
    workspace: str | None = None,
    tab: str | None = None,
    pane: str | None = None,
    once: bool = False,
) -> int:
    """Stream inbox transitions until interrupted. Returns a process exit code.

    The frontier moves in both directions: questions arrive, get answered,
    get undone, get retired, get purged. Every one of those is a line, because
    a watcher that only hears about answers cannot tell a silent inbox from a
    question that was withdrawn.

    `agent`, `workspace`, `tab`, and `pane`, when given, narrow what is emitted
    to rows stamped with that value — the poll itself still spans every row,
    because a `gone` event for a purged row has to be judged against the scope
    recorded in `seen`, not against a row that no longer exists to ask.

    With `agent` set, `asked` is never streamed: the only rows that can
    arrive under that filter are ones the agent posted (or was rehomed
    onto, which the session-start hook already lists). `replay` still
    emits the current inbox first when asked to.

    `once` exits right after the first emitted event that is not `asked` —
    an agent waiting on a verdict in the background after the Monitor tool's
    own time cap hits, not a full session watcher.
    """
    def fetch() -> list[Question]:
        return store.list(project=project, status=None, all_projects=all_projects)

    def owned(scope: tuple[str | None, str | None, str | None, str | None]) -> bool:
        owner, ws, tb, pn = scope
        return (
            (agent is None or owner == agent)
            and (workspace is None or ws == workspace)
            and (tab is None or tb == tab)
            and (pane is None or pn == pane)
        )

    def open_ids(rows: Iterable[Question]) -> list[str]:
        """Actionable row IDs the watching agent can act on right now."""
        return [
            _display_key(q.project, q.key, show_project=all_projects)
            for q in rows
            if q.status in ACTIONABLE and owned(_scope_of(q))
        ]

    current = fetch()
    current_open_ids = open_ids(current)
    if replay:
        for q in current:
            if owned(_scope_of(q)):
                event = _arrival_event(q)
                _emit(
                    q, event, as_json=as_json, show_project=all_projects,
                    open_ids=current_open_ids,
                )
                if once and event != "asked":
                    return 0
    seen = _snapshot(current)
    cursor = store.cursor()

    try:
        while True:
            time.sleep(interval)
            now = store.cursor()
            if now == cursor:
                continue
            cursor = now
            questions = fetch()
            current_open_ids = open_ids(questions)
            live = {(q.project, q.key) for q in questions}
            fired = False
            for q in questions:
                ident = (q.project, q.key)
                signature = _signature(q)
                scope = _scope_of(q)
                prev = seen.get(ident)
                before = prev[1] if prev else None
                # `seen` always tracks the row's current scope, even when its
                # signature (and so its content) has not moved — a pure
                # rehome (q208) changes `agent` only, which `_signature`
                # excludes on purpose, so it must not read as a spurious
                # `answered`/`asked`. Skipping the scope update on a no-op
                # signature would instead leave a freshly rehomed row
                # invisible to the new owner's `--monitor --agent` until
                # some unrelated change touched it.
                if before != signature and owned(scope):
                    event = _arrival_event(q) if before is None else _transition_event(before, q)
                    # An `asked` on an --agent stream is a row that agent
                    # posted itself (q319): the line repeats what it already
                    # knows, and every line lands in its conversation.
                    # `--replay` above still lists the inbox on request.
                    if not (agent is not None and event == "asked"):
                        _emit(
                            q, event, as_json=as_json, show_project=all_projects,
                            open_ids=current_open_ids,
                        )
                    if event != "asked":
                        fired = True
                seen[ident] = (scope, signature)
            for ident in [k for k in seen if k not in live]:
                scope, _ = seen[ident]
                if owned(scope):
                    _emit_gone(
                        *ident,
                        as_json=as_json,
                        show_project=all_projects,
                        open_ids=current_open_ids,
                    )
                    fired = True
                del seen[ident]
            if once and fired:
                return 0
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # The watcher closed the stream; that is a normal end, not a failure.
        sys.stderr.close()
        return 0
