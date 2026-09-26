"""
test_tui.py — CactusApp footer, projects pane, and answering behavior.

Responsibilities:
- Footer relabeling follows the focused row's act/kind (y/n, digits, d).
- `s` (skip) stays available on plan/review/data/notify rows.
- A --no-free row hides the `i` (type) key in both footer and card hint.
- Digit keys answer a choice row.
- The projects pane opens/closes with `P`/escape and `I`/`A` flip a project's
  enabled switch, but only while not typing.
- Undo restores an answered row to open.
- An empty multi submit records nothing and flashes instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Footer, Static
from textual.widgets._footer import FooterKey

from cactus.store import Choice, Store
from cactus.tui import CactusApp

AGENT = "t"


def footer_keys(app: CactusApp) -> dict[str, str]:
    return {
        fk.key_display or fk.key: fk.description
        for fk in app.query_one(Footer).query(FooterKey)
    }


def card_hint(app: CactusApp) -> str:
    text = str(app.query_one("#card", Static).content)
    lines = text.strip().splitlines()
    return lines[-1] if lines else ""


async def test_footer_relabels_review_run_plan_data_choice(store: Store, project: str) -> None:
    review_key = store.ask(
        "review this", project=project, cwd=project, agent=AGENT,
        kind="confirm", act="review", choices=[Choice("pass"), Choice("fail")],
    ).key
    run_key = store.ask(
        "run this", project=project, cwd=project, agent=AGENT,
        kind="confirm", act="run", choices=[Choice("approve"), Choice("deny")],
    ).key
    plan_key = store.ask(
        "plan this", project=project, cwd=project, agent=AGENT, kind="text", act="plan",
    ).key
    store.set_steps(plan_key, ["s1", "s2"])
    data_key = store.ask(
        "data row", project=project, cwd=project, agent=AGENT,
        kind="choice", act="data", choices=[Choice("one", "body")],
    ).key
    choice_key = store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    ).key

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()

        async def goto(key: str) -> None:
            for _ in range(len(app.questions)):
                if app.focused_key == key:
                    return
                await pilot.press("j")
                await pilot.pause()
            raise AssertionError(f"{key} not reached on rail")

        await goto(review_key)
        keys = footer_keys(app)
        assert keys["y"] == "pass"
        assert keys["n"] == "fail"

        await goto(run_key)
        keys = footer_keys(app)
        assert keys["y"] == "approve"
        assert keys["n"] == "deny"

        await goto(plan_key)
        keys = footer_keys(app)
        assert keys["1-9"] == "Toggle step"

        await goto(data_key)
        keys = footer_keys(app)
        assert keys["1-9"] == "Copy chunk"
        assert keys["d"] == "Close"

        await goto(choice_key)
        keys = footer_keys(app)
        assert keys["1-9"] == "Pick"


async def test_skip_key_present_on_plan_review_data_notify(store: Store, project: str) -> None:
    plan_key = store.ask(
        "plan this", project=project, cwd=project, agent=AGENT, kind="text", act="plan",
    ).key
    review_key = store.ask(
        "review this", project=project, cwd=project, agent=AGENT,
        kind="confirm", act="review", choices=[Choice("pass"), Choice("fail")],
    ).key
    data_key = store.ask(
        "data row", project=project, cwd=project, agent=AGENT,
        kind="choice", act="data", choices=[Choice("one", "body")],
    ).key
    notify_key = store.ask(
        "fyi", project=project, cwd=project, agent=AGENT, kind="text", act="notify",
    ).key

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()

        async def goto(key: str) -> None:
            for _ in range(len(app.questions)):
                if app.focused_key == key:
                    return
                await pilot.press("j")
                await pilot.pause()
            raise AssertionError(f"{key} not reached on rail")

        for key in (plan_key, review_key, data_key, notify_key):
            await goto(key)
            assert "s" in footer_keys(app), f"{key} missing skip key"


async def test_no_free_hides_type_key(store: Store, project: str) -> None:
    store.ask(
        "no free text here", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")], allow_free=False,
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "i" not in footer_keys(app)
        assert "i type" not in card_hint(app)


async def test_digit_answers_choice_row(store: Store, project: str) -> None:
    q = store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    fresh = store.get(q.key, project=project)
    assert fresh.status == "answered"
    assert fresh.answer.selected == ["a"]


async def test_projects_pane_open_ignore_activate_close(store: Store, project: str) -> None:
    store.ask("hi", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.projects_open is False

        await pilot.press("P")
        await pilot.pause()
        assert app.projects_open is True

        await pilot.press("I")
        await pilot.pause()
        assert store.project_enabled(project) is False

        await pilot.press("A")
        await pilot.pause()
        assert store.project_enabled(project) is True

        await pilot.press("P")
        await pilot.pause()
        assert app.projects_open is False


async def test_projects_pane_escape_closes(store: Store, project: str) -> None:
    store.ask("hi", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        assert app.projects_open is True

        await pilot.press("escape")
        await pilot.pause()
        assert app.projects_open is False


async def test_typing_blocks_projects_pane_and_letters_land_in_input(
    store: Store, project: str
) -> None:
    store.ask("type here", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert app.free_text_mode is True

        before = store.project_enabled(project)
        await pilot.press("P")
        await pilot.pause()
        assert app.projects_open is False

        await pilot.press("I")
        await pilot.pause()
        assert store.project_enabled(project) is before

        await pilot.press("A")
        await pilot.pause()
        assert store.project_enabled(project) is before

        from textual.widgets import Input
        assert app.query_one("#answer-input", Input).value == "PIA"


async def test_undo_reopens_answered_row(store: Store, project: str) -> None:
    q = store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        assert store.get(q.key, project=project).status == "answered"

        await pilot.press("u")
        await pilot.pause()

    assert store.get(q.key, project=project).status == "open"


async def test_empty_multi_submit_records_nothing_and_flashes(store: Store, project: str) -> None:
    q = store.ask(
        "pick some", project=project, cwd=project, agent=AGENT,
        kind="multi", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    fresh = store.get(q.key, project=project)
    assert fresh.status == "open"
    assert fresh.answer is None
    assert app.flash
