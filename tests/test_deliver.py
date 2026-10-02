"""
test_deliver.py — the per-agent delivery map and `cactus deliver`.

Responsibilities:
- The map parses a herdr entry beside every webhook shape.
- `deliver` writes, reads and removes one agent's entry, keeping the rest.
- `deliver` exit codes: missing --agent 1, no entry 3.
- Answering a row whose agent registered herdr runs the transport at the
  row's pane; a row with no pane is skipped; webhook entries still parse.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from cactus import poke as poke_mod


@pytest.fixture
def map_path(scratch_env: dict[str, str]) -> Path:
    return Path(scratch_env["CACTUS_POKE_WEBHOOKS"])


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_map_parses_herdr_and_webhook_entries(map_path: Path) -> None:
    map_path.write_text(json.dumps({
        "h": {"herdr": True},
        "w": {"url": "https://x/y", "authorization": "Bearer t"},
    }))
    assert poke_mod.is_herdr_entry(poke_mod.delivery_entry("h"))
    assert poke_mod.webhook_entry("h") is None
    assert poke_mod.webhook_entry("w") == {"url": "https://x/y", "authorization": "Bearer t"}
    assert not poke_mod.is_herdr_entry(poke_mod.delivery_entry("w"))
    assert poke_mod.delivery_entry("nobody") is None


def test_deliver_herdr_webhook_show_off(cli, map_path: Path) -> None:
    got = cli("deliver", "herdr", "--agent", "a1", "--json")
    assert got.returncode == 0 and json.loads(got.stdout) == {"herdr": True}
    assert _load(map_path) == {"a1": {"herdr": True}}

    got = cli("deliver", "webhook", "https://h/w", "--agent", "a2", "--json")
    assert got.returncode == 0 and json.loads(got.stdout) == {"url": "https://h/w"}

    got = cli("deliver", "--agent", "a1", "--json")
    assert got.returncode == 0 and json.loads(got.stdout) == {"herdr": True}

    got = cli("deliver", "off", "--agent", "a1")
    assert got.returncode == 0
    assert _load(map_path) == {"a2": {"url": "https://h/w"}}


def test_deliver_no_entry_is_exit_3(cli) -> None:
    for argv in (("deliver", "off", "--agent", "ghost"), ("deliver", "--agent", "ghost")):
        got = cli(*argv)
        assert got.returncode == 3
        assert got.stderr.strip() == "cactus: no match"


def test_deliver_requires_agent(cli) -> None:
    assert cli("deliver", "herdr").returncode == 1
    assert cli("deliver", "webhook", "--agent", "a").returncode == 1


def test_deliver_preserves_other_entries_and_unknown_keys(cli, map_path: Path) -> None:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps({
        "keep": {"url": "https://k", "headers": {"X": "1"}, "extra": 5},
        "_note": "unknown",
    }))
    assert cli("deliver", "herdr", "--agent", "new").returncode == 0
    data = _load(map_path)
    assert data["keep"] == {"url": "https://k", "headers": {"X": "1"}, "extra": 5}
    assert data["_note"] == "unknown"
    assert data["new"] == {"herdr": True}
    assert not list(map_path.parent.glob("*.tmp"))


def test_deliver_creates_parent_dir(cli, scratch_env, tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "map.json"
    scratch_env["CACTUS_POKE_WEBHOOKS"] = str(nested)
    assert cli("deliver", "herdr", "--agent", "x").returncode == 0
    assert _load(nested) == {"x": {"herdr": True}}


def _logger(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "poke.log"
    exe = tmp_path / "logpoke"
    exe.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe, log


def _ask(cli, agent: str) -> str:
    got = cli("ask", "ship it?", "--agent", agent, "-c", "yes", "-c", "no", "--no-wait", "--json")
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)["key"]


def test_answer_delivers_to_herdr_agent_at_the_rows_pane(
    cli, scratch_env, map_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, log = _logger(tmp_path)
    scratch_env["CACTUS_POKE"] = f"{exe} {{target}} {{agent}} {{message}}"
    monkeypatch.setenv("HERDR_PANE_ID", "w9:p4")
    monkeypatch.setenv("HERDR_SESSION", "sess")
    assert cli("deliver", "herdr", "--agent", "hagent").returncode == 0
    key = _ask(cli, "hagent")

    got = cli("answer", key, "-s", "yes")
    assert got.returncode == 0, got.stderr
    line = log.read_text()
    assert line.startswith("w9:p4 hagent ")


def test_answer_skips_herdr_agent_when_row_has_no_pane(
    cli, scratch_env, map_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, log = _logger(tmp_path)
    scratch_env["CACTUS_POKE"] = f"{exe} {{target}} {{agent}} {{message}}"
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    assert cli("deliver", "herdr", "--agent", "hagent").returncode == 0
    key = _ask(cli, "hagent")

    got = cli("answer", key, "-s", "yes")
    assert got.returncode == 0 and got.stderr.strip() == ""
    assert not log.exists()


def test_unregistered_agent_is_not_delivered(
    cli, scratch_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, log = _logger(tmp_path)
    scratch_env["CACTUS_POKE"] = f"{exe} {{target}} {{agent}} {{message}}"
    monkeypatch.setenv("HERDR_PANE_ID", "w9:p4")
    key = _ask(cli, "plain")
    assert cli("answer", key, "-s", "yes").returncode == 0
    assert not log.exists()


def test_deliver_if_mapped_herdr_unit(
    map_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe, log = _logger(tmp_path)
    monkeypatch.setenv("CACTUS_POKE", f"{exe} {{target}} {{message}}")
    map_path.write_text(json.dumps({"h": {"herdr": True}}))
    assert poke_mod.deliver_if_mapped("h") is None
    assert poke_mod.deliver_if_mapped("h", pane="w1:p2")
    assert log.read_text().startswith("w1:p2 ")
    assert poke_mod.poke_webhook_if_mapped is poke_mod.deliver_if_mapped
