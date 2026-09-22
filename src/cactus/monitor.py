"""
monitor.py — plain-stdout event stream of a cactus inbox, for agents.

Responsibilities:
- Poll the store's change cursor and diff the inbox against the previous tick.
- Emit one line per transition: asked, answered, skipped, cleared, reopened,
  changed, gone.
- Render each event as a fixed-column line or as one JSON object per line.
- Flush every line immediately so a line-oriented watcher sees events as they land.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Iterable

from .scope import project_label
from .store import Question, Store

DEFAULT_INTERVAL = 1.0


def _answer_signature(q: Question) -> tuple[Any, ...]:
    if q.answer is None:
        return ()
    return (tuple(q.answer.selected), q.answer.text, q.answer.skipped)


def _signature(q: Question) -> tuple[Any, ...]:
    """Everything a watcher would want to hear about if it moved."""
    return (
        q.status,
        q.text,
        q.kind,
        tuple(c.label for c in q.choices),
        q.context,
        _answer_signature(q),
    )


def _arrival_event(q: Question) -> str:
    if q.status == "open":
        return "asked"
    if q.status == "cleared":
        return "cleared"
    return "skipped" if q.answer is not None and q.answer.skipped else "answered"


def _transition_event(before: tuple[Any, ...], q: Question) -> str:
    """Name the move from a previous signature to the current question."""
    if before[0] != q.status:
        if q.status == "open":
            return "reopened"
        return _arrival_event(q)
    return "changed"


def _detail(q: Question, event: str) -> str:
    if event in ("answered", "skipped") and q.answer is not None:
        picks = f"[{', '.join(q.answer.selected)}] " if q.answer.selected else ""
        return f"{picks}{q.answer.text or ''}".strip() or "(no answer given)"
    if event == "asked":
        kinds = {"choice": f"{len(q.choices)} choices",
                 "multi": f"{len(q.choices)} choices, multi",
                 "confirm": "yes / no",
                 "text": "text"}
        return f"{q.text}  ({kinds.get(q.kind, q.kind)})"
    return q.text


def _line(q: Question, event: str, *, show_project: bool) -> str:
    project = f"{project_label(q.project)}  " if show_project else ""
    return f"{q.key}  {event:<9}{project}{_detail(q, event)}"


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


def _snapshot(questions: Iterable[Question]) -> dict[str, tuple[Any, ...]]:
    return {q.key: _signature(q) for q in questions}


def run_monitor(
    store: Store,
    project: str | None = None,
    *,
    all_projects: bool = False,
    as_json: bool = False,
    interval: float = DEFAULT_INTERVAL,
    replay: bool = False,
) -> int:
    """Stream inbox transitions until interrupted. Returns a process exit code.

    The frontier moves in both directions: questions arrive, get answered,
    get undone, get retired, get purged. Every one of those is a line, because
    a watcher that only hears about answers cannot tell a silent inbox from a
    question that was withdrawn.
    """
    def fetch() -> list[Question]:
        return store.list(project=project, status=None, all_projects=all_projects)

    current = fetch()
    if replay:
        for q in current:
            _emit(q, _arrival_event(q), as_json=as_json, show_project=all_projects)
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
            for q in questions:
                signature = _signature(q)
                before = seen.get(q.key)
                if before == signature:
                    continue
                event = _arrival_event(q) if before is None else _transition_event(before, q)
                _emit(q, event, as_json=as_json, show_project=all_projects)
                seen[q.key] = signature
            for key in [k for k in seen if k not in live]:
                _emit_gone(key, as_json=as_json)
                del seen[key]
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # The watcher closed the stream; that is a normal end, not a failure.
        sys.stderr.close()
        return 0
