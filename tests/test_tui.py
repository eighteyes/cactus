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

# The projects pane (P / I / A) is a separate change; until it lands these
# tests skip rather than fail, and start running the moment it does.
needs_projects_pane = pytest.mark.skipif(
    not hasattr(CactusApp, "action_open_projects"),
    reason="projects pane not in this checkout",
)

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


@needs_projects_pane
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


@needs_projects_pane
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


@needs_projects_pane
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


async def test_visit_binds_only_on_a_row_with_a_pane(store: Store, project: str) -> None:
    store.ask("stamped", project=project, cwd=project, agent=AGENT, pane="w1:p1")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "v" in footer_keys(app)
        await pilot.press("v")
        await pilot.pause()
        assert app.flash == "visited w1:p1"


async def test_visit_flashes_on_a_row_posted_outside_herdr(store: Store, project: str) -> None:
    q = store.ask("unstamped", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "v" not in footer_keys(app)
        await pilot.press("v")
        await pilot.pause()
        assert app.flash == f"{q.key} was posted outside herdr; nothing to visit"


def _logging_script(tmp_path: Path) -> tuple[Path, Path]:
    """A tiny shell script that appends its argv to a log file."""
    log = tmp_path / "log.txt"
    script = tmp_path / "logit.sh"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    script.chmod(0o755)
    return script, log


async def test_footer_shows_f_and_ff_only_on_a_row_with_files(store: Store, project: str) -> None:
    store.ask("no files", project=project, cwd=project, agent=AGENT)
    store.ask("has files", project=project, cwd=project, agent=AGENT, files=["/tmp/x"])

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "f" not in footer_keys(app)

        await pilot.press("j")
        await pilot.pause()
        assert "f" in footer_keys(app)


async def test_view_file_flashes_when_row_carries_no_file(store: Store, project: str) -> None:
    q = store.ask("no files", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert app.flash == f"{q.key} carries no file"


async def test_view_file_one_file_row_calls_pager_immediately(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script, log = _logging_script(tmp_path)
    monkeypatch.setenv("CACTUS_PAGER", f"{script} {{path}}")

    target = tmp_path / "a.txt"
    target.write_text("hi")
    store.ask("one file", project=project, cwd=project, agent=AGENT, files=[str(target)])

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()

    assert log.read_text().strip() == str(target)


async def test_view_edit_two_file_row_digit_picks_the_file(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script, log = _logging_script(tmp_path)
    monkeypatch.setenv("CACTUS_PAGER", f"{script} {{path}}")
    monkeypatch.setenv("CACTUS_EDITOR", f"{script} {{path}}")

    one = tmp_path / "one.txt"
    one.write_text("1")
    two = tmp_path / "two.txt"
    two.write_text("2")
    q = store.ask(
        "two files", project=project, cwd=project, agent=AGENT, files=[str(one), str(two)],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()
        assert app.file_pending == "view"
        await pilot.press("2")
        await pilot.pause()
        assert app.file_pending is None

        await pilot.press("F")
        await pilot.pause()
        assert app.file_pending == "edit"
        await pilot.press("1")
        await pilot.pause()
        assert app.file_pending is None

    lines = [line.strip() for line in log.read_text().splitlines()]
    assert lines == [str(two), str(one)]
    assert f"{q.key} has no file" not in app.flash


async def test_view_file_disarmed_by_an_unrelated_key(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script, log = _logging_script(tmp_path)
    monkeypatch.setenv("CACTUS_PAGER", f"{script} {{path}}")

    one = tmp_path / "one.txt"
    one.write_text("1")
    two = tmp_path / "two.txt"
    two.write_text("2")
    store.ask("two files", project=project, cwd=project, agent=AGENT, files=[str(one), str(two)])

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert app.file_pending == "view"

        await pilot.press("j")
        await pilot.pause()
        assert app.file_pending is None

    assert not log.exists()


async def test_view_file_out_of_range_digit_flashes(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script, log = _logging_script(tmp_path)
    monkeypatch.setenv("CACTUS_PAGER", f"{script} {{path}}")

    one = tmp_path / "one.txt"
    one.write_text("1")
    two = tmp_path / "two.txt"
    two.write_text("2")
    q = store.ask("two files", project=project, cwd=project, agent=AGENT, files=[str(one), str(two)])

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()
        assert app.flash == f"{q.key} has no file 9"
        assert app.file_pending is None

    assert not log.exists()


async def test_card_shows_numbered_file_list(store: Store, project: str) -> None:
    store.ask(
        "files here", project=project, cwd=project, agent=AGENT,
        files=["/tmp/a", "/tmp/b"],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        text = str(app.query_one("#card", Static).content)

    assert f"  {'files':<8}1 /tmp/a" in text
    assert f"  {'':<8}2 /tmp/b" in text

