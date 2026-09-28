"""
test_field.py — World physics: dropping, anchoring, weather, and rendering.

Responsibilities:
- A dropped seed falls to the floor, or anchors on top of / beside the
  structure (including the reverse-pawn diagonal below it).
- Wind stays bounded and clouds wrap inside the world.
- A bird nudges a seed it flies close to.
- Cloud depth drives speed (far clouds crawl, near clouds hustle) and glyph/
  colour band.
- Structure age is counted in `drops` (decisions), not ticks: a landed cell
  stays `cactus_new` through any number of ticks and only ages past further
  `drop()` calls.
- The quadrant glyph table maps sub-cell bit patterns to the right character.
- Render produces exactly `rows` lines of `cols` cells; resize keeps the
  structure.
- Ground speckle is a deterministic function of cell position.
"""

from __future__ import annotations

import random

from rich.cells import cell_len
from rich.text import Text

from cactus.field import QUADRANT, Bird, Cloud, MONO_PLUS, Seed, World


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
    world.structure[(8, 0)] = 0
    world.seeds.append(Seed(x=8.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 300)
    assert (8, 1) in world.structure


def test_seed_passing_beside_tall_column_anchors_to_its_side() -> None:
    world = World(cols=10, rows=8, rng=random.Random(3))
    world.structure |= {(8, 0): 0, (8, 1): 0, (8, 2): 0}
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
    world.structure[(3, 0)] = 0
    world.resize(20, 5)
    assert (3, 0) in world.structure
    assert world.width == 40
    assert world.cols == 20


def test_cloud_high_in_the_sky_moves_slower_than_one_near_the_ground() -> None:
    world = World(cols=10, rows=12, rng=random.Random(17))
    far = world._make_cloud(y=float(world.height))  # top of the sky: depth 1, far
    near = world._make_cloud(y=world._sky_floor())  # just above the ground: depth 0, near
    world.clouds = [far, near]
    far_x0, near_x0 = far.x, near.x
    world._tick_clouds()
    far_delta = (far.x - far_x0) % world.width
    near_delta = (near.x - near_x0) % world.width
    assert far_delta < near_delta


def test_cloud_glyph_and_colour_follow_depth_band() -> None:
    world = World(cols=10, rows=12, rng=random.Random(19))
    far = Cloud(x=0.0, y=0.0, w=3.0, speed=0.1, depth=0.9)
    mid = Cloud(x=0.0, y=0.0, w=3.0, speed=0.1, depth=0.5)
    near = Cloud(x=0.0, y=0.0, w=3.0, speed=0.1, depth=0.1)
    assert (world._cloud_glyph(far.depth), world._cloud_colour(far.depth)) == (
        ".",
        MONO_PLUS.cloud_far,
    )
    assert (world._cloud_glyph(mid.depth), world._cloud_colour(mid.depth)) == (
        "~",
        MONO_PLUS.cloud_mid,
    )
    assert (world._cloud_glyph(near.depth), world._cloud_colour(near.depth)) == (
        "o",
        MONO_PLUS.cloud_near,
    )


def test_landed_cell_stays_new_through_ticks_then_ages_on_further_drops() -> None:
    world = World(cols=10, rows=8, rng=random.Random(23))
    world.drop(4)
    run_ticks(world, 200)
    assert world.structure
    cell = next(iter(world.structure))

    age = world._age(cell)
    assert age < 34
    assert world._age_colour(age) == MONO_PLUS.cactus_new

    for _ in range(1000):
        world.tick()
    age = world._age(cell)
    assert age < 34
    assert world._age_colour(age) == MONO_PLUS.cactus_new

    for _ in range(100):
        world.drop(0)
    age = world._age(cell)
    assert age >= 100
    assert world._age_colour(age) == MONO_PLUS.cactus_old


def test_landed_cell_renders_a_quadrant_glyph_in_cactus_new() -> None:
    world = World(cols=10, rows=8, rng=random.Random(29))
    world.drop(4)
    run_ticks(world, 200)
    assert world.structure

    text = world.render()
    plain = text.plain
    found = False
    for span in text.spans:
        chunk = plain[span.start : span.end]
        if any(ch in QUADRANT[1:] for ch in chunk) and span.style == MONO_PLUS.cactus_new:
            found = True
            break
    assert found


def test_ground_speckle_is_deterministic() -> None:
    world = World(cols=16, rows=6, rng=random.Random(31))
    first = world.render().plain
    second = world.render().plain
    assert first == second
