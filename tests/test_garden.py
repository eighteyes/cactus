"""
test_garden.py — garden.py: persisting the field's landed pile to disk.

Responsibilities:
- `dump`/`load_into` round-trip a `World`'s `structure`/`drops`.
- `save`/`read` write and read the file atomically; `clear` removes it.
- `load_into` raises `ValueError` on malformed data rather than corrupting
  the world it was asked to populate.
"""

from __future__ import annotations

import random

from cactus import garden
from cactus.field import World


def make_world() -> World:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.structure = {(1, 0): 0, (2, 0): 1, (2, 1): 1}
    world.drops = 2
    return world


def test_dump_and_load_into_round_trip() -> None:
    world = make_world()
    data = garden.dump(world)
    other = World(cols=10, rows=8, rng=random.Random(2))
    garden.load_into(other, data)
    assert other.structure == world.structure
    assert other.drops == world.drops


def test_save_and_read_round_trip(tmp_path) -> None:
    world = make_world()
    path = tmp_path / "garden.json"
    mtime = garden.save(world, path)
    assert path.exists()
    assert mtime == path.stat().st_mtime
    data = garden.read(path)
    other = World(cols=10, rows=8, rng=random.Random(3))
    garden.load_into(other, data)
    assert other.structure == world.structure
    assert other.drops == world.drops


def test_save_is_atomic_no_leftover_tmp(tmp_path) -> None:
    world = make_world()
    path = tmp_path / "garden.json"
    garden.save(world, path)
    assert not path.with_suffix(".json.tmp").exists()


def test_read_missing_file_returns_none(tmp_path) -> None:
    assert garden.read(tmp_path / "nope.json") is None


def test_clear_removes_file_and_reports_existence(tmp_path) -> None:
    world = make_world()
    path = tmp_path / "garden.json"
    garden.save(world, path)
    assert garden.clear(path) is True
    assert not path.exists()
    assert garden.clear(path) is False


def test_load_into_malformed_data_raises() -> None:
    world = make_world()
    for bad in (
        {"cells": "not a list", "drops": 0},
        {"cells": [[1, 2]], "drops": 0},
        {"cells": [["a", 1, 0]], "drops": 0},
        {"cells": [], "drops": "not an int"},
        "not a dict",
    ):
        try:
            garden.load_into(world, bad)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_garden_path_lives_beside_db() -> None:
    from pathlib import Path

    assert garden.garden_path(Path("/tmp/scratch/cactus.db")) == Path("/tmp/scratch/garden.json")
