"""
test_field.py — World physics: dropping, anchoring, weather, and rendering.

Responsibilities:
- A dropped seed falls to the floor, or anchors on top of / beside the
  structure (including the reverse-pawn diagonal below it).
- Wind stays bounded and clouds wrap inside the world.
- A bird nudges a seed it flies close to.
- The quadrant glyph table maps sub-cell bit patterns to the right character.
- Render produces exactly `rows` lines of `cols` cells; resize keeps the
  structure.
"""

from __future__ import annotations

import random

from rich.cells import cell_len
from rich.text import Text

from cactus.field import Bird, QUADRANT, Seed, World


def run_ticks(world: World, n: int) -> None:
    for _ in range(n):
        world.tick()


def run_seed_ticks(world: World, n: int) -> None:
    """Advance seed physics only, holding wind at 0 for a deterministic fall."""
    for _ in range(n):
        world._tick_seeds()


def test_seed_dropped_over_flat_ground_lands() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.drop(4)
    run_ticks(world, 200)
    assert any(y == 0 for _x, y in world.structure)
    assert not world.seeds


def test_seed_dropped_above_structure_cell_anchors_on_top() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.structure.add((8, 0))
    world.seeds.append(Seed(x=8.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 300)
    assert (8, 1) in world.structure


def test_seed_passing_beside_tall_column_anchors_to_its_side() -> None:
    world = World(cols=10, rows=8, rng=random.Random(3))
    world.structure |= {(8, 0), (8, 1), (8, 2)}
    world.seeds.append(Seed(x=7.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 300)
    assert (7, 3) in world.structure


def test_wind_stays_within_bounds() -> None:
    world = World(cols=10, rows=8, rng=random.Random(5))
    for _ in range(10_000):
        world.tick()
        assert -0.6 <= world.wind <= 0.6


def test_clouds_wrap_within_world_bounds() -> None:
    world = World(cols=10, rows=8, rng=random.Random(7))
    for _ in range(5_000):
        world.tick()
        for cloud in world.clouds:
            assert 0 <= cloud.x < world.width


def test_bird_near_a_seed_changes_its_vx() -> None:
    world = World(cols=10, rows=8, rng=random.Random(9))
    world.wind = 0.0
    seed = Seed(x=10.0, y=10.0, vx=0.0, vy=0.0)
    world.seeds.append(seed)
    world.birds.append(Bird(x=10.5, y=10.0, vx=0.8))
    before = seed.vx
    world.tick()
    assert seed.vx != before


def test_quadrant_glyph_table() -> None:
    assert QUADRANT[0b1111] == "█"
    assert QUADRANT[0b0001] == "▘"
    assert QUADRANT[0b1100] == "▄"


def test_render_returns_exact_rows_and_cols() -> None:
    world = World(cols=12, rows=6, rng=random.Random(11))
    text = world.render()
    lines = text.split("\n")
    assert len(lines) == world.rows
    for line in lines:
        assert cell_len(line.plain) == world.cols


def test_resize_keeps_the_structure() -> None:
    world = World(cols=5, rows=5, rng=random.Random(13))
    world.structure.add((3, 0))
    world.resize(20, 5)
    assert (3, 0) in world.structure
    assert world.width == 40
    assert world.cols == 20
