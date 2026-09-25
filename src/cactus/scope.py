"""
scope.py — resolve the project scope a question belongs to, from a working directory.

Responsibilities:
- Resolve a directory to a stable project root (git toplevel, else the directory itself).
- Map a linked git worktree to its main repository's toplevel, so rows asked
  from a worktree file under the same project as the main checkout.
- Produce a short display label for a project root.
- Provide the default scope for agent-side commands (the current working directory).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git_toplevel(start: Path) -> Path | None:
    """Return the git toplevel containing `start`, or None if it is not in a repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    top = out.stdout.strip()
    return Path(top) if top else None


def git_main_toplevel(start: Path) -> Path | None:
    """Return the main repository's toplevel for `start`, resolving linked worktrees.

    A linked worktree (`git worktree add`) has its own `--show-toplevel` but
    shares a common git dir with the main checkout. When `--git-common-dir`
    and `--git-dir` differ, `start` is inside a linked worktree; the parent of
    the common dir is the main worktree's toplevel. When they are equal,
    `start` is already the main worktree (or a bare repo), and this falls
    back to `git_toplevel`.
    """
    try:
        common = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        local = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return git_toplevel(start)
    if common.returncode != 0 or local.returncode != 0:
        return git_toplevel(start)
    common_dir = common.stdout.strip()
    local_dir = local.stdout.strip()
    if not common_dir or not local_dir:
        return git_toplevel(start)
    common_path = (start / common_dir).resolve()
    local_path = (start / local_dir).resolve()
    if common_path == local_path:
        return git_toplevel(start)
    return common_path.parent


def resolve_project(cwd: str | os.PathLike[str] | None = None) -> tuple[str, str]:
    """Resolve `cwd` to (project_root, cwd) as absolute posix strings.

    The project root is the git toplevel when one exists, otherwise the
    directory itself. A linked worktree resolves to its main repository's
    toplevel (`CACTUS_SCOPE=worktree` restores the old per-worktree
    behaviour). Both values are stored on every question so the TUI can
    group by project while still showing where a question was actually asked.
    """
    here = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    if here.is_file():
        here = here.parent
    if os.environ.get("CACTUS_SCOPE") == "worktree":
        root = git_toplevel(here) or here
    else:
        root = git_main_toplevel(here) or here
    return (str(root), str(here))


def project_label(project_root: str) -> str:
    """Short, human-readable label for a project root."""
    path = Path(project_root)
    home = Path.home()
    try:
        rel = path.relative_to(home)
    except ValueError:
        return path.name or str(path)
    parts = rel.parts
    if not parts:
        return "~"
    return parts[-1]


def project_display(project_root: str) -> str:
    """Full display path for a project root, with the home directory elided."""
    path = Path(project_root)
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)
