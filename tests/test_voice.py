# test_voice.py
# Table-driven tests for the voice grammar (cactus.voice.parse).
#
# Responsibilities:
#   - cover each grammar row: pick, label, verdict, yes/no, type, moves, read, status, step, stop
#   - cover qN targeting, refusals that speak, and None for an unparsed transcript

from types import SimpleNamespace as NS

import pytest

from cactus.voice import VERBS, Command, parse


def row(key, labels=(), kind="choice", act="ask", steps=0):
    return NS(key=key, kind=kind, act=act, choices=[NS(label=l) for l in labels],
              steps=[NS(idx=i) for i in range(steps)])


CUR = row("q1", ["red", "green", "postgres", "postmortem"])
CONF = row("q2", ["yes", "no"], kind="confirm")
REV = row("q3", ["pass", "fail"], kind="confirm", act="review")
PLAN = row("q4", kind="text", act="plan", steps=3)
OTHER = row("q12", ["red", "blue"])
ROWS = [CUR, CONF, REV, PLAN, OTHER]


@pytest.mark.parametrize("say,row_,want", [
    ("one", CUR, Command("answer", "q1", selected="red")),
    ("Pick two.", CUR, Command("answer", "q1", selected="green")),
    ("pick to", CUR, Command("answer", "q1", selected="green")),
    ("3", CUR, Command("answer", "q1", selected="postgres")),
    ("answer q12 two", CUR, Command("answer", "q12", selected="blue")),
    ("answer q12 too", CUR, Command("answer", "q12", selected="blue")),
    ("answer q12 red", CUR, Command("answer", "q12", selected="red")),
    ("Green", CUR, Command("answer", "q1", selected="green")),
    ("postg", CUR, Command("answer", "q1", selected="postgres")),
    ("yes", CONF, Command("answer", "q2", selected="yes")),
    ("no", CONF, Command("answer", "q2", selected="no")),
    ("pass", REV, Command("verdict", "q3", selected="pass")),
    ("fail", REV, Command("verdict", "q3", selected="fail")),
    ("type Hello, World", CUR, Command("answer", "q1", text="Hello, World")),
    ("say ship it", CUR, Command("answer", "q1", text="ship it")),
    ("skip", CUR, Command("skip", "q1")),
    ("undo", CUR, Command("undo", "q1")),
    ("skip q12", CUR, Command("skip", "q12")),
    ("next", CUR, Command("next")),
    ("previous", CUR, Command("previous")),
    ("back", CUR, Command("previous")),
    ("read", CUR, Command("read", "q1")),
    ("again", CUR, Command("read", "q1")),
    ("read q12", CUR, Command("read", "q12")),
    ("what's next", CUR, Command("status")),
    ("how many", CUR, Command("status")),
    ("done step two", PLAN, Command("step", "q4", n=2)),
    ("tick 3", PLAN, Command("step", "q4", n=3)),
    ("tick too", PLAN, Command("step", "q4", n=2)),
    ("stop", CUR, Command("none")),
    ("cancel", CUR, Command("none")),
    ("never mind", CUR, Command("none")),
])
def test_grammar(say, row_, want):
    assert parse(say, row_, ROWS) == want


@pytest.mark.parametrize("say,row_,fragment", [
    ("five", CUR, "4 choices"),
    ("answer q99 one", CUR, "no q99"),
    ("yes", CUR, "not a yes or no"),
    ("pass", CUR, "not a review"),
    ("post", CUR, "more than one"),
    ("tick nine", PLAN, "3 steps"),
    ("one", None, ""),
])
def test_refusals_speak(say, row_, fragment):
    got = parse(say, row_, ROWS)
    if row_ is None:
        assert got is None
        return
    assert got.verb == "none" and fragment in got.say


@pytest.mark.parametrize("say", ["", "   ", "banana", "to", "make it blue and then some", "pick"])
def test_unparsed_is_none(say):
    assert parse(say, CUR, ROWS) is None


def test_verbs_allowlist_covers_grammar():
    for say, r in [("one", CUR), ("pass", REV), ("skip", CUR), ("undo", CUR), ("next", CUR),
                   ("back", CUR), ("read", CUR), ("how many", CUR), ("tick 1", PLAN), ("stop", CUR)]:
        assert parse(say, r, ROWS).verb in VERBS


def test_command_is_frozen():
    with pytest.raises(Exception):
        Command("skip").verb = "undo"


# ---- run / describe -----------------------------------------------------------

from cactus.store import Choice
from cactus.voice import KEYBOARD_ONLY, describe, interpret, run


def test_interpret_stub_returns_none():
    assert interpret("anything", CUR, ROWS) is None


def test_describe_title_and_at_most_four_choices():
    r = NS(key="q14", text="which  storage engine", choices=[NS(label=l) for l in "abcdef"])
    assert describe(r) == "q14, which storage engine. One, a. Two, b. Three, c. Four, d."


def _ask(store, project, text, **kw):
    kw.setdefault("choices", [Choice("red"), Choice("green")])
    return store.ask(text, project=project, cwd=project, kind="choice", agent="a1", **kw)


def test_run_answer_then_speaks_next_row(store, project):
    a, b = _ask(store, project, "first?"), _ask(store, project, "second?")
    res = run(Command("answer", a.key, selected="green"), store, project=project, current=a.key)
    assert res.ok and res.say.startswith("Answered green. Next: " + b.key) and res.next_key == b.key
    assert store.get(a.key, project=project).status == "answered"


def test_run_skip_and_undo(store, project):
    a = _ask(store, project, "first?")
    assert run(Command("skip", a.key), store, project=project).say.startswith("Skipped.")
    res = run(Command("undo", a.key), store, project=project)
    assert res.say.startswith("Undone.") and store.get(a.key, project=project).status == "open"


def test_run_undo_refuses_open_and_cleared(store, project):
    a = _ask(store, project, "first?")
    assert "no answer to undo" in run(Command("undo", a.key), store, project=project).say
    store.clear(keys=[a.key], project=project, record=False)
    res = run(Command("undo", a.key), store, project=project)
    assert not res.ok and "cleared" in res.say


def test_run_refuses_run_rows(store, project):
    r = store.ask("go?", project=project, cwd=project, kind="confirm", act="run",
                  choices=[Choice("approve"), Choice("deny")], agent="a1")
    res = run(Command("answer", r.key, selected="approve"), store, project=project)
    assert res.say == KEYBOARD_ONLY and not res.ok
    assert store.get(r.key, project=project).status == "open"


def test_run_status_and_moves(store, project):
    a, b = _ask(store, project, "first?"), _ask(store, project, "second?")
    assert run(Command("status"), store, project=project, current=a.key).say.startswith("2 due.")
    assert run(Command("next"), store, project=project, current=a.key).next_key == b.key
    assert run(Command("previous"), store, project=project, current=a.key).next_key == b.key  # wraps


def test_run_bad_label_is_spoken_not_raised(store, project):
    a = _ask(store, project, "first?")
    res = run(Command("answer", a.key, selected="purple"), store, project=project)
    assert not res.ok and "purple" in res.say


def test_run_none_speaks_its_reason(store, project):
    assert run(Command("none", say="q1 has 2 choices, not 9"), store, project=project).say == "q1 has 2 choices, not 9"
    assert run(Command("none"), store, project=project).say == ""
