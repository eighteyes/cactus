"""
test_tui.py — CactusApp footer, key bar, projects pane, and answering behavior.

Responsibilities:
- The Footer shows only global keys — never y/n/digits/d/s/i/etc, which are
  row-dependent and live in the in-card key bar instead.
- The key bar (`_keybar_items`) enumerates a row's own keys by kind: choice
  labels, confirm's own y/n labels, plan steps, data chunks; a --no-free row
  hides "i type" from the bar the same way it hides `i` from `check_action`.
- Digit keys answer a choice row.
- The projects pane opens/closes with `P`/escape and `I`/`A` flip a project's
  enabled switch, but only while not typing.
- Undo restores an answered row to open.
- An empty multi submit records nothing and flashes instead.
- Answering drops a block onto the pachinko field; clearing a row does not.
- Backtick drops a seed anytime except while typing, empty inbox included, or
  (with the field hidden) toggles pile-only instead; tilde always toggles the
  field itself.
- The card is always displayed, showing the empty-state message with an
  empty store; the field lives inside it, sized to the card's remaining
  height once the text and key bar rows are accounted for.
- Card first: the card's content gets every row it needs in both
  orientations; the field (pile-only too) takes the leftover and hides below
  4 rows. The key bar is centred and a seed drops under the key pressed.
- The auto worker proposes (never answers) on gated rows and holds the rest;
  the card shows `[..] label - reason`, and `A` accepts it like the digit.
- The garden (the landed pile) is shared and persisted: it survives a
  restart and stays in sync across every TUI on the same database.
- The field child (`ProcessField`) streams changed rows, lands a seed,
  writes the garden itself, and stops with no process left behind; the
  Line-API `FieldView` matches the old Static output cell for cell and
  repaints only changed rows; a process-mode app paints the child's frames.
"""

from __future__ import annotations

import asyncio
import random
import select
import time
from pathlib import Path

import pytest
from textual.widgets import Footer, Input, ListView, Static
from textual.widgets._footer import FooterKey

from cactus import garden
from cactus.field import World
from cactus.fieldproc import ProcessField, text_rows
from cactus.store import Choice, Store
from cactus.tui import CactusApp, FieldView, QuestionBlock

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


def keybar_keys(app: CactusApp) -> dict[str, str]:
    """The focused row's key bar items, as `_keybar_items` builds them."""
    return dict(app._keybar_items(app._current_question()))


def card_hint(app: CactusApp) -> str:
    text = str(app.query_one("#card-text", Static).content)
    lines = text.strip().splitlines()
    return lines[-1] if lines else ""


async def test_keybar_enumerates_review_run_plan_data_choice(store: Store, project: str) -> None:
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
        keys = keybar_keys(app)
        assert keys["y"] == "pass"
        assert keys["n"] == "fail"
        assert "y" not in footer_keys(app)

        await goto(run_key)
        keys = keybar_keys(app)
        assert keys["y"] == "approve"
        assert keys["n"] == "deny"

        await goto(plan_key)
        keys = keybar_keys(app)
        assert keys["1"] == "s1"
        assert keys["2"] == "s2"
        assert "1" not in footer_keys(app)

        await goto(data_key)
        keys = keybar_keys(app)
        assert keys["1"] == "one"
        assert keys["d"] == "close"
        assert "d" not in footer_keys(app)

        await goto(choice_key)
        keys = keybar_keys(app)
        assert keys["1"] == "a"
        assert keys["2"] == "b"


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
            assert "s" in keybar_keys(app), f"{key} missing skip key"
            assert "s" not in footer_keys(app)


