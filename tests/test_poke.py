"""
test_poke.py — poke transport resolution.

Responsibilities:
- A transport on PATH resolves as before.
- A transport missing from a stripped PATH is found in the fallback bin dirs.
- A transport nowhere reports every place it looked.
- Visit focuses the row's pane and refuses a row without one.
"""

from __future__ import annotations

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

    ran = poke_mod.visit("w3B:p3")

    assert ran.endswith(" agent focus w3B:p3")


def test_visit_refuses_without_a_pane() -> None:
    with pytest.raises(poke_mod.PokeError) as err:
        poke_mod.visit(None)

    assert "pane" in str(err.value)


def test_poke_webhook_if_mapped_ignores_override_and_unmapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CACTUS_POKE", "echo {target} {message}")
    monkeypatch.setenv("CACTUS_POKE_WEBHOOKS", str(tmp_path / "no-webhooks.json"))
    assert poke_mod.poke_webhook_if_mapped("agent-1") is None
    assert poke_mod.poke_webhook_if_mapped(None) is None
