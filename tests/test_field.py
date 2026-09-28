"""
test_field.py — World physics: dropping, anchoring, weather, and rendering.

Responsibilities:
- A dropped seed falls to the floor, or anchors on top of / beside the
  structure (including the reverse-pawn diagonal below it).
- Wind stays bounded; the sky's depth layers scroll and wrap inside the world.
- A bird nudges a seed it flies close to, and its colour follows the same
  atmospheric shift as a sky cell's.
- Structure age is counted in `drops` (decisions), not ticks: a landed cell
  stays `cactus_new` through any number of ticks and only ages past further
  `drop()` calls.
- The quadrant glyph table maps sub-cell bit patterns to the right character.
- Render produces exactly `rows` lines of `cols` cells; resize keeps the
  structure and rebakes the sky.
- Ground speckle is a deterministic function of cell position.
- A dropped seed takes roughly a minute (`LANDING_SECONDS`) of ticks to land.
- A flock spawns with a plausible bird count and despawns once it has fully
  crossed off-screen; a near-depth bird renders three cells, a far one renders
  one.
- One tick plus one render at 100x10 stays under the 40 ms frame budget.
"""

from __future__ import annotations

import random
import time

from rich.cells import cell_len
from rich.text import Text

from cactus.field import (
    LANDING_SECONDS,
    TICK_SECONDS,
    QUADRANT,
    Bird,
    Flock,
    MONO_PLUS,
    Seed,
    World,
)


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
    run_ticks(world, 900)
    assert any(y == 0 for _x, y in world.structure)
    assert not world.seeds


def test_seed_dropped_above_structure_cell_anchors_on_top() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.structure[(8, 0)] = 0
    world.seeds.append(Seed(x=8.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 900)
    assert (8, 1) in world.structure


def test_seed_passing_beside_tall_column_anchors_to_its_side() -> None:
    world = World(cols=10, rows=8, rng=random.Random(3))
    world.structure |= {(8, 0): 0, (8, 1): 0, (8, 2): 0}
    world.seeds.append(Seed(x=7.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 900)
    assert (7, 3) in world.structure


def test_wind_stays_within_bounds() -> None:
    world = World(cols=10, rows=8, rng=random.Random(5))
    for _ in range(10_000):
        world.tick()
        assert -0.6 <= world.wind <= 0.6


def test_sky_layer_offsets_wrap_within_bounds() -> None:
    world = World(cols=10, rows=8, rng=random.Random(7))
    for _ in range(5_000):
        world.tick()
        for layer in world.sky.layers.values():
            assert 0 <= layer.offset < layer.period_px


def test_bird_near_a_seed_changes_its_vx() -> None:
    world = World(cols=10, rows=8, rng=random.Random(9))
    world.wind = 0.0
    seed = Seed(x=10.0, y=10.0, vx=0.0, vy=0.0)
    world.seeds.append(seed)
    world.birds.append(Bird(x=10.5, y=10.0, vx=0.8))
    before = seed.vx
    world.tick()
    assert seed.vx != before


def test_bird_colour_shifts_toward_haze() -> None:
    world = World(cols=10, rows=12, rng=random.Random(9))
    colour = world._bird_colour(cy=world.rows - 1, depth=0.5)  # top of the sky
    assert colour != MONO_PLUS.bird
    assert colour.startswith("#")


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


def test_resize_rebakes_the_sky_to_the_new_column_count() -> None:
    world = World(cols=5, rows=8, rng=random.Random(15))
    world.resize(20, 8)
    assert world.sky.cols == 20
    assert world.sky.canvas.width_px == 40


def test_far_sky_layer_moves_slower_than_near() -> None:
    world = World(cols=10, rows=12, rng=random.Random(17))
    for _ in range(100):
        world.tick()
    assert world.sky.layers["far"].offset < world.sky.layers["near"].offset


def test_landed_cell_stays_new_through_ticks_then_ages_on_further_drops() -> None:
    world = World(cols=10, rows=8, rng=random.Random(23))
    world.drop(4)
    run_ticks(world, 900)
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
    run_ticks(world, 900)
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


def test_seed_takes_about_a_minute_to_land() -> None:
    world = World(cols=10, rows=10, rng=random.Random(37))
    world.drop(3)
    landing_ticks = LANDING_SECONDS / TICK_SECONDS
    for i in range(int(landing_ticks * 2)):
        world.tick()
        if not world.seeds:
            assert 0.5 * landing_ticks <= i <= 1.5 * landing_ticks
            break
    else:
        raise AssertionError("seed never landed")


def test_flock_spawns_with_a_plausible_bird_count() -> None:
    world = World(cols=20, rows=10, rng=random.Random(41))
    world._spawn_flock()
    flock = world._flocks[0]
    assert 0 <= len(flock.followers) <= 12
    total = 1 + len(flock.followers)
    assert total == 1 or 5 <= total <= 13


def test_flock_despawns_once_fully_past_the_edge() -> None:
    world = World(cols=10, rows=10, rng=random.Random(43))
    leader = Bird(x=float(world.width + 10), y=10.0, vx=0.2, band="mid", depth=0.6)
    world._flocks.append(Flock(band="mid", leader=leader, followers=[]))
    world._tick_birds()
    assert not world._flocks
    assert not world.birds


def test_near_bird_renders_three_cells_far_bird_renders_one() -> None:
    world = World(cols=20, rows=10, rng=random.Random(47))
    near = Bird(x=10.0, y=10.0, vx=0.25, band="near", depth=0.2, phase=0, glide=False)
    world.birds = [near]
    cells = world._bird_cells()
    assert len(cells) == 3

    far = Bird(x=10.0, y=10.0, vx=0.08, band="far", depth=0.9, phase=0, glide=False)
    world.birds = [far]
    cells = world._bird_cells()
    assert len(cells) == 1


def test_frame_time_at_100x10_stays_under_budget() -> None:
    world = World(cols=100, rows=10, rng=random.Random(51))
    for _ in range(20):
        world.tick()
    n = 20
    start = time.perf_counter()
    for _ in range(n):
        world.tick()
        world.render()
    elapsed = time.perf_counter() - start
    mean_ms = elapsed / n * 1000
    assert mean_ms < 40, f"mean frame time {mean_ms:.2f} ms"
