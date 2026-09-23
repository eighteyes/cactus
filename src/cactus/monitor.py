"""
monitor.py — plain-stdout event stream of a cactus inbox, for agents.

Responsibilities:
- Poll the store's change cursor and diff the inbox against the previous tick.
- Emit one line per transition: asked, verdict, answered, skipped, cleared,
  reopened, stepped, changed, gone.
- Render each event as a fixed-column line or as one JSON object per line.
- Flush every line immediately so a line-oriented watcher sees events as they land.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Iterable

from .scope import project_label
from .store import CONFIDENCE_GLYPH, Question, Store

DEFAULT_INTERVAL = 1.0


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
        # Kept ahead of the last two slots: `_transition_event` reads
        # before[-2] and before[-1] as the answer and sidecar signatures.
        tuple(q.recommend),
        q.confidence,
        q.recommend_why,
        _answer_signature(q),
        _sidecar_signature(q),
    )


def _arrival_event(q: Question) -> str:
    if q.status in ("open", "live"):
        return "asked"
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


def _line(q: Question, event: str, *, show_project: bool) -> str:
    project = f"{project_label(q.project)}  " if show_project else ""
    # The act is on every line: a watcher filtering for its own review rows
    # should not have to fetch each key to learn what kind of row it is.
    return f"{q.key}  {event:<9}{q.act:<7}{project}{_detail(q, event)}"


def _record(q: Question, event: str) -> dict[str, Any]:
    payload = q.as_dict()
    payload["event"] = event
    return payload


def _emit(q: Question, event: str, *, as_json: bool, show_project: bool) -> None:
    if as_json:
        print(json.dumps(_record(q, event)), flush=True)
    else:
        print(_line(q, event, show_project=show_project), flush=True)


def _emit_gone(key: str, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"key": key, "event": "gone"}), flush=True)
    else:
        print(f"{key}  gone", flush=True)


def _scope_of(q: Question) -> tuple[str | None, str | None, str | None, str | None]:
    return (q.agent, q.workspace, q.tab, q.pane)


def _snapshot(
    questions: Iterable[Question],
) -> dict[str, tuple[tuple[str | None, ...], tuple[Any, ...]]]:
    # The owning scope travels with the signature, not just the row's current
    # fields: a purge drops the row before a `gone` event can read its agent,
    # workspace, tab, or pane off it, so filtering for `gone` reads it back
    # from here.
    return {q.key: (_scope_of(q), _signature(q)) for q in questions}


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

    current = fetch()
    if replay:
        for q in current:
            if owned(_scope_of(q)):
                event = _arrival_event(q)
                _emit(q, event, as_json=as_json, show_project=all_projects)
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
            live = {q.key for q in questions}
            fired = False
            for q in questions:
                signature = _signature(q)
                prev = seen.get(q.key)
                before = prev[1] if prev else None
                if before == signature:
                    continue
                if owned(_scope_of(q)):
                    event = _arrival_event(q) if before is None else _transition_event(before, q)
                    _emit(q, event, as_json=as_json, show_project=all_projects)
                    if event != "asked":
                        fired = True
                seen[q.key] = (_scope_of(q), signature)
            for key in [k for k in seen if k not in live]:
                scope, _ = seen[key]
                if owned(scope):
                    _emit_gone(key, as_json=as_json)
                    fired = True
                del seen[key]
            if once and fired:
                return 0
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # The watcher closed the stream; that is a normal end, not a failure.
        sys.stderr.close()
        return 0
