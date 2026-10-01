"""
test_rank.py — the auto-decider's ranker gate.

Responsibilities:
- Label and fixed-pair parsing.
- The gate truth table and the reason string.
- CACTUS_RANK override: fixed pair, off, malformed, command template, and
  that an override never falls through to a real model.
- Backend fallback order: apint, then haiku, then None.
- A slow backend is cut off by the timeout and falls through.
"""

from __future__ import annotations

import stat
import time
from pathlib import Path

import pytest

from cactus import poke as poke_mod
from cactus import rank

ROW = ("Name the flag --quiet or --silent?", None,
       [("quiet", "matches git"), ("silent", "matches curl")])


def _exe(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH holding only fakes plus the system shell tools; no real models."""
    directory = tmp_path / "bin"
    directory.mkdir()
    monkeypatch.setenv("PATH", f"{directory}:/usr/bin:/bin")
    monkeypatch.setattr(poke_mod, "FALLBACK_BIN_DIRS", ())
    monkeypatch.delenv("CACTUS_RANK", raising=False)
    return directory


def _fake_apint(directory: Path, log: Path, *, exit_code: int = 0,
                rev: str = "reversible", cx: str = "low", sleep: float = 0) -> None:
    # Answers per axis by which axis its --schema names.
    _exe(directory, "apint", f"""echo apint >> {log}
sleep {sleep}
[ {exit_code} -ne 0 ] && exit {exit_code}
case "$*" in
  *'"reversibility"'*) echo '{{"why": "w", "reversibility": "{rev}"}}' ;;
  *) echo '{{"why": "w", "complexity": "{cx}"}}' ;;
esac
""")


def _fake_claude(directory: Path, log: Path, *, rev: str = "costly",
                 cx: str = "med") -> None:
    _exe(directory, "claude", f"""echo claude >> {log}
cat > /dev/null
printf 'reversibility: {rev}\\ncomplexity: {cx}\\n'
""")


def _calls(log: Path) -> list[str]:
    return log.read_text().split() if log.exists() else []


# --- parsing ---------------------------------------------------------------

@pytest.mark.parametrize("output,expected", [
    ("low\n", "low"),
    ("  High. ", "high"),
    ("The answer is med", "med"),
    ("", None),
    ("medium", None),
    ("low or high", None),
])
def test_parse_label(output: str, expected: str | None) -> None:
    assert rank.parse_label(output, rank.COMPLEXITY) == expected


def test_parse_label_reversible_is_not_irreversible() -> None:
    assert rank.parse_label("irreversible", rank.REVERSIBILITY) == "irreversible"
    assert rank.parse_label("reversible", rank.REVERSIBILITY) == "reversible"


@pytest.mark.parametrize("value,expected", [
    ("reversible,low", ("reversible", "low")),
    (" Costly , HIGH ", ("costly", "high")),
    ("reversible", None),
    ("reversible,low,extra", None),
    ("undoable,low", None),
    ("reversible,tiny", None),
])
def test_parse_fixed(value: str, expected: tuple[str, str] | None) -> None:
    got = rank.parse_fixed(value)
    if expected is None:
        assert got is None
    else:
        assert (got.reversibility, got.complexity, got.source) == (*expected, "override")


@pytest.mark.parametrize("output,expected", [
    ("reversibility: reversible\ncomplexity: low\n", ("reversible", "low")),
    ("**Reversibility:** costly\n- complexity: High", ("costly", "high")),
    ("reversibility: reversible", None),
    ("reversibility: reversible or costly\ncomplexity: low", None),
    ("I think it is reversible and low", None),
])
def test_parse_pair(output: str, expected: tuple[str, str] | None) -> None:
    assert rank.parse_pair(output) == expected


# --- gate ------------------------------------------------------------------

@pytest.mark.parametrize("rev", rank.REVERSIBILITY)
@pytest.mark.parametrize("cx", rank.COMPLEXITY)
def test_gate_truth_table(rev: str, cx: str) -> None:
    r = rank.Rank(rev, cx, "override")
    assert r.gated is (rev == "reversible" and cx == "low")
    assert r.reason() == f"{rev} · {cx}"


def test_render_row_clips_and_lists_choices() -> None:
    row = rank.render_row("x" * 5000, "ctx", [("a", "first\nline"), ("b", "")])
    assert len(row) < 2000
    assert "- a: first line" in row and "- b" in row and "Context: ctx" in row
    assert "free-text" in rank.render_row("q?", None, [])


# --- override --------------------------------------------------------------

def test_override_fixed_skips_every_backend(
    bin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log)
    monkeypatch.setenv("CACTUS_RANK", "reversible,low")
    r = rank.classify(*ROW)
    assert r == rank.Rank("reversible", "low", "override") and r.gated
    assert _calls(log) == []


@pytest.mark.parametrize("value", ["off", "none", "OFF", "reversible,tiny"])
def test_override_off_or_malformed_is_none(
    bin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log)
    monkeypatch.setenv("CACTUS_RANK", value)
    assert rank.classify(*ROW) is None
    assert _calls(log) == []


def test_override_template_gets_axis_and_labels(
    bin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = tmp_path / "seen"
    _exe(bin_dir, "ranker", f"""echo "$1 $2" >> {seen}
