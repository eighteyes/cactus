"""
test_field.py — World physics: dropping, anchoring, weather, and rendering.

Responsibilities:
- A dropped seed falls to the floor, or anchors on top of / beside the
  structure (including the reverse-pawn diagonal below it).
- Wind stays bounded; the sky's air grids stay within [0, 1] density inside the world.
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
- `World.advance(dt)` is continuous, not per-tick: splitting one step into two
  half-steps moves a seed at terminal velocity the same distance, and the
  wind's Ornstein-Uhlenbeck integration is stable across step sizes.
- A falling seed splats as a tumbling, antialiased Gaussian blob through the
  same braille dither the sky uses, not a full block, and its silhouette
  changes as it spins in place.
- `pile_style == "dots"` (v6d) renders a landed cell as a splatted, dithered
  braille glyph instead of a quadrant block, same age colour either way.
- Two seeds within `stick_distance` merge into one rigid clump that falls,
  lands, and leaves a structure cell per member; seeds far apart never merge
  (v6e).
"""

from __future__ import annotations

import math
import random
import time
from unittest.mock import patch

import pytest
from rich.cells import cell_len
from rich.text import Text

from cactus.field import (
    LANDING_SECONDS,
    TICK_SECONDS,
    WIND_THETA,
    QUADRANT,
    Bird,
    Flock,
    MONO_PLUS,
    Clump,
    World,
)
from cactus.sky import PX_X, PX_Y


def run_ticks(world: World, n: int) -> None:
    for _ in range(n):
        world.tick()


def run_seed_ticks(world: World, n: int) -> None:
    """Advance seed physics only, holding wind at 0 for a deterministic fall."""
    for _ in range(n):
        world._advance_seeds(TICK_SECONDS)


def test_seed_dropped_over_flat_ground_lands() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.drop(4)
    run_ticks(world, 900)
    assert any(y == 0 for _x, y in world.structure)
    assert not world.seeds


