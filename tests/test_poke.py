"""
test_poke.py — poke transport resolution.

Responsibilities:
- A transport on PATH resolves as before.
- A transport missing from a stripped PATH is found in the fallback bin dirs.
- A transport nowhere reports every place it looked.
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