cat > /dev/null
[ "$1" = reversibility ] && echo costly || echo low
""")
    monkeypatch.setenv("CACTUS_RANK", "ranker {axis} {labels}")
    r = rank.classify(*ROW)
    assert r == rank.Rank("costly", "low", "override") and not r.gated
    assert sorted(seen.read_text().splitlines()) == [
        "complexity low,med,high",
        "reversibility reversible,costly,irreversible",
    ]


def test_override_template_failure_never_reaches_a_model(
    bin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log)
    _fake_claude(bin_dir, log)
    _exe(bin_dir, "ranker", "exit 1\n")
    monkeypatch.setenv("CACTUS_RANK", "ranker {axis}")
    assert rank.classify(*ROW) is None
    monkeypatch.setenv("CACTUS_RANK", "no-such-ranker {axis}")
    assert rank.classify(*ROW) is None
    assert _calls(log) == []


# --- fallback order --------------------------------------------------------

def test_apint_answers_first(bin_dir: Path, tmp_path: Path) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log)
    _fake_claude(bin_dir, log)
    assert rank.classify(*ROW) == rank.Rank("reversible", "low", "apint")
    assert _calls(log) == ["apint", "apint"]


def test_apint_unavailable_falls_to_haiku(bin_dir: Path, tmp_path: Path) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log, exit_code=3)
    _fake_claude(bin_dir, log)
    assert rank.classify(*ROW) == rank.Rank("costly", "med", "haiku")
    assert sorted(_calls(log)) == ["apint", "apint", "claude"]


def test_apint_missing_falls_to_haiku(bin_dir: Path, tmp_path: Path) -> None:
    log = tmp_path / "calls"
    _fake_claude(bin_dir, log, rev="reversible", cx="low")
    r = rank.classify(*ROW)
    assert r == rank.Rank("reversible", "low", "haiku") and r.gated


def test_one_bad_axis_fails_the_backend(bin_dir: Path, tmp_path: Path) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log, cx="unsure")
    _fake_claude(bin_dir, log)
    assert rank.classify(*ROW).source == "haiku"


def test_nothing_reachable_is_none(bin_dir: Path) -> None:
    assert rank.classify(*ROW) is None


def test_haiku_garbage_is_none(bin_dir: Path, tmp_path: Path) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log, exit_code=3)
    _fake_claude(bin_dir, log, rev="maybe", cx="dunno")
    assert rank.classify(*ROW) is None


def test_slow_backend_times_out_and_falls_through(
    bin_dir: Path, tmp_path: Path
) -> None:
    log = tmp_path / "calls"
    _fake_apint(bin_dir, log, sleep=5)
    _fake_claude(bin_dir, log)
    start = time.monotonic()
    r = rank.classify(*ROW, timeout=0.5)
    assert r is not None and r.source == "haiku"
    assert time.monotonic() - start < 3


def test_classify_never_raises(bin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACTUS_RANK", "ranker 'unclosed")
    assert rank.classify(*ROW) is None
    monkeypatch.delenv("CACTUS_RANK")
    assert rank.classify(None, None, None) is None  # type: ignore[arg-type]
