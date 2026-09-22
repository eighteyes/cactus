"""
shell.py — clipboard and command execution for the answering surface.

Responsibilities:
- Copy a command to the system clipboard, naming the tool it used.
- Run a command in a recorded directory, yielding output line by line.
- Spill a full capture to a file when it is too long to read in a card.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

# Ordered by platform likelihood; the first one present wins.
CLIPBOARD_TOOLS = (
    ("pbcopy", []),
    ("wl-copy", []),
    ("xclip", ["-selection", "clipboard"]),
    ("xsel", ["--clipboard", "--input"]),
)


class ShellError(RuntimeError):
    """A clipboard or execution failure worth showing a human verbatim."""


def copy(text: str) -> str:
    """Put `text` on the clipboard. Returns the tool that took it."""
    from shutil import which

    for tool, args in CLIPBOARD_TOOLS:
        if which(tool) is None:
            continue
        try:
            subprocess.run([tool, *args], input=text, text=True, check=True, timeout=5)
        except (subprocess.SubprocessError, OSError) as exc:
            raise ShellError(f"{tool}: {exc}") from exc
        return tool
    raise ShellError("no clipboard tool found (pbcopy, wl-copy, xclip, xsel)")


def run(command: str, *, cwd: str | None = None, timeout: float = 600.0) -> Iterator[str]:
    """Run `command` in `cwd`, yielding output lines as they arrive.

    The command runs through a shell because it was written for one — a review
    block's `run_cmd` is a line a human would paste, pipes and all. It only
    ever runs on an explicit keypress, never on a row arriving.

    The working directory is the row's, not the surface's: a command recorded
    against one repository must not run against whichever project the human
    happens to be looking at.
    """
    workdir = cwd if cwd and Path(cwd).is_dir() else None
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except OSError as exc:
        raise ShellError(str(exc)) from exc

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.stdout.close()
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            yield f"— killed after {timeout:g}s —"
            code = -1
        yield f"— exit {code} —"


def spill(lines: list[str], *, key: str) -> Path:
    """Write a full capture to a file and return its path.

    A card shows a tail. Anything longer than the card needs somewhere to live
    that outlives the next keypress.
    """
    fd, name = tempfile.mkstemp(prefix=f"cactus-{key}-", suffix=".log")
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return Path(name)


def quote(command: str) -> str:
    """A command rendered for display, collapsed to one line."""
    return " ".join(shlex.split(command)) if command else ""