async def test_no_free_hides_type_key(store: Store, project: str) -> None:
    store.ask(
        "no free text here", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")], allow_free=False,
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "i" not in footer_keys(app)
        assert "i" not in keybar_keys(app)
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


async def test_blocking_acp_row_is_labeled_and_raised(store: Store, project: str) -> None:
    ordinary = store.ask("ordinary", project=project, cwd=project, agent=AGENT)
    acp = store.ask(
        "ACP needs this", project=project, cwd=project, agent=AGENT,
        blocked=True, source="acp",
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.questions[0].key == acp.key
        row = app.query_one(f"#row-{acp.key}", QuestionBlock)
        assert "BLOCKING · ACP" in str(row._text.content)
        assert app.questions[1].key == ordinary.key


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
        assert "v" in keybar_keys(app)
        assert "v" not in footer_keys(app)
        await pilot.press("v")
        await pilot.pause()
        assert app.flash == "visited w1:p1"


async def test_visit_flashes_on_a_row_posted_outside_herdr(store: Store, project: str) -> None:
    q = store.ask("unstamped", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "v" not in keybar_keys(app)
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


async def test_keybar_shows_f_and_ff_only_on_a_row_with_files(store: Store, project: str) -> None:
    store.ask("no files", project=project, cwd=project, agent=AGENT)
    store.ask("has files", project=project, cwd=project, agent=AGENT, files=["/tmp/x"])

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "f" not in keybar_keys(app)
        assert "f" not in footer_keys(app)

        await pilot.press("j")
        await pilot.pause()
        assert "f" in keybar_keys(app)
        assert "f" not in footer_keys(app)


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
        text = str(app.query_one("#card-text", Static).content)

    assert f"  {'files':<8}1 /tmp/a" in text
    assert f"  {'':<8}2 /tmp/b" in text


async def test_answering_choice_drops_a_field_seed(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.world.seeds
        await pilot.press("1")
        await pilot.pause()
        assert len(app.world.seeds) == 1


async def test_clear_drops_no_field_seed(store: Store, project: str) -> None:
    store.ask("pick one", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert not app.world.seeds


async def test_field_column_matches_the_keybar_glyph(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b"), Choice("c")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Each digit now has its own key bar column, so "2" sits to the
        # right of "1" — a choice row enumerates its choices left to right.
        col_1 = app._field_column("1")
        col_2 = app._field_column("2")
        assert col_2 > col_1


def _keybar_centre_check(app: CactusApp) -> int:
    """Assert the key bar is centred and "1"'s recorded column is its glyph's
    screen column in `#field`; return that column."""
    bar = app.query_one("#keybar", Static)
    field = app.query_one("#field")
    line = str(bar.content)
    body = line.lstrip(" ")
    pad = len(line) - len(body)
    assert pad == (bar.size.width - len(body)) // 2
    assert pad > 0
    col = app._keybar_x["1"]
    assert bar.content_region.x + line.index("1 ") == field.region.x + col
    return col


@pytest.mark.parametrize("orientation, width", [("bottom", 100), ("side", 200)])
async def test_keybar_is_centred_and_a_seed_drops_under_the_key(
    store: Store, project: str, orientation: str, width: int,
) -> None:
    """The key bar sits mid-card so the digits drop seeds mid-field; the
    column `_keybar_x` records is the pressed glyph's own screen column.
    Side at 100 columns leaves the bar no slack to centre in (it fills and
    truncates), so side runs wider."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    app.tui_settings["orientation"] = orientation
    async with app.run_test(size=(width, 40)) as pilot:
        await _settle(pilot)
        col = _keybar_centre_check(app)
        assert app._field_column("1") == col
        # Record the spawn column itself: the seed drifts on the wind as
        # soon as the field ticks, so its later x says nothing about the drop.
        dropped: list[int] = []
        real_drop = app.world.drop
        app.world.drop = lambda c: (dropped.append(c), real_drop(c))[1]
        await pilot.press("1")
        await pilot.pause()
        assert dropped == [col]
        assert len(app.world.seeds) == 1


async def test_seed_release_right_mirrors_the_drop_column(store: Store, project: str) -> None:
    """`seed_release`: the default `left` drops a seed under the pressed
    key's glyph; `right` drops it at the mirrored column, `width - 1 - col`,
    while the key bar itself stays put."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    app.tui_settings["orientation"] = "bottom"
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        assert app.tui_settings["seed_release"] == "left"
        col = app._keybar_x["1"]
        width = app.query_one("#field").size.width
        assert app._field_column("1") == col

        app.tui_settings["seed_release"] = "right"
        dropped: list[int] = []
        real_drop = app.world.drop
        app.world.drop = lambda c: (dropped.append(c), real_drop(c))[1]
        await pilot.press("1")
        await pilot.pause()
        assert dropped == [width - 1 - col]
        assert width - 1 - col != col


async def test_seed_release_settings_toggle_persists(store: Store, project: str) -> None:
    store.ask("hi", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        assert app.tui_settings["seed_release"] == "right"

    second = CactusApp(store, project=project)
    async with second.run_test() as pilot:
        await pilot.pause()
        assert second.tui_settings["seed_release"] == "right"


async def test_keybar_recentres_on_resize(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    app.tui_settings["orientation"] = "bottom"
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        before = _keybar_centre_check(app)
        await pilot.resize_terminal(140, 40)
        await _settle(pilot)
        assert _keybar_centre_check(app) > before


@pytest.mark.parametrize("align", ["left", "center", "right"])
async def test_keybar_align_places_the_glyph_and_the_seed(
    store: Store, project: str, align: str,
) -> None:
    """`keybar_align` pads the bar left (0), center (half the slack) or
    right (all of it) at 200 columns; "1"'s recorded column is its glyph's
    screen column and a seed from "1" spawns there."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    app.tui_settings["orientation"] = "side"
    app.tui_settings["keybar_align"] = align
    async with app.run_test(size=(200, 40)) as pilot:
        await _settle(pilot)
        bar = app.query_one("#keybar", Static)
        field = app.query_one("#field")
        line = str(bar.content)
        body = line.lstrip(" ")
        pad = len(line) - len(body)
        slack = bar.size.width - len(body)
        assert slack > 0
        assert pad == {"left": 0, "center": slack // 2, "right": slack}[align]
        col = app._keybar_x["1"]
        assert bar.content_region.x + line.index("1 ") == field.region.x + col
        assert col == bar.styles.gutter.left + pad
        dropped: list[int] = []
        real_drop = app.world.drop
        app.world.drop = lambda c: (dropped.append(c), real_drop(c))[1]
        await pilot.press("1")
        await pilot.pause()
        assert dropped == [col]


async def test_keybar_align_settings_cycle_persists(store: Store, project: str) -> None:
    """Settings `5` cycles center -> right -> left, re-pads the bar at once,
    and a fresh app reads the saved value back."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    async with app.run_test(size=(200, 40)) as pilot:
        await _settle(pilot)
        assert app.tui_settings["keybar_align"] == "center"
        await pilot.press("?")
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        assert app.tui_settings["keybar_align"] == "right"
        await pilot.press("5")
        await pilot.pause()
        assert app.tui_settings["keybar_align"] == "left"
        await pilot.press("escape")
        await _settle(pilot)
        assert app._keybar_x["1"] == app.query_one("#keybar", Static).styles.gutter.left

    second = CactusApp(store, project=project)
    async with second.run_test() as pilot:
        await pilot.pause()
        assert second.tui_settings["keybar_align"] == "left"


@pytest.mark.parametrize("release", ["left", "right"])
@pytest.mark.parametrize("align", ["left", "center", "right"])
async def test_keybar_order_choices_last_moves_digits_and_the_seed(
    store: Store, project: str, align: str, release: str,
) -> None:
    """`keybar_order = "choices_last"` puts the numbered keys after every
    other key; "1"'s recorded column is still its glyph's screen column, so
    a seed from "1" drops under it (or at the mirror under `right`)."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    app.tui_settings["orientation"] = "side"
    app.tui_settings["keybar_align"] = align
    app.tui_settings["seed_release"] = release
    app.tui_settings["keybar_order"] = "choices_last"
    async with app.run_test(size=(200, 40)) as pilot:
        await _settle(pilot)
        keys = [k for k, _ in app._keybar_items(app._current_question())]
        assert keys[-5:] == ["1", "2", "3", "4", "5"]
        bar = app.query_one("#keybar", Static)
        field = app.query_one("#field")
        line = str(bar.content)
        assert line.index("1 a") > line.index("c clear")
        assert line.index("1 a") > line.index("` seed")
        col = app._keybar_x["1"]
        assert bar.content_region.x + line.index("1 a") == field.region.x + col
        width = field.size.width
        dropped: list[int] = []
        real_drop = app.world.drop
        app.world.drop = lambda c: (dropped.append(c), real_drop(c))[1]
        await pilot.press("1")
        await pilot.pause()
        assert dropped == [col if release == "left" else width - 1 - col]


async def test_keybar_order_settings_toggle_persists(store: Store, project: str) -> None:
    """Settings `6` flips choices_first -> choices_last, re-lays the bar at
    once, and a fresh app reads the saved value back."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice(c) for c in "abcde"],
    )

    app = CactusApp(store, project=project)
    async with app.run_test(size=(200, 40)) as pilot:
        await _settle(pilot)
        assert app.tui_settings["keybar_order"] == "choices_first"
        first_col = app._keybar_x["1"]
        await pilot.press("?")
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause()
        assert app.tui_settings["keybar_order"] == "choices_last"
        await pilot.press("escape")
        await _settle(pilot)
        assert app._keybar_x["1"] > first_col

    second = CactusApp(store, project=project)
    async with second.run_test() as pilot:
        await pilot.pause()
        assert second.tui_settings["keybar_order"] == "choices_last"


async def test_field_column_enter_falls_back_to_i(store: Store, project: str) -> None:
    """A plan row's key bar offers "i note" but no "enter" item of its own —
    `_field_column("enter")` should fall back to "i"'s column rather than
    landing on a random one."""
    q = store.ask(
        "plan this", project=project, cwd=project, agent=AGENT, kind="text", act="plan",
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "enter" not in dict(app._keybar_items(q))
        assert app._field_column("enter") == app._field_column("i")


async def test_teardown_with_a_seed_in_flight_does_not_raise(store: Store, project: str) -> None:
    """Exiting run_test with a seed still falling and the sky timer still
    running must not leak an exception or leave a dangling timer."""
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert app._field_timer is None


async def test_render_field_after_widget_removed_stops_the_timer(store: Store, project: str) -> None:
    store.ask("pick one", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#field").remove()
        await pilot.pause()
        app._render_field()
        assert app._field_timer is None


async def test_backtick_drops_a_seed_on_any_row(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.world.seeds
        await pilot.press("grave_accent")
        await pilot.pause()
        assert len(app.world.seeds) == 1


async def test_tilde_toggles_the_field(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.tui_settings["field"] is True
        await pilot.press("tilde")
        await pilot.pause()
        assert app.tui_settings["field"] is False
        assert app.query_one("#field").display is False


async def test_backtick_drops_a_seed_with_an_empty_inbox(store: Store, project: str) -> None:
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.questions
        await pilot.press("grave_accent")
        await pilot.pause()
        assert len(app.world.seeds) == 1


async def test_backtick_in_free_text_mode_types_instead_of_dropping(store: Store, project: str) -> None:
    store.ask("say something", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert app.free_text_mode
        await pilot.press("grave_accent")
        await pilot.pause()
        assert not app.world.seeds
        assert "`" in app.query_one("#answer-input", Input).value


async def test_landing_persists_and_a_second_app_loads_the_same_garden(store: Store, project: str) -> None:
    store.ask("pick one", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.world.structure[(1, 0)] = 0
        app.world.drops = 1
        app.world.landed_since_save = 1
        app._save_garden()
        assert app._garden_path.exists()
        assert app.world.landed_since_save == 0

    other = CactusApp(store, project=project)
    async with other.run_test() as pilot:
        await pilot.pause()
        assert other.world.structure == {(1, 0): 0}
        assert other.world.drops == 1


async def test_external_garden_write_is_reloaded_after_a_poll(store: Store, project: str) -> None:
    store.ask("pick one", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        other_world = World(cols=5, rows=5)
        other_world.structure[(2, 0)] = 0
        other_world.drops = 1
        time.sleep(0.01)  # a distinct mtime from whatever on_mount already wrote
        garden.save(other_world, app._garden_path)
        app._sky_reload_last = None  # force the poll clock to fire on the next tick
        app._field_tick()
        assert app.world.structure == {(2, 0): 0}
        assert app.flash == "garden updated"


async def test_tilde_hides_field_and_persists_setting(store: Store, project: str) -> None:
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tilde")
        await pilot.pause()
        assert app.tui_settings["field"] is False

    second = CactusApp(store, project=project)
    async with second.run_test() as pilot:
        await pilot.pause()
        assert second.tui_settings["field"] is False


async def test_backtick_toggles_pile_only_when_field_hidden(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tilde")
        await pilot.pause()
        assert app.tui_settings["field"] is False
        assert app.tui_settings["pile_only"] is False

        await pilot.press("grave_accent")
        await pilot.pause()
        assert not app.world.seeds
        assert app.tui_settings["pile_only"] is True
        assert app.query_one("#field").display is True

        await pilot.press("tilde")
        await pilot.pause()
        assert app.tui_settings["field"] is True
        await pilot.press("grave_accent")
        await pilot.pause()
        assert len(app.world.seeds) == 1


# The answers view and projects pane (sublists) are a separate change; until
# they land these tests skip rather than fail, and start running the moment
# they do — same reasoning as `needs_projects_pane`.
needs_sublists = pytest.mark.skipif(
    not hasattr(CactusApp, "action_open_answers"),
    reason="answers view / projects pane not in this checkout",
)


@pytest.fixture(autouse=True)
def _isolated_tui_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`_tui_settings_path` reads/writes real `~/.config/cactus/tui.json` by
    default; any test that flips a persisted setting (orientation, figlet, the
    projects pane) must never touch the human's own file.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


@needs_sublists
async def test_projects_pane_shows_due_ranked_projects_marks_current(
    store: Store, project: str, tmp_path: Path
) -> None:
    busier = tmp_path / "busier"
    busier.mkdir()
    busier_project = str(busier)
    store.ask("only one due", project=project, cwd=project, agent=AGENT)
    for _ in range(3):
        store.ask("busier", project=busier_project, cwd=busier_project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        text = str(app.query_one("#projects-pane", Static).content)

    lines = [l for l in text.splitlines() if l.strip()]
    # Busiest project (3 due) ranks before the current one (1 due), which
    # still carries the ▸ marker even though it isn't first.
    assert lines[0].strip().endswith("3")
    assert any(l.startswith("▸") and l.strip().endswith("1") for l in lines)


@needs_sublists
async def test_projects_pane_hidden_in_bottom_orientation(store: Store, project: str) -> None:
    store.ask("hi", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#projects-pane", Static).display is True

        await pilot.press("?")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert app.query_one("#projects-pane", Static).display is False


@needs_sublists
async def test_projects_pane_settings_toggle_persists(
    store: Store, project: str
) -> None:
    store.ask("hi", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.tui_settings["projects_pane"] is True

        await pilot.press("?")
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert app.tui_settings["projects_pane"] is False
        assert app.query_one("#projects-pane", Static).display is False

    second = CactusApp(store, project=project)
    async with second.run_test() as pilot:
        await pilot.pause()
        assert second.tui_settings["projects_pane"] is False


@needs_sublists
async def test_answers_view_opens_shows_history_closes_on_a(
    store: Store, project: str
) -> None:
    answered = store.ask("answer me", project=project, cwd=project, agent=AGENT)
    store.answer(answered.key, project=project, text="yep")
    cleared = store.ask("clear me", project=project, cwd=project, agent=AGENT)
    store.answer(cleared.key, project=project, text="verdict")
    store.clear(keys=[cleared.key], project=project)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.answers_open is False

        await pilot.press("a")
        await pilot.pause()
        assert app.answers_open is True
        text = str(app.query_one("#answers-panel", Static).content)
        assert answered.key in text
        assert cleared.key in text
        assert "cleared" in text

        await pilot.press("escape")
        await pilot.pause()
        assert app.answers_open is False


@needs_sublists
async def test_answers_view_enter_expands_selected_row(store: Store, project: str) -> None:
    q = store.ask("expand me", project=project, cwd=project, agent=AGENT, context="the context")
    store.answer(q.key, project=project, text="the verdict")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert "the context" not in str(app.query_one("#answers-panel", Static).content)

        await pilot.press("enter")
        await pilot.pause()
        assert app.answers_expanded is True
        assert "the context" in str(app.query_one("#answers-panel", Static).content)

        await pilot.press("enter")
        await pilot.pause()
        assert app.answers_expanded is False


@needs_sublists
async def test_answers_view_brackets_rotate_project(
    store: Store, project: str, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    other_project = str(other)
    here = store.ask("here", project=project, cwd=project, agent=AGENT)
    store.answer(here.key, project=project, text="ok")
    elsewhere = store.ask("elsewhere", project=other_project, cwd=other_project, agent=AGENT)
    store.answer(elsewhere.key, project=other_project, text="ok")

    app = CactusApp(store, project=None)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.current_project = project
        await pilot.press("a")
        await pilot.pause()
        assert [q.key for q in app.answers_rows] == [here.key]

        await pilot.press("]")
        await pilot.pause()
        assert app.current_project == other_project
        assert [q.key for q in app.answers_rows] == [elsewhere.key]


@needs_sublists
async def test_typing_blocks_answers_view_and_letters_land_in_input(
    store: Store, project: str
) -> None:
    store.ask("type here", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert app.free_text_mode is True

        await pilot.press("a")
        await pilot.pause()
        assert app.answers_open is False

        from textual.widgets import Input
        assert app.query_one("#answer-input", Input).value == "a"


@needs_sublists
async def test_opening_projects_and_answers_panels_are_mutually_exclusive(
    store: Store, project: str
) -> None:
    q = store.ask("hi", project=project, cwd=project, agent=AGENT)
    store.answer(q.key, project=project, text="ok")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert app.answers_open is True

        await pilot.press("P")
        await pilot.pause()
        assert app.answers_open is False
        assert app.projects_open is True
        assert app.query_one("#answers-panel", Static).display is False


def _poke_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Swap the inert transport for one that logs `{target}|{message}` per call."""
    log = tmp_path / "poke.log"
    script = tmp_path / "poke.sh"
    script.write_text(f'#!/bin/sh\necho "$1|$2" >> {log}\n')
    script.chmod(0o755)
    monkeypatch.setenv("CACTUS_POKE", f"{script} {{target}} {{message}}")
    return log


async def test_projects_page_p_pokes_every_pane_in_the_project(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cactus.tui import PROJECT_POKE_MESSAGE

    log = _poke_log(tmp_path, monkeypatch)
    for agent, pane in (("a1", "w1:p1"), ("a1", "w1:p1"), ("a2", "w1:p2"), ("a3", None)):
        store.ask("hi", project=project, cwd=project, agent=agent, kind="text",
                  act="ask", pane=pane)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert app.flash == "poked 2 panes in proj"

    calls = log.read_text().splitlines()
    assert sorted(c.split("|", 1)[0] for c in calls) == ["w1:p1", "w1:p2"]
    assert all(c.split("|", 1)[1] == PROJECT_POKE_MESSAGE for c in calls)


async def test_projects_page_p_flashes_when_project_has_no_panes(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _poke_log(tmp_path, monkeypatch)
    store.ask("hi", project=project, cwd=project, agent=AGENT, kind="text", act="ask")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert app.flash == "proj: no herdr panes (1 rows unstamped)"

    assert not log.exists()


async def test_inbox_p_still_pokes_only_the_focused_row(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _poke_log(tmp_path, monkeypatch)
    store.ask("one", project=project, cwd=project, agent="a1", kind="text",
              act="ask", pane="w1:p1")
    store.ask("two", project=project, cwd=project, agent="a2", kind="text",
              act="ask", pane="w1:p2")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

    calls = log.read_text().splitlines()
    assert len(calls) == 1
    assert "re-read your answers" not in calls[0]


async def test_seed_dropped_by_a_digit_lands_inside_the_field(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert len(app.world.seeds) == 1
    assert 0 <= app.world.seeds[0].x < app.world.width


async def test_card_is_displayed_with_an_empty_store(store: Store, project: str) -> None:
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.questions
        card = app.query_one("#card")
        assert card.display is not False
        text = str(app.query_one("#card-text", Static).content)
        assert "inbox empty" in text
        # The key bar still shows the always-reachable seed key.
        assert "`" in keybar_keys(app)


async def test_field_height_fills_the_card_beneath_text_and_keybar(store: Store, project: str) -> None:
    store.ask(
        "pick one", project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )

    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        card = app.query_one("#card")
        text = app.query_one("#card-text", Static)
        field = app.query_one("#field")
        keybar = app.query_one("#keybar", Static)
        assert field.size.height == card.size.height - text.size.height - keybar.size.height


def _ask_context(store: Store, project: str, text: str, lines: int) -> None:
    context = "\n".join(f"context line {i}" for i in range(lines)) if lines else None
    store.ask(
        text, project=project, cwd=project, agent=AGENT, context=context,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )


async def _settle(pilot) -> None:
    # One pause lays the card out; the field re-fit runs after that refresh.
    await pilot.pause()
    await pilot.pause()


def _card_fills_column(app: CactusApp) -> bool:
    """The card text takes every row of the card above the key bar."""
    card = app.query_one("#card")
    text = app.query_one("#card-text", Static)
    keybar = app.query_one("#keybar", Static)
    return text.outer_size.height == card.content_size.height - keybar.outer_size.height


async def test_short_question_gets_its_rows_and_the_field_the_rest(store: Store, project: str) -> None:
    """Card first: a short card shows every line, the field takes the rest."""
    _ask_context(store, project, "short one", 0)

    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        card = app.query_one("#card")
        text = app.query_one("#card-text", Static)
        field = app.query_one("#field")
        keybar = app.query_one("#keybar", Static)
        assert text.region.height >= text.virtual_size.height
        assert text.region.height >= len(str(text.content).splitlines())
        assert field.display is True
        assert field.size.height > 10
        assert field.size.height == card.content_size.height - text.outer_size.height - keybar.outer_size.height
        assert (app.world.cols, app.world.rows) == (field.size.width, field.size.height)


async def test_mid_question_fits_whole_and_shrinks_the_field(store: Store, project: str) -> None:
    """A card that still fits shows every line; the field shrinks to make room."""
    _ask_context(store, project, "short one", 0)
    _ask_context(store, project, "mid one", 12)
    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        short_field = app.query_one("#field").size.height
        await pilot.press("j")
        await _settle(pilot)
        assert app._current_question().text == "mid one"
        card = app.query_one("#card")
        text = app.query_one("#card-text", Static)
        field = app.query_one("#field")
        assert text.region.height >= text.virtual_size.height
        assert card.region.contains_region(text.region)
        assert 0 < field.size.height < short_field
        assert (app.world.cols, app.world.rows) == (field.size.width, field.size.height)


async def test_long_question_takes_the_card_and_hides_the_field(store: Store, project: str) -> None:
    """30 context lines at 100x40: the card keeps every row it can use and
    the field yields — smaller than the short case, or hidden."""
    _ask_context(store, project, "short one", 0)
    _ask_context(store, project, "long one", 30)

    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        short_field = app.query_one("#field").size.height
        await pilot.press("j")
        await _settle(pilot)
        assert app._current_question().text == "long one"
        card = app.query_one("#card")
        text = app.query_one("#card-text", Static)
        field = app.query_one("#field")
        assert card.region.contains_region(text.region)
        assert text.region.height >= min(text.virtual_size.height, card.content_size.height - 1)
        assert field.display is False or field.size.height < short_field
        if text.virtual_size.height > text.region.height:
            assert _card_fills_column(app)
            assert field.display is False


async def test_too_long_question_hides_the_field_and_fills_the_column(store: Store, project: str) -> None:
    _ask_context(store, project, "long one", 30)

    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 24)) as pilot:
        await _settle(pilot)
        field = app.query_one("#field")
        assert field.display is False or field.size.height == 0
        assert _card_fills_column(app)
        # The key bar still sits on the card's last content row.
        card = app.query_one("#card")
        keybar = app.query_one("#keybar", Static)
        assert keybar.region.bottom == card.content_region.bottom


async def test_moving_to_a_short_row_gives_the_field_its_rows_back(store: Store, project: str) -> None:
    _ask_context(store, project, "long one", 30)
    _ask_context(store, project, "short one", 0)

    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        assert app._current_question().text == "long one"
        assert app.query_one("#field").display is False
        await pilot.press("j")
        await _settle(pilot)
        assert app._current_question().text == "short one"
        field = app.query_one("#field")
        assert field.display is True
        assert field.size.height > 10
        assert (app.world.cols, app.world.rows) == (field.size.width, field.size.height)
        await pilot.press("k")
        await _settle(pilot)
        assert app.query_one("#field").display is False


async def test_bottom_orientation_is_card_first_too(store: Store, project: str) -> None:
    _ask_context(store, project, "long one", 30)
    _ask_context(store, project, "short one", 0)

    app = CactusApp(store, project=project)
    app.tui_settings["orientation"] = "bottom"
    async with app.run_test(size=(100, 40)) as pilot:
        await _settle(pilot)
        assert app.query_one("#field").display is False
        assert _card_fills_column(app)
        await pilot.press("j")
        await _settle(pilot)
        text = app.query_one("#card-text", Static)
        field = app.query_one("#field")
        assert text.region.height >= text.virtual_size.height
        assert field.display is True
        assert field.size.height >= 4


async def test_pile_only_yields_to_the_card(store: Store, project: str) -> None:
    """Pile-only sizes to the pile's rows, but only in rows the card leaves."""
    _ask_context(store, project, "long one", 30)
    _ask_context(store, project, "short one", 0)

    app = CactusApp(store, project=project)
    app.tui_settings["field"] = False
    app.tui_settings["pile_only"] = True
    async with app.run_test(size=(100, 24)) as pilot:
        await _settle(pilot)
        assert app.query_one("#field").display is False
        assert _card_fills_column(app)
        await pilot.press("j")
        await _settle(pilot)
        field = app.query_one("#field")
        assert field.display is True
        assert field.size.height == app.world.pile_rows()


async def test_sky_config_reload_updates_the_running_world(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cactus.sky import SkyConfig

    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))
    SkyConfig().dump(path)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.world.sky.config.far.growth == SkyConfig().far.growth

        changed = SkyConfig().overlay({"far": {"growth": 0.5}})
        changed.dump(path)
        await pilot.pause(2.5)
        assert app.world.sky.config.far.growth == 0.5


async def test_tuning_overlay_opens_shows_first_key(store: Store, project: str) -> None:
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert app.tuning_open is True
        assert app.query_one("#tuning-panel", Static).display is True
        assert app.tuning_index == 0
        first = app.tuning_rows[0]
        assert first.name in app._tuning_text()


async def test_tuning_overlay_nudge_updates_config_and_file(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cactus.sky import SkyConfig

    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        row = app.tuning_rows[0]
        before = getattr(app._tuning_obj(row.group), row.name)

        await pilot.press("l")
        await pilot.pause()

        after = getattr(app._tuning_obj(row.group), row.name)
        assert after != before
        on_disk = SkyConfig.load(path)
        disk_obj = on_disk if row.group == "shared" else getattr(on_disk, row.group)
        assert getattr(disk_obj, row.name) == after


async def test_tuning_overlay_reset_restores_default(store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cactus.sky import SkyConfig

    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        idx = next(i for i, r in enumerate(app.tuning_rows) if r.step is not None)
        for _ in range(idx):
            await pilot.press("j")
        await pilot.pause()
        row = app.tuning_rows[idx]
        default_cfg = SkyConfig()
        default_obj = default_cfg if row.group == "shared" else getattr(default_cfg, row.group)
        default_value = getattr(default_obj, row.name)

        await pilot.press("l")
        await pilot.press("l")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) != default_value

        await pilot.press("r")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) == default_value


async def test_tuning_overlay_pile_style_cycles_with_h_l(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v6d: `pile_style` has no numeric step, so `h`/`l` cycle between its
    two `choices` instead of nudging by an amount — and the cycle still
    writes through to the config file like a numeric nudge does."""
    from cactus.sky import SkyConfig

    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        idx = next(i for i, row in enumerate(app.tuning_rows) if row.name == "pile_style")
        app.tuning_index = idx
        app._render_tuning()
        assert app.world.sky.config.pile_style == "dots"

        await pilot.press("l")
        await pilot.pause()
        assert app.world.sky.config.pile_style == "blocks"

        await pilot.press("l")
        await pilot.pause()
        assert app.world.sky.config.pile_style == "dots"

        await pilot.press("h")
        await pilot.pause()
        assert app.world.sky.config.pile_style == "blocks"

        assert SkyConfig.load(path).pile_style == "blocks"


async def test_tuning_overlay_escape_closes_and_keeps_nudge(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        row = app.tuning_rows[0]
        before = getattr(app._tuning_obj(row.group), row.name)

        await pilot.press("l")
        await pilot.pause()
        nudged = getattr(app._tuning_obj(row.group), row.name)
        assert nudged != before

        await pilot.press("escape")
        await pilot.pause()
        assert app.tuning_open is False
        assert app.query_one("#tuning-panel", Static).display is False
        assert getattr(app._tuning_obj(row.group), row.name) == nudged


async def test_tuning_overlay_save_and_recall_slot(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v6g: `S` then a digit saves the live config to that slot; a bare
    digit recalls it, applying live and rewriting sky.toml. `r` (reset)
    then recalling the same slot brings the nudged value back."""
    from cactus.sky import SkyConfig, slot_path

    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        row = app.tuning_rows[0]
        default_value = getattr(app._tuning_obj(row.group), row.name)

        await pilot.press("l")
        await pilot.pause()
        nudged = getattr(app._tuning_obj(row.group), row.name)
        assert nudged != default_value

        await pilot.press("S")
        await pilot.pause()
        assert app.tuning_save_armed is True
        await pilot.press("2")
        await pilot.pause()
        assert app.tuning_save_armed is False
        assert app.tuning_name_slot == 2
        assert not slot_path(2).exists()
        await pilot.press("enter")
        await pilot.pause()
        assert app.tuning_name_slot is None
        assert slot_path(2).exists()
        saved_cfg = SkyConfig.load_slot(2)
        assert saved_cfg is not None
        saved_obj = saved_cfg if row.group == "shared" else getattr(saved_cfg, row.group)
        assert getattr(saved_obj, row.name) == nudged

        await pilot.press("r")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) == default_value
        mtime_before_recall = path.stat().st_mtime

        await pilot.press("2")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) == nudged
        assert path.stat().st_mtime >= mtime_before_recall
        assert "recalled slot 2" in app.flash

        await pilot.press("3")
        await pilot.pause()
        assert "slot 3 is empty" in app.flash


async def test_tuning_overlay_named_slot_save_and_recall(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v6h: `S`, a digit, then typed text names the slot before saving; the
    grid at the top of the overlay shows the name, the flash mentions it, and
    a bare digit recall's flash names it back."""
    from cactus.sky import slot_path

    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()

        await pilot.press("S")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert app.tuning_name_slot == 2
        for ch in "wisp":
            await pilot.press(ch)
        await pilot.pause()
        assert app.tuning_name_buf == "wisp"
        await pilot.press("enter")
        await pilot.pause()
        assert app.tuning_name_slot is None
        assert slot_path(2).exists()
        assert 'name = "wisp"' in slot_path(2).read_text()
        assert "wisp" in app.flash

        text = app._tuning_text()
        assert "2 wisp" in text
        assert text.index("2 wisp") < text.index("▸ ")  # slots grid sits above the panel's rows

        # Save, arm, then bail out without saving: cursor/nudge untouched.
        default_index = app.tuning_index
        await pilot.press("S")
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert app.tuning_name_slot == 3
        await pilot.press("j")
        await pilot.press("k")
        await pilot.pause()
        assert app.tuning_index == default_index
        await pilot.press("escape")
        await pilot.pause()
        assert app.tuning_name_slot is None
        assert "save cancelled" in app.flash
        assert not slot_path(3).exists()

        await pilot.press("2")
        await pilot.pause()
        assert "recalled slot 2: wisp" in app.flash


# ---- perf (v6f) -------------------------------------------------------


async def test_fps_nudge_restarts_the_field_timer_at_the_new_interval(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v6f: nudging the `fps` tuning row restarts `_field_timer` at `1 /
    fps` — inspected via the timer's own (private) interval, since
    `_sync_field_interval` only restarts when the interval actually
    changed."""
    path = tmp_path / "sky.toml"
    monkeypatch.setenv("CACTUS_SKY", str(path))

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        before_fps = app.world.sky.config.fps
        before_interval = app._field_timer._interval

        await pilot.press("T")
        await pilot.pause()
        fps_index = next(
            i for i, row in enumerate(app.tuning_rows) if row.group == "shared" and row.name == "fps"
        )
        app.tuning_index = fps_index
        await pilot.press("l")
        await pilot.pause()

        after_fps = app.world.sky.config.fps
        assert after_fps != before_fps
        assert app._field_timer._interval == pytest.approx(1.0 / after_fps)
        assert app._field_timer._interval != before_interval


@pytest.mark.slow
async def test_headless_field_cpu_stays_under_20_percent_of_one_core(store: Store, project: str) -> None:
    """v6f: over a 3 s wall-clock window at the default 6 fps, a headless
    120x40 TUI's own CPU time (the field timer plus everything else it does
    meanwhile) should stay well under 10% of one core. Loose in CI (shared,
    noisy hardware), tight by hand — see the v6f perf spec's target."""
    import resource
    import time as _time

    app = CactusApp(store, project=project)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        def cpu_time() -> float:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_utime + usage.ru_stime

        cpu_before = cpu_time()
        wall_before = _time.perf_counter()
        await pilot.pause(3.0)
        wall_elapsed = _time.perf_counter() - wall_before
        cpu_elapsed = cpu_time() - cpu_before

        cpu_share = cpu_elapsed / wall_elapsed
        assert cpu_share < 0.20, f"{cpu_share * 100:.1f}% of one core"


async def test_tuning_overlay_arrows_move_and_nudge(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert app.tuning_index == 0
        await pilot.press("down")
        await pilot.pause()
        assert app.tuning_index == 1
        await pilot.press("up")
        await pilot.pause()
        assert app.tuning_index == 0
        idx = next(i for i, r in enumerate(app.tuning_rows) if r.step is not None)
        for _ in range(idx):
            await pilot.press("down")
        await pilot.pause()
        row = app.tuning_rows[idx]
        before = getattr(app._tuning_obj(row.group), row.name)
        await pilot.press("right")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) == pytest.approx(before + row.step)
        await pilot.press("left")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) == pytest.approx(before)
        await pilot.press("shift+right")
        await pilot.pause()
        assert getattr(app._tuning_obj(row.group), row.name) == pytest.approx(min(before + 10 * row.step, row.hi))
        text = app._tuning_text()
        assert "saved skies" in text and "digit loads one" in text
        await pilot.press("S")
        await pilot.pause()
        assert "press a digit 1-9 to name and save" in app._tuning_text()


# --- file preview (`o`): shell.file_preview and the card block ---------------


def _repo(tmp_path: Path) -> Path:
    """A throwaway repository with one committed file, `a.txt`."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("one\ntwo\n")
    who = ["-c", "user.name=t", "-c", "user.email=t@t"]
    for args in (["init", "-q"], ["add", "a.txt"], [*who, "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def test_file_preview_modified_file_shows_diff(tmp_path: Path) -> None:
    from cactus.shell import file_preview

    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("one\nTWO\n")
    lines = file_preview(str(repo / "a.txt"))
    assert lines[0] == f"── {repo / 'a.txt'}  (diff vs HEAD) ──"
    assert "-two" in lines and "+TWO" in lines


def test_file_preview_untracked_shows_head(tmp_path: Path) -> None:
    from cactus.shell import file_preview

    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("fresh\n")
    lines = file_preview(str(repo / "new.txt"))
    assert "(untracked)" in lines[0]
    assert lines[1:] == ["fresh"]


def test_file_preview_unchanged_shows_head(tmp_path: Path) -> None:
    from cactus.shell import file_preview

    repo = _repo(tmp_path)
    lines = file_preview(str(repo / "a.txt"))
    assert "(unchanged)" in lines[0]
    assert lines[1:] == ["one", "two"]


def test_file_preview_missing_and_binary(tmp_path: Path) -> None:
    from cactus.shell import file_preview

    assert file_preview(str(tmp_path / "gone")) == [f"missing: {tmp_path / 'gone'}"]
    blob = tmp_path / "b.bin"
    blob.write_bytes(b"ab\0cd")
    lines = file_preview(str(blob))
    assert lines[1] == "binary, 5 bytes"


def test_file_preview_caps_with_tail_line(tmp_path: Path) -> None:
    from cactus.shell import file_preview

    big = tmp_path / "big.txt"
    big.write_text("".join(f"l{i}\n" for i in range(50)))
    lines = file_preview(str(big), limit=40)
    assert len(lines) == 1 + 40 + 1
    assert lines[-1] == "… 10 more lines · f to open"


def test_file_preview_outside_a_repo_shows_head(tmp_path: Path) -> None:
    from cactus.shell import file_preview

    plain = tmp_path / "p.txt"
    plain.write_text("hello\n")
    lines = file_preview(str(plain))
    assert "(no repo)" in lines[0]
    assert lines[1:] == ["hello"]


async def test_preview_o_hidden_on_row_without_files(store: Store, project: str) -> None:
    store.ask("no files", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "o" not in keybar_keys(app)
        await pilot.press("o")
        await pilot.pause()
        assert app.preview_open is False


async def test_preview_o_toggles_block_and_row_move_closes_it(
    store: Store, project: str, tmp_path: Path
) -> None:
    target = tmp_path / "a.txt"
    target.write_text("preview-me\n")
    store.ask("has files", project=project, cwd=project, agent=AGENT, files=[str(target)])
    store.ask("other", project=project, cwd=project, agent=AGENT)

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert keybar_keys(app)["o"] == "preview"
        assert "preview-me" not in str(app.query_one("#card-text", Static).content)

        await pilot.press("o")
        await pilot.pause()
        assert app.preview_open is True
        assert "preview-me" in str(app.query_one("#card-text", Static).content)

        await pilot.press("o")
        await pilot.pause()
        assert "preview-me" not in str(app.query_one("#card-text", Static).content)

        await pilot.press("o")
        await pilot.press("j")
        await pilot.pause()
        assert app.preview_open is False


async def test_tuning_overlay_reshapes_when_the_engine_changes(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        text = app._tuning_text()
        assert "engine puffs" in text and "clouds" in _tuning_panel_names(app)
        assert "far" not in _tuning_panel_names(app)
        # walk to sky_engine and cycle puffs -> fluid
        idx = next(i for i, r in enumerate(app.tuning_rows) if r.name == "sky_engine")
        for _ in range(idx):
            await pilot.press("j")
        await pilot.press("l")
        await pilot.pause()
        text = app._tuning_text()
        names = _tuning_panel_names(app)
        assert "engine fluid" in text and "far" in names and "projection" in names and "clouds" not in names
        assert app.tuning_rows[app.tuning_index].name == "sky_engine"
        await pilot.press("l")  # fluid -> texture
        await pilot.pause()
        text = app._tuning_text()
        assert "engine texture" in text
        assert "far" not in _tuning_panel_names(app) and "clouds" not in _tuning_panel_names(app)
        assert app.tuning_rows[app.tuning_index].name == "sky_engine"


def _tuning_panel_names(app: CactusApp) -> list[str]:
    """The panel strip's names, in order, with the current one's brackets
    stripped — read off the overlay text, the same line the human sees."""
    strip = app._tuning_text().splitlines()[2]
    return [w.strip("[]") for w in strip.split()]


def _tuning_current_panel(app: CactusApp) -> str:
    strip = app._tuning_text().splitlines()[2]
    return next(w.strip("[]") for w in strip.split() if w.startswith("["))


async def _open_tuning_under(pilot, app: CactusApp, **overrides) -> None:
    """Swap the live sky to `SkyConfig(**overrides)`, then open `T`."""
    from cactus.sky import SkyConfig

    app.world.apply_sky_config(SkyConfig(**overrides))
    await pilot.press("T")
    await pilot.pause()


async def test_tuning_panels_filter_by_engine(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_tuning_under(pilot, app, sky_engine="puffs", cloud_style="bands")
        names = _tuning_panel_names(app)
        assert names[0] == "engine" and "clouds" in names
        assert not {"projection", "far", "mid", "near"} & set(names)
        await pilot.press("T")
        await pilot.pause()
        await _open_tuning_under(pilot, app, sky_engine="fluid", perspective="on")
        names = _tuning_panel_names(app)
        assert "projection" in names and names[-3:] == ["far", "mid", "near"]
        assert "clouds" not in names


async def test_tuning_tab_cycles_panels_and_wraps(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_tuning_under(pilot, app, sky_engine="fluid", perspective="on")
        names = _tuning_panel_names(app)
        assert _tuning_current_panel(app) == names[0]
        seen = []
        for _ in range(len(names)):
            await pilot.press("tab")
            await pilot.pause()
            seen.append(_tuning_current_panel(app))
        assert seen == names[1:] + names[:1]
        await pilot.press("shift+tab")
        await pilot.pause()
        assert _tuning_current_panel(app) == names[-1]
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert _tuning_current_panel(app) == names[-2]
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert _tuning_current_panel(app) == names[-1]
        # a panel switch lands on that panel's first row
        from cactus.sky import tuning_panel_of

        row = app.tuning_rows[app.tuning_index]
        assert tuning_panel_of(row) == names[-1]
        assert tuning_panel_of(app.tuning_rows[app.tuning_index - 1]) != names[-1]


async def test_tuning_j_past_panel_end_lands_on_next_panel(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cactus.sky import tuning_panel_of

    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_tuning_under(pilot, app, sky_engine="puffs", cloud_style="bands")
        names = _tuning_panel_names(app)
        first = names[0]
        last = max(i for i, r in enumerate(app.tuning_rows) if tuning_panel_of(r) == first)
        for _ in range(last):
            await pilot.press("j")
        await pilot.pause()
        assert _tuning_current_panel(app) == first
        await pilot.press("j")
        await pilot.pause()
        assert _tuning_current_panel(app) == names[1]
        assert app.tuning_index == last + 1
        await pilot.press("k")
        await pilot.pause()
        assert _tuning_current_panel(app) == first and app.tuning_index == last
        # only the current panel's rows are on the page
        text = app._tuning_text()
        other = next(r for r in app.tuning_rows if tuning_panel_of(r) == names[1])
        assert f" {other.name}  " not in text


async def test_tuning_scroll_keeps_cursor_visible_on_a_short_terminal(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.containers import VerticalScroll
    from cactus.sky import tuning_panel_of

    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        await _open_tuning_under(pilot, app, sky_engine="fluid", perspective="on")
        while _tuning_current_panel(app) != "far":
            await pilot.press("tab")
        await pilot.pause()
        last = max(i for i, r in enumerate(app.tuning_rows) if tuning_panel_of(r) == "far")
        while app.tuning_index != last:
            await pilot.press("j")
        await pilot.pause()
        await pilot.pause()
        scroll = app.query_one("#tuning-scroll", VerticalScroll)
        assert scroll.max_scroll_y > 0  # the page really is taller than the view
        assert scroll.scroll_y > 0

        def cursor_on_screen() -> bool:
            y, h = app._tuning_cursor_span()
            top, height = scroll.scroll_y, scroll.scrollable_content_region.height
            name = app.tuning_rows[app.tuning_index].name
            screen = "\n".join(s.text for s in app.screen._compositor.render_strips())
            return top <= y and y + h <= top + height and f"▸ {name}  " in screen

        assert cursor_on_screen()
        # and back up to the panel's first row scrolls up again
        first = min(i for i, r in enumerate(app.tuning_rows) if tuning_panel_of(r) == "far")
        while app.tuning_index != first:
            await pilot.press("k")
        await pilot.pause()
        await pilot.pause()
        assert cursor_on_screen()


async def test_tuning_engine_change_keeps_cursor_on_sky_engine(
    store: Store, project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACTUS_SKY", str(tmp_path / "sky.toml"))
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_tuning_under(pilot, app, sky_engine="puffs", cloud_style="bands")
        app.tuning_index = next(i for i, r in enumerate(app.tuning_rows) if r.name == "sky_engine")
        app._render_tuning()
        before = _tuning_panel_names(app)
        await pilot.press("l")  # puffs -> fluid: clouds goes, projection/far/mid/near arrive
        await pilot.pause()
        assert app.world.sky.config.sky_engine == "fluid"
        assert _tuning_panel_names(app) != before
        assert app.tuning_rows[app.tuning_index].name == "sky_engine"
        assert _tuning_current_panel(app) == "engine"


def _review(store: Store, project: str, text: str = "check it"):
    return store.ask(
        text, project=project, cwd=project, agent=AGENT,
        kind="confirm", act="review", choices=[Choice("pass"), Choice("fail")],
    )


def _card_classes(app: CactusApp) -> tuple[bool, bool]:
    card = app.query_one("#card")
    return card.has_class("-sent"), card.has_class("-heard")


async def test_verdict_dims_card_sent_then_heard_then_normal(store: Store, project: str) -> None:
    q = _review(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _card_classes(app) == (False, False)

        store.answer(q.key, project=project, selected=["pass"])
        await app._reload(force=True)
        await pilot.pause()
        assert _card_classes(app) == (True, False)
        text = str(app.query_one("#card-text", Static).content)
        assert "sent · waiting for the agent" in text
        block = app.query_one(f"#row-{q.key}", QuestionBlock)
        assert block.has_class("-sent")

        store.mark_heard(q.id)
        await app._reload(force=True)
        await pilot.pause()
        assert _card_classes(app) == (False, True)
        assert "heard ✓ · agent is on it" in str(app.query_one("#card-text", Static).content)
        assert app.query_one(f"#row-{q.key}", QuestionBlock).has_class("-heard")

        store.mark_responded(q.id)
        await app._reload(force=True)
        await pilot.pause()
        assert _card_classes(app) == (False, False)
        assert not app.query_one(f"#row-{q.key}", QuestionBlock).has_class("-heard")


async def test_x_closes_review_and_plan_and_undo_restores(store: Store, project: str) -> None:
    rq = _review(store, project)
    pq = store.ask("plan", project=project, cwd=project, agent=AGENT, kind="text", act="plan")

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        for key in (rq.key, pq.key):
            while app.focused_key != key:
                await pilot.press("j")
                await pilot.pause()
            assert keybar_keys(app)["x"] == "close"
            assert "enter = note · x = close" in str(app.query_one("#card-text", Static).content)
            await pilot.press("x")
            await pilot.pause()
            assert store.get(key, project=project).status == "cleared"
        await pilot.press("u")
        await pilot.pause()
        assert store.get(pq.key, project=project).status == "live"


async def test_x_absent_on_other_rows(store: Store, project: str) -> None:
    ask = store.ask("pick", project=project, cwd=project, agent=AGENT, kind="choice",
                    choices=[Choice("a"), Choice("b")])
    data = store.ask("d", project=project, cwd=project, agent=AGENT, kind="choice",
                     act="data", choices=[Choice("one", "body")])
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        for key in (ask.key, data.key):
            while app.focused_key != key:
                await pilot.press("j")
                await pilot.pause()
            assert "x" not in keybar_keys(app)
            assert app.check_action("close_row", ()) is False
            await pilot.press("x")
            await pilot.pause()
            assert store.get(key, project=project).status != "cleared"


async def test_finished_prompt_on_plan_and_review(store: Store, project: str) -> None:
    pq = store.ask("plan", project=project, cwd=project, agent=AGENT, kind="text", act="plan")
    store.set_steps(pq.key, ["s1", "s2"], project=project)
    rq = _review(store, project)
    prompt = "finished? x closes it (or the agent will)"

    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        while app.focused_key != pq.key:
            await pilot.press("j")
            await pilot.pause()
        assert prompt not in str(app.query_one("#card-text", Static).content)

        store.set_step_done(pq.key, 0, project=project)
        store.set_step_done(pq.key, 1, project=project)
        await app._reload(force=True)
        await pilot.pause()
        assert prompt in str(app.query_one("#card-text", Static).content)

        while app.focused_key != rq.key:
            await pilot.press("j")
            await pilot.pause()
        assert prompt not in str(app.query_one("#card-text", Static).content)
        store.answer(rq.key, project=project, selected=["pass"])
        await app._reload(force=True)
        await pilot.pause()
        assert prompt in str(app.query_one("#card-text", Static).content)


# ---- reload / rail rebuild serialization ----------------------------------


class _Gate:
    """Parks every `ListView.clear` on the rail until `release()`.

    `entered` counts how many rebuilds reached the clear, so a test can tell
    a serialized second reload (never gets there while the first is parked)
    from a racing one.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.entered = 0
        self.total = 0
        self.first_parked = asyncio.Event()
        self._open = asyncio.Event()
        orig = ListView.clear
        gate = self

        async def clear(view: ListView):
            if view.id == "rail-list":
                gate.total += 1
                gate.entered += 1
                gate.first_parked.set()
                await gate._open.wait()
            return await orig(view)

        monkeypatch.setattr(ListView, "clear", clear)

    def release(self) -> None:
        self._open.set()


async def _yield(n: int = 10) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _rail_ids(app: CactusApp) -> list[str]:
    return [c.id for c in app.query_one("#rail-list", ListView).children]


def _three(store: Store, project: str) -> list[str]:
    return [
        store.ask(
            f"row {i}", project=project, cwd=project, agent=AGENT,
            kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
        ).key
        for i in range(3)
    ]


async def test_concurrent_reloads_do_not_duplicate_rail_ids(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _three(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.focused_key = keys[1]
        gate = _Gate(monkeypatch)
        try:
            first = asyncio.create_task(app._reload(force=True))
            await gate.first_parked.wait()
            second = asyncio.create_task(app._reload(force=True))
            poll = asyncio.create_task(app._poll())
            await _yield()
        finally:
            gate.release()
        await asyncio.gather(first, second, poll)
        await pilot.pause()

        ids = _rail_ids(app)
        assert ids == [f"row-{q.key}" for q in app.questions]
        assert len(set(ids)) == len(ids) == 3
        assert app.focused_key == keys[1]
        assert gate.entered == 2  # one rebuild per forced reload, serialized


async def test_poll_while_locked_coalesces_and_runs_once_after(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _three(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        gate = _Gate(monkeypatch)
        try:
            held = asyncio.create_task(app._reload(force=True))
            await gate.first_parked.wait()
            parked_cursor = app.last_cursor
            new = store.ask(
                "late", project=project, cwd=project, agent=AGENT,
                kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
            )
            polls = [asyncio.create_task(app._poll()) for _ in range(2)]
            await _yield()
            assert all(p.done() for p in polls)  # coalesced, not parked
            assert app.last_cursor == parked_cursor
            assert app.last_cursor != store.cursor()
        finally:
            gate.release()
        await held
        await pilot.pause()

        assert f"row-{new.key}" in _rail_ids(app)
        assert app.last_cursor == store.cursor()
        assert gate.entered == 2  # the held rebuild plus one pending rebuild


async def test_row_move_during_rebuild_is_honoured(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _three(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.focused_key == keys[0]
        gate = _Gate(monkeypatch)
        try:
            held = asyncio.create_task(app._reload(force=True))
            await gate.first_parked.wait()
            app.action_focus_next()
        finally:
            gate.release()
        await held
        await pilot.pause()

        assert app.focused_key == keys[1]
        assert app.query_one("#rail-list", ListView).index == 1


async def test_choice_card_renders_tradeoff_marks_colored(store: Store, project: str) -> None:
    store.ask(
        "which?", project=project, cwd=project, agent=AGENT, kind="choice",
        choices=[Choice("oidc", "existing IdP\n+ tenant ready\n- couples us [bold]x[/]")],
    )
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        content = app.query_one("#card-text", Static).content

    plain = content.plain
    assert "1)  oidc  — existing IdP" in plain
    assert "      ✓ tenant ready" in plain
    assert "      ✗ couples us [bold]x[/]" in plain
    styles = {content.plain[s.start:s.end].strip(): str(s.style) for s in content.spans}
    assert styles["✓ tenant ready"] == "green"
    assert styles["✗ couples us [bold]x[/]"] == "red"


def test_decompose_instruction_batches_without_waiting():
    # Follow-ups are a batch: each posts --no-wait, and one backgrounded
    # get waits on all of them.
    from cactus.tui import DECOMPOSE_INSTRUCTION

    text = DECOMPOSE_INSTRUCTION.format(key="q7")
    assert "-p q7 --no-wait" in text
    assert "backgrounded `cactus get KEY... --wait`" in text


# ---- auto-decider -------------------------------------------------------


async def settle_auto(app: CactusApp, pilot) -> None:
    """Let the auto worker chain drain: each stamp triggers a reload and the next job."""
    for _ in range(4):
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause(0.7)  # past POLL_INTERVAL so the stamp reloads


def auto_row(store: Store, project: str, text: str = "pick one"):
    return store.ask(
        text, project=project, cwd=project, agent=AGENT,
        kind="choice", act="ask", choices=[Choice("a"), Choice("b")],
    )


async def test_auto_worker_stamps_gated_row_with_proposal(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACTUS_RANK", "reversible,low")
    monkeypatch.setenv("CACTUS_DECIDE", "b:0.93")
    q = auto_row(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await settle_auto(app, pilot)
        got = store.get(q.key, project=project)
        assert (got.auto_pick, got.auto_confidence) == ("b", 0.93)
        assert got.auto_reason == "reversible · low"
        assert got.status == "open"  # proposes, never answers
        text = str(app.query_one("#card-text", Static).content)
        assert "[..] b - reversible · low" in text


async def test_auto_worker_holds_a_non_gated_row_and_card_shows_nothing(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACTUS_RANK", "costly,high")
    monkeypatch.setenv("CACTUS_DECIDE", "b:0.93")
    q = auto_row(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await settle_auto(app, pilot)
        got = store.get(q.key, project=project)
        assert got.auto_pick is None and got.auto_at is not None
        assert got.auto_reason == "costly · high"
        assert "[..]" not in str(app.query_one("#card-text", Static).content)
        assert "A" not in keybar_keys(app)


async def test_auto_worker_never_runs_when_overrides_are_off(
    store: Store, project: str
) -> None:
    q = auto_row(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await settle_auto(app, pilot)
    assert store.get(q.key, project=project).auto_at is None


async def test_auto_worker_skips_multi_and_persistent_rows(
    store: Store, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACTUS_RANK", "reversible,low")
    monkeypatch.setenv("CACTUS_DECIDE", "b:0.93")
    multi = store.ask("m", project=project, cwd=project, agent=AGENT, kind="multi",
                      act="ask", choices=[Choice("a"), Choice("b")])
    review = store.ask("r", project=project, cwd=project, agent=AGENT, kind="confirm",
                       act="review", choices=[Choice("pass"), Choice("fail")])
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await settle_auto(app, pilot)
    assert store.get(multi.key, project=project).auto_at is None
    assert store.get(review.key, project=project).auto_at is None


async def test_A_accepts_the_proposal_like_its_digit(store: Store, project: str) -> None:
    q = auto_row(store, project)
    store.set_auto(q.key, "b", 0.9, "reversible · low", project=project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert keybar_keys(app).get("A") == "auto"
        await pilot.press("A")
        await pilot.pause()
        assert app.undo_stack  # same undo entry a digit pushes
    fresh = store.get(q.key, project=project)
    assert fresh.status == "answered"
    assert fresh.answer.selected == ["b"]


async def test_A_without_a_proposal_flashes_and_keybar_omits_it(
    store: Store, project: str
) -> None:
    q = auto_row(store, project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "A" not in keybar_keys(app)
        assert app.check_action("activate_project", ()) is False
        await pilot.press("A")
        await pilot.pause()
        assert "no proposal" in app.flash
    assert store.get(q.key, project=project).status == "open"


async def test_A_on_the_projects_page_still_activates(store: Store, project: str) -> None:
    q = auto_row(store, project)
    store.set_auto(q.key, "b", 0.9, "reversible · low", project=project)
    app = CactusApp(store, project=project)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("P")
        await pilot.pause()
        assert app.check_action("activate_project", ()) is True
        await pilot.press("A")
        await pilot.pause()
    assert store.get(q.key, project=project).status == "open"  # not accepted


# ---- field process and Line-API field view -------------------------------


def _drain_until(field: ProcessField, rows: dict[int, tuple], done, timeout: float) -> bool:
    """Feed `field`'s frames into `rows` (the parent's merged view) until
    `done(rows)` holds or `timeout` runs out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([field.fileno()], [], [], 0.1)
        if not ready:
            continue
        upd = field.drain()
        assert not upd.closed and upd.error is None
        if upd.n_rows is not None:
            for y in [y for y in rows if y >= upd.n_rows]:
                del rows[y]
        rows.update(upd.rows)
        if done(rows):
            return True
    return False


def test_process_field_streams_rows_lands_a_seed_and_stops_clean(
    scratch_env: dict[str, str], tmp_path: Path,
) -> None:
    """The child owns the World: frames arrive as changed rows, a dropped
    seed lands (the pile-only rows stop being blank, and the child wrote the
    landing to garden.json itself), and stop leaves no process behind."""
    garden_path = tmp_path / "garden.json"
    field = ProcessField(garden_path=garden_path, sky_path=tmp_path / "sky.toml", cols=20, rows=6, seed=1)
    field.start()
    try:
        rows: dict[int, tuple] = {}
        assert _drain_until(field, rows, lambda r: len(r) == 6, 20)
        assert all(len(plain) == 20 for plain, _ in rows.values())
        field.set_pile_only(True)
        field.drop(10)
        # A seed falls for LANDING_SECONDS (12 s) of real time.
        landed = _drain_until(field, rows, lambda r: any(p.strip() for p, _ in r.values()), 40)
        assert landed
        assert field.pile_rows() >= 3
        deadline = time.monotonic() + 5
        while not garden_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert garden.read(garden_path)["cells"]
    finally:
        field.stop()
    assert not field.alive()
    assert field._proc.exitcode == 0


async def test_field_view_repaints_only_changed_rows_and_matches_static() -> None:
    """FieldView draws a World frame cell for cell like the old Static path
    (char, colour, background — Static only adds mouse-offset meta), and a
    frame that changes one row refreshes that row alone."""
    from rich.text import Text as RichText
    from textual.app import App, ComposeResult
    from textual.geometry import Region

    width, height = 40, 8
    world = World(width, height, rng=random.Random(3))
    for col in range(0, width, 7):
        world.drop(col)
    for _ in range(40):
        world.advance(0.05)
    text = world.render()

    class Probe(App):
        CSS = f"#old, #new {{ height: {height}; width: {width}; background: $surface; }}"

        def compose(self) -> ComposeResult:
            yield Static(id="old", markup=False)
            yield FieldView(id="new")

    def cells(widget) -> list[tuple]:
        return [
            (ch, seg.style.clear_meta_and_links() if seg.style else None)
            for strip in widget.render_lines(Region(0, 0, width, height))
            for seg in strip
            for ch in seg.text
        ]

    app = Probe()
    async with app.run_test(size=(width, height * 2)) as pilot:
        old, new = app.query_one("#old", Static), app.query_one("#new", FieldView)
        old.update(text)
        new.show_text(text)
        await pilot.pause()
        assert cells(new) == cells(old)

        refreshed: list[Region] = []
        real_refresh = new.refresh
        new.refresh = lambda *regions, **kw: (refreshed.extend(regions), real_refresh(*regions, **kw))[1]
        rows = text_rows(text)
        new.apply_frame(height, dict(enumerate(rows)))
        assert refreshed == []  # nothing changed, nothing repainted
        new.apply_frame(height, {3: ("x" * width, ((0, width, "#ff0000"),))})
        assert refreshed == [Region(0, 3, width, 1)]
        await pilot.pause()
        changed = RichText("\n".join(p for p, _ in rows[:3]) + "\n" + "x" * width + "\n"
                           + "\n".join(p for p, _ in rows[4:]))
        assert "".join(c for c, _ in cells(new)) == changed.plain.replace("\n", "")


async def test_process_mode_app_paints_child_frames_and_stops_the_child(store: Store, project: str) -> None:
    """`field_mode="process"`: the app holds no World, the child's frames
    land in FieldView, a backtick drop and a tuning nudge reach the child
    without error, and unmounting stops it."""
    from multiprocessing import resource_tracker

    resource_tracker.ensure_running()  # as run_tui does before App.run()
    store.ask("pick one", project=project, cwd=project, agent=AGENT, kind="text", act="ask")
    app = CactusApp(store, project=project, field_mode="process")
    async with app.run_test(size=(100, 40)) as pilot:
        assert app.world is None
        assert isinstance(app.field, ProcessField) and app.field.alive()
        widget = app.query_one("#field", FieldView)
        deadline = time.monotonic() + 20
        while not widget._rows and time.monotonic() < deadline:
            await pilot.pause(0.1)
        assert len(widget._rows) == widget.size.height
        assert app.field.cols == widget.size.width
        await pilot.press("grave_accent")
        await pilot.pause(0.2)
        assert app._field_timer is None  # the child paces itself
        await pilot.press("T")
        await pilot.pause()
        before = app.sky_config.fps
        app.tuning_index = next(i for i, r in enumerate(app.tuning_rows) if r.name == "fps")
        await pilot.press("l")
        await pilot.pause(0.3)
        assert app.sky_config.fps != before  # the overlay's copy moved on the spot
        assert app.field.alive()
        child = app.field
    assert not child.alive()
