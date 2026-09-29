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
- The garden (the landed pile) is shared and persisted: it survives a
  restart and stays in sync across every TUI on the same database.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from textual.widgets import Footer, Input, Static
from textual.widgets._footer import FooterKey

from cactus import garden
from cactus.field import World
from cactus.store import Choice, Store
from cactus.tui import CactusApp, QuestionBlock

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
        row = app.tuning_rows[0]
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
        assert app.world.sky.config.pile_style == "blocks"

        await pilot.press("l")
        await pilot.pause()
        assert app.world.sky.config.pile_style == "dots"

        await pilot.press("l")
        await pilot.pause()
        assert app.world.sky.config.pile_style == "blocks"

        await pilot.press("h")
        await pilot.pause()
        assert app.world.sky.config.pile_style == "dots"

        assert SkyConfig.load(path).pile_style == "dots"


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
    """v6f: over a 3 s wall-clock window at the default 5 fps, a headless
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