def test_seed_dropped_above_structure_cell_anchors_on_top() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.structure[(8, 0)] = 0
    world.seeds.append(Clump(x=8.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 900)
    assert (8, 1) in world.structure


def test_seed_passing_beside_tall_column_anchors_to_its_side() -> None:
    world = World(cols=10, rows=8, rng=random.Random(3))
    world.structure |= {(8, 0): 0, (8, 1): 0, (8, 2): 0}
    world.seeds.append(Clump(x=7.0, y=float(world.height - 1), vx=0.0, vy=0.0))
    run_seed_ticks(world, 900)
    assert (7, 3) in world.structure


def test_wind_stays_within_bounds() -> None:
    world = World(cols=10, rows=8, rng=random.Random(5))
    for _ in range(10_000):
        world.tick()
        assert -0.6 <= world.wind <= 0.6


def test_sky_air_density_stays_within_bounds() -> None:
    world = World(cols=10, rows=8, rng=random.Random(7))
    for _ in range(5_000):
        world.tick()
        for grid in world.sky.grids.values():
            for row in grid.d:
                for v in row:
                    assert 0.0 <= v <= 1.0


def test_bird_near_a_seed_changes_its_vx() -> None:
    world = World(cols=10, rows=8, rng=random.Random(9))
    world.wind = 0.0
    seed = Clump(x=10.0, y=10.0, vx=0.0, vy=0.0)
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
    assert world.sky.grids["near"].width == 40


def test_far_sky_grid_drifts_slower_than_near() -> None:
    world = World(cols=10, rows=12, rng=random.Random(17))
    for _ in range(100):
        world.tick()
    assert world.sky.config.far.wind_scale < world.sky.config.near.wind_scale


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


def test_pile_style_dots_renders_a_braille_glyph_not_a_block() -> None:
    """v6d: the same landed world renders a full block under 'blocks' and a
    braille glyph under 'dots', both still coloured by the cell's age."""
    world = World(cols=10, rows=8, rng=random.Random(29))
    world.drop(4)
    run_ticks(world, 900)
    assert world.structure

    blocks_text = world.render()
    found_block = any(
        any(ch in QUADRANT[1:] for ch in blocks_text.plain[span.start:span.end])
        and span.style == MONO_PLUS.cactus_new
        for span in blocks_text.spans
    )
    assert found_block

    world.sky.config.pile_style = "dots"
    dots_text = world.render()
    found_braille = any(
        any("⠀" <= ch <= "⣿" for ch in dots_text.plain[span.start:span.end])
        and span.style == MONO_PLUS.cactus_new
        for span in dots_text.spans
    )
    assert found_braille


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


# ---- clumps (v6e) --------------------------------------------------------


def test_two_close_seeds_merge_and_land_as_one_clump() -> None:
    world = World(cols=20, rows=10, rng=random.Random(101))
    world.seeds = [
        Clump(x=5.0, y=float(world.height - 1), vx=0.0, vy=0.0),
        Clump(x=6.0, y=float(world.height - 1), vx=0.0, vy=0.0),
    ]
    merged = False
    for _ in range(20):
        world._advance_seeds(TICK_SECONDS)
        if len(world.seeds) == 1 and len(world.seeds[0].members) == 2:
            merged = True
            break
    assert merged, "two seeds 1 sub-cell apart never merged"

    run_seed_ticks(world, 900)
    assert not world.seeds
    assert len(world.structure) == 2


def test_far_apart_seeds_never_merge() -> None:
    world = World(cols=60, rows=10, rng=random.Random(103))
    world.seeds = [
        Clump(x=5.0, y=float(world.height - 1), vx=0.0, vy=0.0),
        Clump(x=45.0, y=float(world.height - 1), vx=0.0, vy=0.0),
    ]
    for _ in range(900):
        world._advance_seeds(TICK_SECONDS)
        assert all(len(c.members) == 1 for c in world.seeds)
    assert not world.seeds
    assert len(world.structure) == 2


def test_merged_clump_has_two_members_and_a_centre_between_the_originals() -> None:
    world = World(cols=20, rows=10, rng=random.Random(105))
    world.seeds = [
        Clump(x=5.0, y=10.0, vx=0.0, vy=0.0),
        Clump(x=6.0, y=10.0, vx=0.0, vy=0.0),
    ]
    world._advance_seeds(TICK_SECONDS)
    assert len(world.seeds) == 1
    merged = world.seeds[0]
    assert len(merged.members) == 2
    assert 5.0 < merged.x < 6.0


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
    world._advance_birds(TICK_SECONDS)
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


# ---- continuous time (v6b) ----------------------------------------------


def test_two_half_steps_move_a_terminal_velocity_seed_as_one_full_step() -> None:
    """No per-tick or per-second snap: splitting `advance` into two 0.05 s
    calls moves a seed already at terminal velocity exactly as far as one
    0.1 s call, since nothing here depends on step count, only elapsed time."""
    world_a = World(cols=10, rows=20, rng=random.Random(61))
    world_b = World(cols=10, rows=20, rng=random.Random(61))
    world_a.wind = world_b.wind = 0.0
    seed_a = Clump(x=5.0, y=30.0, vx=0.0, vy=world_a.terminal_vy, nudged=True)
    seed_b = Clump(x=5.0, y=30.0, vx=0.0, vy=world_b.terminal_vy, nudged=True)
    world_a.seeds = [seed_a]
    world_b.seeds = [seed_b]

    world_a._advance_seeds(0.05)
    world_a._advance_seeds(0.05)
    world_b._advance_seeds(0.1)

    assert seed_a.y == pytest.approx(seed_b.y, abs=1e-9)
    assert seed_a.x == pytest.approx(seed_b.x, abs=1e-9)


def test_wind_integration_is_step_size_stable() -> None:
    """With the noise term held at zero (isolating the Ornstein-Uhlenbeck
    drift), 10 s of 0.1 s steps and 10 s of 0.02 s steps land on the same
    wind within 5% — the integration does not depend on how finely it's
    sliced."""
    world_a = World(cols=10, rows=10, rng=random.Random(1))
    world_b = World(cols=10, rows=10, rng=random.Random(1))
    world_a.wind = world_b.wind = 0.5
    with patch.object(random.Random, "gauss", return_value=0.0):
        for _ in range(100):
            world_a._advance_wind(0.1)
        for _ in range(500):
            world_b._advance_wind(0.02)
    assert world_a.wind == pytest.approx(world_b.wind, rel=0.05)
    assert world_a.wind == pytest.approx(0.5 * math.exp(-WIND_THETA * 10.0), rel=0.05)


def _seed_cell(world: World, seed: Clump) -> tuple[int, int]:
    bx = seed.x * (PX_X / 2)
    by = seed.y * (PX_Y / 2)
    return int(bx) // PX_X, int(by) // PX_Y


def test_falling_seed_renders_a_partial_dot_glyph_not_a_full_block() -> None:
    world = World(cols=6, rows=6, rng=random.Random(71))
    seed = Clump(x=2.5, y=7.5, vx=0.0, vy=0.0, angle=0.3)
    world.seeds = [seed]
    canvas = world._seed_splat_canvas()
    cx, cy = _seed_cell(world, seed)
    block = world._seed_pixel_block(cx, cy, canvas)
    assert block is not None
    from cactus.sky import _ordered_dither

    glyph = _ordered_dither(block)
    dots = bin(ord(glyph) - 0x2800).count("1")
    assert 2 <= dots <= 6, f"{dots} dots, glyph {glyph!r}"


def test_spinning_seed_held_still_renders_different_glyphs_as_it_tumbles() -> None:
    world = World(cols=6, rows=6, rng=random.Random(73))
    seed = Clump(x=3.3, y=7.7, vx=0.0, vy=0.0, angle=0.0, spin=2.0)
    world.seeds = [seed]
    cx, cy = _seed_cell(world, seed)
    from cactus.sky import _ordered_dither

    block_1 = world._seed_pixel_block(cx, cy, world._seed_splat_canvas())
    glyph_1 = _ordered_dither(block_1)

    seed.angle += seed.spin * 0.3  # 0.3 s of held-still spin, no position change
    block_2 = world._seed_pixel_block(cx, cy, world._seed_splat_canvas())
    glyph_2 = _ordered_dither(block_2)

    assert glyph_1 != glyph_2
