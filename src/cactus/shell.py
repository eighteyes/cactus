"""
shell.py — clipboard and command execution for the answering surface.

Responsibilities:
- Copy a command to the system clipboard, naming the tool it used.
- Run a command in a recorded directory, yielding output line by line.
- Read the exit code back out of a run's captured lines.
- Spill a full capture to a file when it is too long to read in a card.
- Preview (`view`) or edit (`edit`) a row's attached file in the human's
  own pager/editor, resolved from CACTUS_PAGER/CACTUS_EDITOR or the usual
  PAGER/VISUAL/EDITOR fallbacks.
- Open a row's site URL in the platform opener (`open_url`), overridable
  with CACTUS_OPEN.
- Build an inline preview of an attached file: a diff against HEAD when the
  file changed in its repository, else the head of its content.
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


def parse_exit_code(lines: list[str]) -> int:
    """The exit code shell.run recorded as its last "— exit N —" line.

    -1 if the command never got that far — killed, or a start-up failure that
    raised before a shell was ever spawned — matching the "killed" line's own
    exit code, so both read as the same kind of non-completion.
    """
    for line in reversed(lines):
        if line.startswith("— exit") and line.endswith("—"):
            try:
                return int(line.strip("— ").split()[-1])
            except ValueError:
                return -1
    return -1


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


def _run_program(template: str, path: str) -> str:
    """Split `template`, substitute `{path}` (or append it), and run it.

    Runs with `subprocess.call` — no timeout, inherits the tty, so a pager
    or editor gets a real terminal. Returns a short description of what ran.
    """
    if not os.path.exists(path):
        raise ShellError(f"no such file: {path}")
    argv = shlex.split(template)
    if not argv:
        raise ShellError("no program configured")
    if any("{path}" in part for part in argv):
        argv = [part.replace("{path}", path) for part in argv]
    else:
        argv = [*argv, path]
    try:
        subprocess.call(argv)
    except FileNotFoundError:
        raise ShellError(f"{argv[0]}: not found") from None
    except OSError as exc:
        raise ShellError(f"{argv[0]}: {exc}") from exc
    return f"{argv[0]} {path}"


def view(path: str) -> str:
    """Preview `path` in a pager: CACTUS_PAGER, else PAGER, else `less`."""
    template = os.environ.get("CACTUS_PAGER") or os.environ.get("PAGER") or "less"
    return _run_program(template, path)


def edit(path: str) -> str:
    """Open `path` in an editor: CACTUS_EDITOR, else VISUAL, else EDITOR, else `vi`."""
    template = (
        os.environ.get("CACTUS_EDITOR")
        or os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or "vi"
    )
    return _run_program(template, path)


def open_url(url: str) -> str:
    """Open `url` with the platform opener: `open` on macOS, else `xdg-open`.

    CACTUS_OPEN overrides it, a template split with shlex and `{url}`
    substituted per argument (the URL is appended when none carries it).
    Never through a shell. Returns a short description of what ran.
    """
    override = os.environ.get("CACTUS_OPEN")
    if override:
        argv = shlex.split(override)
    else:
        argv = ["open" if sys.platform == "darwin" else "xdg-open", "{url}"]
    if not argv:
        raise ShellError("no program configured")
    if any("{url}" in part for part in argv):
        argv = [part.replace("{url}", url) for part in argv]
    else:
        argv = [*argv, url]
    try:
        done = subprocess.run(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=10,
        )
    except FileNotFoundError:
        raise ShellError(f"{argv[0]}: not found") from None
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShellError(f"{argv[0]}: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise ShellError(f"{argv[0]}: {detail[-1] if detail else f'exit {done.returncode}'}")
    return f"{argv[0]} {url}"


def _vcs(directory: str, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run the repository tool in `directory`; None when missing, slow, or unusable."""
    try:
        return subprocess.run(
            ["git", "-C", directory, *args],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None


def file_preview(path: str, limit: int = 40) -> list[str]:
    """Lines previewing `path`: its diff against HEAD, else its head.

    Header line first, `── path  (state) ──`, where state is `diff vs HEAD`,
    `untracked`, `unchanged`, or `no repo`. Body is capped at `limit` lines
    with a `… N more lines · f to open` tail. A missing file is one
    `missing: PATH` line, a binary one a header plus `binary, N bytes`.
    Nothing is stored; the repository is asked at call time, and any failure
    there falls back to the head of the content.
    """
    target = Path(path)
    if not target.is_file():
        return [f"missing: {path}"]
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return [f"missing: {path} ({exc.strerror or exc})"]

    def header(state: str) -> str:
        return f"── {path}  ({state}) ──"

    if b"\0" in raw[:8192]:
        return [header("binary"), f"binary, {len(raw)} bytes"]

    directory = str(target.parent)
    state = "no repo"
    body: list[str] | None = None
    inside = _vcs(directory, "rev-parse", "--is-inside-work-tree")
    if inside is not None and inside.returncode == 0:
        tracked = _vcs(directory, "ls-files", "--error-unmatch", "--", target.name)
        if tracked is not None and tracked.returncode != 0:
            state = "untracked"
        else:
            state = "unchanged"
            diff = _vcs(
                directory, "diff", "HEAD", "--no-color", "--no-ext-diff", "--", target.name
            )
            if diff is not None and diff.returncode == 0 and diff.stdout.strip():
                state = "diff vs HEAD"
                body = diff.stdout.splitlines()
    if body is None:
        body = raw.decode("utf-8", errors="replace").splitlines()

    lines = [header(state), *body[:limit]]
    if len(body) > limit:
        lines.append(f"… {len(body) - limit} more lines · f to open")
    return lines
