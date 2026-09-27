"""
conftest.py — shared fixtures for the cactus test suite.

Responsibilities:
- Point every test at a scratch database, never the live inbox.
- Make the poke transport inert so no test prompts a real agent.
- Disable decision records unless a test opts in inside a temp git repo.
- Offer a Store, a project path, and a CLI runner that share that scratch state.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cactus.store import Store  # noqa: E402

AGENT = "test-agent"

# The per-project enable/ignore switch (Store.set_project_enabled, `cactus
# project`, the hook gates) is a separate change; tests that need it skip
# until it is in the checkout and run the moment it lands.
needs_project_switch = pytest.mark.skipif(
    not hasattr(Store, "set_project_enabled"),
    reason="project switch not in this checkout",
)


@pytest.fixture
def scratch_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Environment every cactus process in a test must run under."""
    env = {
        "CACTUS_DB": str(tmp_path / "cactus.db"),
        "CACTUS_POKE": "true {agent} {message}",
        "CACTUS_VISIT": "true {pane}",
        "CACTUS_RECORDS": "0",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def project(tmp_path: Path) -> str:
    """A project root that exists on disk; scope.py resolves it to itself."""
    root = tmp_path / "proj"
    root.mkdir()
    return str(root)


@pytest.fixture
def store(scratch_env: dict[str, str]) -> Store:
    s = Store(scratch_env["CACTUS_DB"])
    yield s
    s.close()


@pytest.fixture
def cli(scratch_env: dict[str, str], project: str):
    """Run the cactus CLI as a subprocess from `project`, returning CompletedProcess."""

    def run(*argv: str, cwd: str | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **scratch_env, "PYTHONPATH": str(SRC)}
        return subprocess.run(
            [sys.executable, "-m", "cactus", *argv],
            cwd=cwd or project,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    return run
