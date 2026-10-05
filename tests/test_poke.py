"""
test_poke.py — poke transport resolution.

Responsibilities:
- A transport on PATH resolves as before.
- A transport missing from a stripped PATH is found in the fallback bin dirs.
- A transport nowhere reports every place it looked.
- Visit focuses the row's pane and refuses a row without one.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from cactus import poke as poke_mod


def _fake_transport(directory: Path, name: str = "herdr") -> Path:
    exe = directory / name
    exe.write_text("#!/bin/sh\necho poked \"$@\"\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def test_fallback_dir_finds_transport_when_path_is_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "userbin"
    bin_dir.mkdir()
    _fake_transport(bin_dir)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(poke_mod, "FALLBACK_BIN_DIRS", (bin_dir,))
    monkeypatch.setenv("CACTUS_POKE", "herdr agent prompt {agent} {message}")

    ran = poke_mod.poke("agent-1")

    assert str(bin_dir / "herdr") in ran


def test_path_wins_over_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    on_path = tmp_path / "onpath"
    on_path.mkdir()
    _fake_transport(on_path)
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    _fake_transport(fallback)
    monkeypatch.setenv("PATH", f"{on_path}{os.pathsep}/usr/bin:/bin")
    monkeypatch.setattr(poke_mod, "FALLBACK_BIN_DIRS", (fallback,))

    assert poke_mod.resolve_executable("herdr") == str(on_path / "herdr")


def test_missing_everywhere_names_the_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(poke_mod, "FALLBACK_BIN_DIRS", (empty,))
    monkeypatch.setenv("CACTUS_POKE", "no-such-transport {agent} {message}")

    with pytest.raises(poke_mod.PokeError) as err:
        poke_mod.poke("agent-1")

    assert str(empty) in str(err.value)


def test_slashed_name_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poke_mod, "FALLBACK_BIN_DIRS", (tmp_path,))
    assert poke_mod.resolve_executable(str(tmp_path / "absent" / "herdr")) is None


def test_default_transport_targets_the_pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """herdr resolves a pane id, never a conversation id: the default prompt goes to the pane."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_transport(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv("CACTUS_POKE", raising=False)
    monkeypatch.setenv("CACTUS_POKE_WEBHOOKS", str(tmp_path / "no-webhooks.json"))

    ran = poke_mod.poke("83155dd4-agent", pane="w3B:p3")

    assert " prompt w3B:p3 " in ran
    assert "83155dd4-agent" not in ran.split(" prompt ")[1].split(" ")[0]


def test_default_transport_refuses_without_a_pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CACTUS_POKE", raising=False)
    monkeypatch.setenv("CACTUS_POKE_WEBHOOKS", str(tmp_path / "no-webhooks.json"))

    with pytest.raises(poke_mod.PokeError) as err:
        poke_mod.poke("agent-1")

    assert "pane" in str(err.value)


def test_override_template_gets_target_and_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_transport(bin_dir, "echo-transport")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    monkeypatch.setenv("CACTUS_POKE", "echo-transport {target} for {agent}")

    ran = poke_mod.poke("agent-1", pane="w1:p1")

    assert "w1:p1 for agent-1" in ran


def test_reachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CACTUS_POKE", raising=False)
    monkeypatch.setenv("CACTUS_POKE_WEBHOOKS", str(tmp_path / "no-webhooks.json"))
    assert poke_mod.reachable("agent-1", "w1:p1")
    assert not poke_mod.reachable("agent-1", None)
    assert not poke_mod.reachable(None, "w1:p1")
    monkeypatch.setenv("CACTUS_POKE", "true {agent} {message}")
    assert poke_mod.reachable("agent-1", None)


