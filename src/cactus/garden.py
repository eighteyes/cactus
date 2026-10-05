"""
garden.py — persistence for the field's landed cactus pile (the "garden").

Responsibilities:
- Locate the garden file next to the store's own database (`garden_path`),
  so every TUI on the same database reads and writes the same file.
- Serialize a `World`'s `structure`/`drops` to a small JSON-safe dict
  (`dump`) and restore them back into a `World` (`load_into`) — nothing
  else about the world (sky, seeds in flight, birds) is persisted. Under
  `pile_settle == "drop"` a load grounds any floating piece
  (`World.drop_floaters`).
- Read, write, and clear the file on disk (`read`/`save`/`clear`), writing
  atomically so a reader never observes a half-written file.
- Keep a pending-seed queue (`garden-pending`, a count) beside the database
  for answers made outside a TUI key: `add_pending` bumps it, `claim_pending`
  returns and zeroes it, both under an exclusive `flock` so several
  processes claim each seed exactly once. Kept out of garden.json because
  every TUI save rewrites that file from its World.

Pure Python: no Textual, no store import, no knowledge of the TUI.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager


def garden_path(db_path: Path) -> Path:
    """The garden file lives beside the database it belongs to."""
    return db_path.parent / "garden.json"


def dump(world: Any) -> dict[str, Any]:
    """`world`'s landed structure and drop count as a JSON-safe dict."""
    cells = sorted([cx, cy, n] for (cx, cy), n in world.structure.items())
    return {"version": 1, "drops": world.drops, "cells": cells}


def load_into(world: Any, data: dict[str, Any]) -> None:
    """Replace `world.structure`/`world.drops` from `data`.

    Every cell is kept regardless of the world's current `width`/`height` —
    a later resize may bring an out-of-bounds cell back into view. Only
    types are validated; anything else malformed raises `ValueError`.
    Under `pile_settle == "drop"` floating pieces then drop onto the pile.
    """
    if not isinstance(data, dict):
        raise ValueError("garden data must be an object")
    cells = data.get("cells")
    drops = data.get("drops", 0)
    if not isinstance(cells, list):
        raise ValueError("garden 'cells' must be a list")
    if not isinstance(drops, int):
        raise ValueError("garden 'drops' must be an int")
    structure: dict[tuple[int, int], int] = {}
    for entry in cells:
        if (
            not isinstance(entry, list)
            or len(entry) != 3
            or not all(isinstance(v, int) for v in entry)
        ):
            raise ValueError("garden 'cells' entries must be [cx, cy, n] ints")
        cx, cy, n = entry
        structure[(cx, cy)] = n
    world.structure = structure
    world.drops = drops
    world.structure_version += 1
    if world.sky.config.pile_settle == "drop":
        world.drop_floaters()


def save(world: Any, path: Path) -> float:
    """Atomically write `world`'s garden to `path`; returns the new mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dump(world)), encoding="utf-8")
    os.replace(tmp, path)
    return path.stat().st_mtime


def read(path: Path) -> dict[str, Any] | None:
    """The garden file's parsed contents, or `None` when it does not exist."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return json.loads(text)


def clear(path: Path) -> bool:
    """Remove the garden file. Returns whether it existed."""
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def pending_path(db_path: Path) -> Path:
    """The pending-seed count file; only `db_path.parent` is used, so any
    file beside the database (garden.json included) names the same queue."""
    return db_path.parent / "garden-pending"


@contextmanager
def _locked(db_path: Path) -> Iterator[Path]:
    path = pending_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def _read_count(path: Path) -> int:
    try:
        return max(int(path.read_text(encoding="utf-8").strip() or 0), 0)
    except (FileNotFoundError, ValueError):
        return 0


def _write_count(path: Path, n: int) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(str(n), encoding="utf-8")
    os.replace(tmp, path)


def add_pending(db_path: Path, n: int = 1) -> None:
    """Queue `n` seeds for whichever TUI field polls next."""
    with _locked(db_path) as path:
        _write_count(path, _read_count(path) + n)


def claim_pending(db_path: Path, limit: int | None = None) -> int:
    """Take up to `limit` queued seeds (all when `None`) and leave the rest."""
    with _locked(db_path) as path:
        have = _read_count(path)
        took = have if limit is None else min(have, max(limit, 0))
        if took:
            _write_count(path, have - took)
        return took


def pending_count(db_path: Path) -> int:
    """Queued seeds, without claiming them."""
    return _read_count(pending_path(db_path))
