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
#   - run: execute a Command through the Store calls /api/answer uses, refusing anything
#     that executes (a `run` row's approve), and build the sentence to speak
#   - interpret: the stub the claude -p interpreter (W3) fills in later

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


KEYBOARD_ONLY = "that one needs the keyboard"
DIDNT_CATCH = "didn't catch that"
MAX_SPOKEN_CHOICES = 4
_ORDINALS = ["one", "two", "three", "four"]


def interpret(transcript: str, row: Any, rows: Sequence[Any] = ()) -> Command | None:
    """The claude -p fallback for a transcript the grammar missed. Stub: W3 fills it."""
    return None


@dataclass(frozen=True)
class Result:
    """What running a Command did: the sentence to speak and the row to show next."""

    say: str
    next_key: str | None = None
    ok: bool = True


def describe(row: Any) -> str:
    """`q14, <title>. One, a. Two, b.` -- title plus at most four choice labels."""
    title = " ".join((getattr(row, "text", "") or "").split())
    out = f"{row.key}, {title}."
    labels = _labels(row)[:MAX_SPOKEN_CHOICES]
    for word, label in zip(_ORDINALS, labels):
        out += f" {word.capitalize()}, {label}."
    return out


def _next_row(rows: Sequence[Any], after: Any, key: str | None) -> Any | None:
    """The row to show after acting on `key`: the one that took its place."""
    if not rows:
        return None
    keys = [r.key for r in rows]
    if key in keys:
        i = keys.index(key)
        return rows[i + 1] if i + 1 < len(rows) else rows[i]
    if after is not None:
        i = min(after, len(rows) - 1)
        return rows[i]
    return rows[0]


def run(cmd: Command, store: Any, *, project: str | None = None, current: str | None = None,
        rows: Sequence[Any] | None = None) -> Result:
    """Execute `cmd` and report. `rows` is the actionable list before the command ran.

    Nothing here retires, execs, pokes, or approves a `run` row: those say
    KEYBOARD_ONLY. Store errors come back as a spoken sentence, never raised.
    """
    from .store import ACTIONABLE

    def fresh() -> list[Any]:
        return list(store.tree(project=project, status=ACTIONABLE, all_projects=project is None))

    before = list(rows) if rows is not None else fresh()
    keys = [r.key for r in before]
    cur = current if current in keys else (keys[0] if keys else None)
    cur_i = keys.index(cur) if cur in keys else 0

    def then(lead: str, key: str | None, idx: int | None = None) -> Result:
        after = fresh()
        nxt = _next_row(after, idx if key not in [r.key for r in after] else None, key)
        if nxt is None:
            return Result(f"{lead} Nothing left.", None)
        return Result(f"{lead} Next: {describe(nxt)}", nxt.key)

    def show(row: Any, lead: str = "") -> Result:
        return Result(f"{lead} {describe(row)}".strip(), row.key)

    verb = cmd.verb
    if verb == "none":
        return Result(cmd.say, cur, ok=bool(not cmd.say))
    if verb == "status":
        n = len(before)
        if not n:
            return Result("Nothing due.", None)
        nxt = before[cur_i]
        return Result(f"{n} due. Next: {describe(nxt)}", nxt.key)
    if verb in ("next", "previous"):
        if not before:
            return Result("Nothing due.", None)
        step = 1 if verb == "next" else -1
        row = before[(cur_i + step) % len(before)]
        return show(row)

    target = next((r for r in before if r.key == cmd.key), None)
    if target is None and cmd.key:
        try:
            target = store.get(cmd.key, project=project)
        except Exception:  # noqa: BLE001 - a miss is a sentence
            target = None
    if target is None:
        return Result(f"no {cmd.key}" if cmd.key else DIDNT_CATCH, cur, ok=False)
    idx = keys.index(target.key) if target.key in keys else cur_i
    if verb == "read":
        return show(target)

    if getattr(target, "act", None) == "run":
        return Result(KEYBOARD_ONLY, target.key, ok=False)

    proj = getattr(target, "project", None) or project
    try:
        if verb in ("answer", "verdict"):
            selected = [cmd.selected] if cmd.selected else []
            store.answer(target.key, project=proj, selected=selected, text=cmd.text)
            what = cmd.selected or cmd.text or ""
            lead = f"{'Verdict' if verb == 'verdict' else 'Answered'} {what}."
            return then(lead, target.key, idx)
        if verb == "skip":
            store.answer(target.key, project=proj, skipped=True)
            return then("Skipped.", target.key, idx)
        if verb == "undo":
            # `cactus undo KEY` semantics: refuse a cleared row (unless pass-closed)
            # and a row with no answer.
            closed = getattr(target, "closed_by_pass", False)
            if target.status == "cleared" and not closed:
                return Result(f"{target.key} is cleared; restore it from the keyboard", target.key, ok=False)
            if (target.status not in ("answered", "live") or target.answer is None) and not closed:
                return Result(f"{target.key} has no answer to undo", target.key, ok=False)
            store.reopen(target.key, project=proj, withdraw_pass=True)
            return show(store.get(target.key, project=proj) or target, "Undone.")
        if verb == "step":
            n = cmd.n or 0
            steps = getattr(target, "steps", None) or []
            if not 1 <= n <= len(steps):
                return Result(f"{target.key} has {len(steps)} steps, not {n}", target.key, ok=False)
            done = not steps[n - 1].done
            store.set_step_done(target.key, n - 1, done, project=proj)
            return Result(f"Step {n} {'done' if done else 'open'}.", target.key)
    except (ValueError, KeyError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        return Result(str(msg), target.key, ok=False)
    return Result(DIDNT_CATCH, cur, ok=False)