def test_visit_focuses_the_pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_transport(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv("CACTUS_VISIT", raising=False)

    ran = poke_mod.visit("w3B:p3").ran

    assert ran.endswith(" agent focus w3B:p3")


def test_visit_and_poke_pin_herdr_to_the_rows_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pane id names a pane inside one herdr session; run from a TUI
    outside it (or in another session), herdr answers agent_not_found
    unless `--session` names the row's own."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_transport(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv("CACTUS_VISIT", raising=False)
    monkeypatch.delenv("CACTUS_POKE", raising=False)
    monkeypatch.setenv("CACTUS_POKE_WEBHOOKS", str(tmp_path / "none.json"))

    assert poke_mod.visit("w3B:p3", session="estate").ran.endswith(" --session estate agent focus w3B:p3")
    assert poke_mod.visit("w3B:p3").ran.endswith("herdr agent focus w3B:p3")
    ran = poke_mod.poke("a1", pane="w3B:p3", session="estate", message="hi")
    assert ran.endswith(" --session estate agent prompt w3B:p3 hi")

    monkeypatch.setenv("CACTUS_VISIT", "true {session} {pane}")
    assert poke_mod.visit("w3B:p3", session="estate").ran == "/usr/bin/true estate w3B:p3"


def test_visit_refuses_without_a_pane() -> None:
    with pytest.raises(poke_mod.PokeError) as err:
        poke_mod.visit(None)

    assert "pane" in str(err.value)


_KITTY_LS = json.dumps([{"tabs": [{"windows": [
    {"id": 3, "foreground_processes": [{"cmdline": ["/bin/zsh"]}]},
    {"id": 7, "foreground_processes": [{"cmdline": ["herdr", "server"]}]},
    {"id": 8, "foreground_processes": [{"cmdline": ["herdr", "--session", "patches"]}]},
    {"id": 24, "foreground_processes": [{"cmdline": ["/opt/bin/herdr", "--session=estate"]}]},
    {"id": 30, "foreground_processes": [{"cmdline": ["herdr"]}]},
]}]}])


def _fake_kitten(directory: Path, log: Path, listing: str = _KITTY_LS) -> None:
    """A `kitten` that answers `ls` with `listing` and logs every call."""
    (directory / "ls.json").write_text(listing)
    exe = directory / "kitten"
    exe.write_text(
        f'#!/bin/sh\necho "$@" >> {log}\n'
        f'case "$*" in *" ls") cat {directory}/ls.json;; esac\n'
    )
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def kitty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "kbin"
    bin_dir.mkdir()
    log = tmp_path / "kitten.log"
    _fake_kitten(bin_dir, log)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv("CACTUS_VISIT_RAISE", raising=False)
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:/tmp/fake-kitty")
    return log


def test_raise_picks_the_session_client_window(kitty: Path) -> None:
    ran = poke_mod.raise_herdr_client("estate")

    assert ran is not None and ran.endswith("@ --to unix:/tmp/fake-kitty focus-window --match id:24")
    assert kitty.read_text().splitlines()[-1] == "@ --to unix:/tmp/fake-kitty focus-window --match id:24"
    assert poke_mod.raise_herdr_client("patches").endswith("id:8")
    assert poke_mod.raise_herdr_client(None).endswith("id:30")


def test_raise_with_no_matching_window_says_so(kitty: Path) -> None:
    with pytest.raises(poke_mod.PokeError) as err:
        poke_mod.raise_herdr_client("nowhere")

    assert "no kitty window runs herdr session nowhere" in str(err.value)
    assert "focus-window" not in kitty.read_text()


def test_raise_without_kitty_socket_does_nothing(kitty: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KITTY_LISTEN_ON")

    assert poke_mod.raise_herdr_client("estate") is None
    assert not kitty.exists()


def test_raise_off_skips_and_template_substitutes_session(
    kitty: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACTUS_VISIT_RAISE", "off")
    assert poke_mod.raise_herdr_client("estate") is None
    monkeypatch.setenv("CACTUS_VISIT_RAISE", "")
    assert poke_mod.raise_herdr_client("estate") is None
    assert not kitty.exists()

    monkeypatch.setenv("CACTUS_VISIT_RAISE", "true raise {session}")
    assert poke_mod.raise_herdr_client("estate") == "/usr/bin/true raise estate"


def test_visit_raises_after_focus_and_reports_a_raise_failure(
    kitty: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_transport(tmp_path / "kbin")
    monkeypatch.delenv("CACTUS_VISIT", raising=False)

    ok = poke_mod.visit("w3B:p3", session="estate")
    assert ok.ran.endswith("--session estate agent focus w3B:p3") and ok.raise_error is None
    assert kitty.read_text().splitlines()[-1].endswith("id:24")

    miss = poke_mod.visit("w3B:p3", session="nowhere")
    assert miss.ran.endswith("agent focus w3B:p3")
    assert "no kitty window runs herdr session nowhere" in miss.raise_error

    # A CACTUS_VISIT override is not the default transport: no raise.
    kitty.unlink()
    monkeypatch.setenv("CACTUS_VISIT", "true {pane}")
    assert poke_mod.visit("w3B:p3", session="estate").raise_error is None
    assert not kitty.exists()


def test_poke_webhook_if_mapped_ignores_override_and_unmapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACTUS_POKE", "echo {target} {message}")
    monkeypatch.setenv("CACTUS_POKE_WEBHOOKS", str(tmp_path / "no-webhooks.json"))
    assert poke_mod.poke_webhook_if_mapped("agent-1") is None
    assert poke_mod.poke_webhook_if_mapped(None) is None
