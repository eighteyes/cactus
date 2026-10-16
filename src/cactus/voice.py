# voice.py
# The fixed grammar behind the www voice endpoint: one final transcript in, one Command out.
#
# Responsibilities:
#   - normalise a spoken transcript (case, punctuation, number words, digits)
#   - match it against the grammar table (pick, label, verdict, yes/no, type, skip,
#     undo, move, read, status, step, stop), current row implicit, `qN` naming another
#   - resolve a pick to a real choice label on the target row, or say why it cannot
#   - stay pure: no store, no subprocess, no clock; rows are read by attribute only
#   - return None when nothing in the grammar matches (the caller may then interpret)

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
# "to"/"too" are what a recogniser hears for "two"; only trusted after a lead word.
HOMOPHONES = {"to": 2, "too": 2}

STOP_PHRASES = {"stop", "cancel", "never mind", "nevermind"}
MOVES = {"next": "next", "previous": "previous", "back": "previous"}
STATUS_PHRASES = {"whats next", "what is next", "how many"}
VERDICTS = {"pass", "fail"}
YES_NO = {"yes": 0, "no": 1}
# The allowlist of verbs a Command may carry, grammar or interpreter alike.
VERBS = frozenset({
    "answer", "verdict", "skip", "undo", "next", "previous", "read", "status",
    "step", "none",
})
_KEY = re.compile(r"^q\d+$")


@dataclass(frozen=True)
class Command:
    """What a transcript asked for. `key` None means no row (move, status).

    verb is one of VERBS. `none` runs nothing: its `say` explains why, or is empty
    for stop/cancel/never mind. The interpreter returns the same fields.
    """

    verb: str
    key: str | None = None
    selected: str | None = None
    text: str | None = None
    n: int | None = None
    say: str = ""


def _norm(s: str) -> str:
    s = s.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def _num(tok: str, lead: bool = False) -> int | None:
    if tok.isdigit():
        return int(tok)
    if tok in NUMBER_WORDS:
        return NUMBER_WORDS[tok]
    if lead and tok in HOMOPHONES:
        return HOMOPHONES[tok]
    return None


def _none(say: str) -> Command:
    return Command("none", say=say)


def _find(rows: Sequence[Any], key: str) -> Any | None:
    return next((r for r in rows if getattr(r, "key", None) == key), None)


def _labels(row: Any) -> list[str]:
    return [c.label for c in getattr(row, "choices", None) or []]


def _pick(row: Any, spoken: str, lead: bool) -> Command | None:
    """Resolve spoken words to one of the row's choices. None = not a pick."""
    labels = _labels(row)
    toks = spoken.split()
    n = _num(toks[0], lead) if len(toks) == 1 else None
    if n is not None:
        if not labels:
            return _none(f"{row.key} has no choices")
        if not 1 <= n <= len(labels):
            return _none(f"{row.key} has {len(labels)} choices, not {n}")
        return _answer(row, labels[n - 1])
    folded = {_norm(l): l for l in labels}
    if spoken in folded:
        return _answer(row, folded[spoken])
    hits = [l for f, l in folded.items() if spoken and f.startswith(spoken)]
    if len(hits) == 1:
        return _answer(row, hits[0])
    if len(hits) > 1:
        return _none(f"{spoken} fits more than one choice")
    return None


def _answer(row: Any, label: str) -> Command:
    verdict = getattr(row, "act", None) == "review" and label in VERDICTS
    return Command("verdict" if verdict else "answer", row.key, selected=label)


def _typed(raw: str) -> str | None:
    m = re.match(r"^\s*(?:type|say)\b[\s,:]*(.+?)\s*$", raw, re.I | re.S)
    return m.group(1) if m else None


def parse(transcript: str, row: Any, rows: Sequence[Any] = ()) -> Command | None:
    """Match a final transcript against the grammar. `row` is the current row."""
    raw = transcript or ""
    spoken = _norm(raw)
    if not spoken:
        return None
    if spoken in STOP_PHRASES:
        return Command("none")

    text = _typed(raw)
    if text is not None:
        if row is None:
            return _none("no row to answer")
        return Command("answer", row.key, text=text)

    toks = spoken.split()
    head = toks[0]

    if spoken in MOVES:
        return Command(MOVES[spoken])
    if spoken in STATUS_PHRASES:
        return Command("status")

    if head in ("skip", "undo") and len(toks) <= 2:
        target, bad = _target(toks[1:], row, rows)
        return bad or Command(head, target.key)

    if spoken == "again":
        return _none("nothing to read") if row is None else Command("read", row.key)
    if head == "read" and len(toks) <= 2:
        target, bad = _target(toks[1:], row, rows)
        return bad or Command("read", target.key)

    if head in ("done", "tick") or (head == "mark" and toks[1:2] == ["done"]):
        rest = toks[1:] if head != "mark" else toks[2:]
        if rest[:1] == ["step"]:
            rest = rest[1:]
        n = _num(rest[0], True) if len(rest) == 1 else None
        if n is None:
            return None
        if row is None:
            return _none("no row to tick")
        steps = getattr(row, "steps", None) or []
        if not 1 <= n <= len(steps):
            return _none(f"{row.key} has {len(steps)} steps, not {n}")
        return Command("step", row.key, n=n)

    lead = head in ("pick", "answer")
    body = toks[1:] if lead else toks
    target = row
    if lead and body and _KEY.match(body[0]):
        target = _find(rows, body[0])
        if target is None:
            return _none(f"no {body[0]}")
        body = body[1:]
    if lead and not body:
        return None
    if target is None:
        return _none("no row to answer") if lead else None

    phrase = " ".join(body)
    if not lead and spoken in YES_NO:
        labels = _labels(target)
        if getattr(target, "kind", None) != "confirm" or len(labels) != 2:
            return _none(f"{target.key} is not a yes or no question")
        return _answer(target, labels[YES_NO[spoken]])
    if not lead and spoken in VERDICTS and getattr(target, "act", None) != "review":
        return _none(f"{target.key} is not a review")
    return _pick(target, phrase, lead)


def _target(rest: list[str], row: Any, rows: Sequence[Any]) -> tuple[Any, Command | None]:
    """Row named by an optional trailing `qN`, else the current row."""
    if rest:
        if not _KEY.match(rest[0]):
            return None, _none("didn't catch that")
        found = _find(rows, rest[0])
        return (found, None) if found else (None, _none(f"no {rest[0]}"))
    return (row, None) if row is not None else (None, _none("no row selected"))
