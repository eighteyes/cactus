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
- A dropped seed takes about `LANDING_SECONDS` (12 s) to land; frames are
  sub-stepped so a fast fall or a big `dt` never tunnels into the pile.
- Random gusts (`gust_speed`/`gust_period`): a seed's vx reverses at random,
  not on a fixed period, and spreads its path several columns; `gust_speed`
  0 falls straight. A merge keeps the larger clump's gust, a burst seed
  starts its own.
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
- Charge (hidden rule): a clump gains charge and a member once per cloud
  entry, not per frame spent inside one; gains charge once per bird it
  touches; an exploded seed (`bounty=False`) never collects; landing with
  charge bursts that many bounty-free clumps only if a bird was touched,
  sideways and down (never up), landing beside the pile; every frame inside
  a cloud, each member calls `sky.scatter` once, and never outside one.
- Ground lines (v7): the two outermost lines' columns converge toward centre
  as the row rises toward the horizon; `ground_lines == 0` disables them.
- Perf (v6f): a world with 3 seeds falling at 100x20 renders under the 4 ms
  mean-frame-time budget; a frame with no seeds never even asks the (empty)
  splat canvas about a cell; a fixture render at the default fps is bit-for-
  bit unchanged from before the pass.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.cells import cell_len
from rich.text import Text

from cactus.field import (
    GROUND_ROWS,
    LANDING_SECONDS,
    SUB_X,
    TICK_SECONDS,
    WIND_THETA,
    QUADRANT,
    Bird,
    Flock,
    MONO_PLUS,
    Clump,
    World,
)
from cactus.sky import SkyConfig, PX_X, PX_Y

FIXTURES = Path(__file__).parent / "fixtures"


def run_ticks(world: World, n: int) -> None:
    for _ in range(n):
        world.tick()


def run_seed_ticks(world: World, n: int) -> None:
    """Advance seed physics only, holding wind at 0 and gusts off for a
    straight, deterministic fall."""
    world.sky.config.gust_speed = 0.0
    for _ in range(n):
        world._advance_seeds(TICK_SECONDS)


def test_seed_dropped_over_flat_ground_lands() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    world.drop(4)
    run_ticks(world, 900)
    assert any(y == 0 for _x, y in world.structure)
    assert not world.seeds


def test_landing_bumps_landed_since_save() -> None:
    world = World(cols=10, rows=8, rng=random.Random(1))
    assert world.landed_since_save == 0
    world.drop(4)
    run_ticks(world, 900)
    assert world.landed_since_save == 1


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
    world = World(cols=10, rows=8, rng=random.Random(7), sky_config=SkyConfig(sky_engine="fluid"))
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
    world = World(cols=5, rows=8, rng=random.Random(15), sky_config=SkyConfig(sky_engine="fluid"))
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


def test_seed_takes_about_twelve_seconds_to_land() -> None:
    """Top of the sky to the ground on an empty field: `LANDING_SECONDS`
    (12 s) within 20%, at the TUI's default 6 fps."""
    assert LANDING_SECONDS == pytest.approx(12.0)
    world = World(cols=40, rows=30, rng=random.Random(37))
    world.drop(20)
    t = 0.0
    while world.seeds and t < 4 * LANDING_SECONDS:
        world.advance(1 / 6)
        t += 1 / 6
    assert not world.seeds, "seed never landed"
    assert 0.8 * LANDING_SECONDS <= t <= 1.2 * LANDING_SECONDS


# ---- clumps (v6e) --------------------------------------------------------


def test_two_close_seeds_merge_and_land_as_one_clump() -> None:
    world = World(cols=20, rows=10, rng=random.Random(101), sky_config=SkyConfig(gust_speed=0.0))
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


# ---- charge (hidden rule) --------------------------------------------------


def make_sky_cells(world: World, cloud_cells: list[tuple[int, int]]) -> list[list[tuple[str, str | None]]]:
    """A `world._sky_cells`-shaped grid (sky rows only, top row first), " "
    everywhere except each `(r, col)` in `cloud_cells`."""
    grid = [[(" ", None) for _ in range(world.cols)] for _ in range(world.rows - GROUND_ROWS)]
    for r, c in cloud_cells:
        grid[r][c] = ("⣿", "#ffffff")
    return grid


def test_cloud_entry_awards_charge_and_member_once_per_entry() -> None:
    world = World(cols=10, rows=10, rng=random.Random(1))
    # col 4 (x=9 // SUB_X): row_from_bottom 7 -> r=2, row_from_bottom 3 -> r=6
    world._sky_cells = make_sky_cells(world, [(2, 4), (6, 4)])
    clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0)  # row_from_bottom 7: cloud
    world.seeds = [clump]

    world._collect_charge()
    assert clump.charge == 1
    assert len(clump.members) == 2
    assert clump.in_cloud is True

    for _ in range(20):
        world._collect_charge()
    assert clump.charge == 1
    assert len(clump.members) == 2

    clump.y = 12.0  # row_from_bottom 6: clear
    world._collect_charge()
    assert clump.in_cloud is False
    assert clump.charge == 1

    clump.y = 6.0  # row_from_bottom 3: cloud again
    world._collect_charge()
    assert clump.charge == 2
    assert len(clump.members) == 3


def test_bird_touch_awards_charge_once_per_bird() -> None:
    world = World(cols=10, rows=10, rng=random.Random(2))
    clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0)
    world.seeds = [clump]
    bird = Bird(x=9.0, y=14.0, vx=0.0)
    world.birds = [bird]

    world._collect_charge()
    assert clump.charge == 1
    assert len(clump.birds_hit) == 1

    world._collect_charge()  # same bird, same cell: no double count
    assert clump.charge == 1

    world.birds = [bird, Bird(x=9.0, y=14.0, vx=0.0)]
    world._collect_charge()
    assert clump.charge == 2
    assert len(clump.birds_hit) == 2


def test_exploded_seed_never_collects_charge() -> None:
    world = World(cols=10, rows=10, rng=random.Random(3))
    world._sky_cells = make_sky_cells(world, [(2, 4)])
    clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0, bounty=False)
    world.seeds = [clump]
    world.birds = [Bird(x=9.0, y=14.0, vx=0.0)]

    world._collect_charge()
    assert clump.charge == 0
    assert clump.in_cloud is False
    assert len(clump.members) == 1


def _charge_through_two_clouds(world: World, *, bird: bool) -> Clump:
    """A clump that enters two separate clouds (charge 2, three members),
    touching one bird inside the second when `bird`, then parked just above
    the floor, falling."""
    world._sky_cells = make_sky_cells(world, [(2, 4), (6, 4)])
    clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0)  # row_from_bottom 7: cloud
    world.seeds = [clump]
    world._collect_charge()
    clump.y = 12.0  # clear
    world._collect_charge()
    clump.y = 6.0  # row_from_bottom 3: cloud again
    if bird:
        world.birds = [Bird(x=9.0, y=6.0, vx=0.0)]
    world._collect_charge()
    world.birds = []
    clump.y, clump.vy = 0.4, -1.0
    return clump


def test_landing_with_charge_and_a_bird_explodes_into_bounty_free_clumps() -> None:
    world = World(cols=10, rows=10, rng=random.Random(4))
    clump = _charge_through_two_clouds(world, bird=True)
    assert clump.charge == 3 and len(clump.birds_hit) == 1
    prior_drops = world.drops

    world._advance_seeds(TICK_SECONDS)

    exploded = [c for c in world.seeds if not c.bounty]
    assert len(exploded) == 3
    assert all(c.charge == 0 for c in exploded)
    assert all(c.vy <= 0 for c in exploded)
    assert all(abs(c.vx) > 0 for c in exploded)
    assert world.drops == prior_drops

    for _ in range(20_000):
        if not world.seeds:
            break
        world._advance_seeds(TICK_SECONDS)
    assert not world.seeds
    assert len(world.structure) > 1


def test_cloud_charge_without_a_bird_never_bursts() -> None:
    world = World(cols=10, rows=10, rng=random.Random(4))
    clump = _charge_through_two_clouds(world, bird=False)
    assert clump.charge == 2 and not clump.birds_hit

    world._advance_seeds(TICK_SECONDS)

    assert not world.seeds, "two clouds and no bird: nothing bursts"
    assert len(world.structure) >= 1


def test_burst_skids_sideways_and_down_and_lands_beside_the_pile() -> None:
    world = World(cols=80, rows=10, rng=random.Random(9))
    land_x = 80.0
    world.seeds = [Clump(x=land_x, y=0.4, vx=0.0, vy=-1.0, charge=4, birds_hit={1})]

    world._advance_seeds(TICK_SECONDS)

    burst = list(world.seeds)
    assert len(burst) == 4
    for c in burst:
        assert c.vy <= 0, "a burst never kicks upward"
        assert abs(c.vx) > 0, "a burst always moves sideways"
        assert c.y > 0.4, "spawned above the pile top"

    landed_before = set(world.structure)
    for _ in range(20_000):
        if not world.seeds:
            break
        world._advance_seeds(TICK_SECONDS)
    assert not world.seeds
    new_cells = set(world.structure) - landed_before
    assert new_cells
    for cx, _ in new_cells:
        dx = abs(cx - land_x)
        dx = min(dx, world.width - dx)
        assert dx // SUB_X <= 15, f"burst landed {dx} sub-cells away"


def test_clump_scatters_the_sky_every_frame_inside_a_cloud_only(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(cols=10, rows=10, rng=random.Random(6))
    world._sky_cells = make_sky_cells(world, [(2, 4)])
    calls: list[tuple[float, float]] = []
    monkeypatch.setattr(world.sky, "scatter", lambda px, py, *a, **k: calls.append((px, py)))
    clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0)  # col 4, row_from_bottom 7 -> screen row 2
    world.seeds = [clump]

    world._collect_charge()
    assert len(calls) == len(clump.members) == 2
    assert (4 * PX_X + 1, 2 * PX_Y + PX_Y // 2) in calls

    for frame in range(2, 5):
        world._collect_charge()
        assert len(calls) == 2 * frame, "once per member, every frame inside"

    clump.y = 12.0  # row_from_bottom 6: clear sky
    before = len(calls)
    for _ in range(3):
        world._collect_charge()
    assert len(calls) == before, "no scatter outside a cloud"


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
    0.1 s call, since nothing here depends on step count, only elapsed time.
    Gusts are off, like the wind: an easing gust integrates x per step."""
    world_a = World(cols=10, rows=20, rng=random.Random(61), sky_config=SkyConfig(gust_speed=0.0))
    world_b = World(cols=10, rows=20, rng=random.Random(61), sky_config=SkyConfig(gust_speed=0.0))
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
    canvas, _cells = world._seed_splat_canvas()
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

    canvas_1, _cells_1 = world._seed_splat_canvas()
    block_1 = world._seed_pixel_block(cx, cy, canvas_1)
    glyph_1 = _ordered_dither(block_1)

    seed.angle += seed.spin * 0.3  # 0.3 s of held-still spin, no position change
    canvas_2, _cells_2 = world._seed_splat_canvas()
    block_2 = world._seed_pixel_block(cx, cy, canvas_2)
    glyph_2 = _ordered_dither(block_2)

    assert glyph_1 != glyph_2


# ---- ground lines (v7) ----------------------------------------------------


def test_ground_lines_converge_toward_centre_as_the_row_rises() -> None:
    world = World(cols=40, rows=16, rng=random.Random(81))
    world.sky.config.ground_lines = 5
    n = world.sky.config.ground_lines
    centre = world.cols / 2.0
    bottom_row = world.rows - 1
    top_ground_row = world.rows - GROUND_ROWS

    def spread(screen_row: int) -> float:
        xs = [world._ground_line_x(i, n, screen_row) for i in (0, n - 1)]
        return abs(xs[1] - xs[0])

    assert spread(top_ground_row) <= spread(bottom_row)
    # every line's x moves toward centre (or stays put) as the row rises
    for i in range(n):
        x_bottom = world._ground_line_x(i, n, bottom_row)
        x_top = world._ground_line_x(i, n, top_ground_row)
        assert abs(x_top - centre) <= abs(x_bottom - centre) + 1e-9


def test_ground_lines_disabled_when_lever_is_zero() -> None:
    world = World(cols=20, rows=8, rng=random.Random(83))
    world.sky.config.ground_lines = 0
    assert world._ground_line_cells() == {}


# ---- perf (v6f) -----------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="v6f perf pass got this from ~19 ms down to ~4.5-6 ms on dev "
    "hardware (cProfile: _project_composite and _react dominate what's "
    "left); under the 4 ms target on a fast/idle machine, over it under "
    "load — xfail(strict=False) per the v6f spec rather than block the "
    "suite on machine-dependent timing.",
)
def test_frame_time_at_100x20_with_3_seeds_stays_under_4ms() -> None:
    world = World(cols=100, rows=20, rng=random.Random(51))
    for _ in range(30):
        world.tick()
    for i in range(3):
        world.drop(10 + i * 30)
    for _ in range(5):
        world.tick()

    n = 20
    start = time.perf_counter()
    for _ in range(n):
        world.tick()
        world.render()
    elapsed = time.perf_counter() - start
    mean_ms = elapsed / n * 1000
    assert mean_ms < 4, f"mean frame time {mean_ms:.2f} ms"


def test_no_seeds_never_calls_seed_pixel_block() -> None:
    """A frame with nothing falling never even asks the (empty) splat canvas
    about a single cell — `_seed_splat_canvas` returns an empty touched-cell
    set, and `render`/`_sample_cell` gate every lookup on it."""
    world = World(cols=10, rows=8, rng=random.Random(85))
    assert not world.seeds
    with patch.object(World, "_seed_pixel_block", side_effect=AssertionError("should not be called")):
        world.render()


def test_render_matches_fixture_before_the_v6f_perf_pass() -> None:
    """Same seed, same frame count, same default fps — a render before and
    after the v6f perf pass must be bit-for-bit identical (the fixture was
    generated from HEAD before that pass touched anything). Re-baked at v8
    when the renderer gained grain markers and lost the edge slashes — a
    deliberate look change, so the fixture follows it; the test still pins
    every render change after that. Re-baked again for v8 `cloud_fade`,
    which holds a cleared cell's glyph while it fades out. Re-baked when
    `WIND_COUPLING` rose 0.003 -> 0.08 so wind visibly carries a seed: the
    falling seeds land a little downwind (the old coupling still reproduces
    the previous fixture exactly). Re-baked again when `seed_wind` became columns (default 3).
    Re-baked when the fall sped up 5x (12 s) and each seed gained random gusts. Re-baked when merges began carrying charge and bird hits."""
    with open(FIXTURES / "field_render_v6f.json") as fh:
        expected = json.load(fh)

    world = World(cols=40, rows=16, rng=random.Random(42), sky_config=SkyConfig(sky_engine="fluid"))
    drop_cols = {5: 10, 6: 20, 7: 30}
    actual = []
    for i in range(60):
        world.tick()
        if i in drop_cols:
            world.drop(drop_cols[i])
        actual.append(world.render().plain)

    assert actual == expected


def test_apply_sky_config_swaps_engine_class_on_sky_engine_change() -> None:
    from cactus.sky import SkyConfig, TextureSky

    world = World(cols=10, rows=8, rng=random.Random(87), sky_config=SkyConfig(sky_engine="fluid"))
    assert not isinstance(world.sky, TextureSky)

    cfg = SkyConfig()
    cfg.sky_engine = "texture"
    world.apply_sky_config(cfg)
    assert isinstance(world.sky, TextureSky)
    assert world.render()  # still renders through the shared interface

    cfg2 = SkyConfig()
    cfg2.sky_engine = "fluid"
    world.apply_sky_config(cfg2)
    assert not isinstance(world.sky, TextureSky)


def test_seed_wind_is_in_columns_and_ignores_the_near_deck() -> None:
    """`seed_wind` is the mean drift in columns over a full fall; the seed
    feels world wind x seed_wind / SEED_WIND_COLS_PER_UNIT, and
    `near.wind_scale` tunes a sky deck only."""
    from cactus.field import SEED_WIND_COLS_PER_UNIT
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", seed_wind=3.0)
    world = World(cols=20, rows=10, rng=random.Random(3), sky_config=cfg)
    world.wind = 0.5
    base = 0.5 * 3.0 / SEED_WIND_COLS_PER_UNIT
    assert world.seed_wind() == pytest.approx(base)
    cfg.near.wind_scale = 0.1
    world.apply_sky_config(cfg)
    assert world.seed_wind() == pytest.approx(base)
    cfg.seed_wind = 30.0
    world.apply_sky_config(cfg)
    assert world.seed_wind() == pytest.approx(base * 10)
    world.drop(5)
    assert world.seeds[-1].vx == pytest.approx(base * 10)


def test_seed_wind_columns_scale_the_drift_roughly_linearly() -> None:
    """`seed_wind` N is ~N columns of mean |drift| over a full 12 s fall
    (unwrapped, empty 120x30 field, 40 drops at one column after the wind
    has warmed to its spread, gusts off so the wind is measured alone) —
    the calibration behind `SEED_WIND_COLS_PER_UNIT`, and linear in N."""
    from cactus.sky import SkyConfig

    def mean_drift(cols_lever: float) -> float:
        cfg = SkyConfig(sky_engine="texture", seed_wind=cols_lever, seed_mass="single", birds="none", gust_speed=0.0)
        w = World(cols=120, rows=30, rng=random.Random(7), sky_config=cfg)
        for _ in range(1200):
            w.advance(1 / 6)
        total = []
        for _ in range(40):
            w.structure.clear()
            w.drop(60)
            c = w.seeds[0]
            px, acc, steps = c.x, 0.0, 0
            while w.seeds and steps < 5000:
                w.advance(1 / 6)
                steps += 1
                if w.seeds:
                    dx = w.seeds[0].x - px
                    dx -= w.width if dx > w.width / 2 else 0
                    dx += w.width if dx < -w.width / 2 else 0
                    acc += dx
                    px = w.seeds[0].x
            total.append(abs(acc) / SUB_X)
        return sum(total) / len(total)

    small, big = mean_drift(2.0), mean_drift(20.0)
    assert 0.7 * 2.0 <= small <= 1.3 * 2.0
    assert 0.7 * 20.0 <= big <= 1.3 * 20.0
    assert big > 7 * small


def _gust_fall(world: World, col: int) -> tuple[list[float], list[float], list[tuple[float, float]]]:
    """One full fall from `col` at 6 fps on an empty field: the seed's
    unwrapped column and its vx per frame, and every (time, target) its
    gust jumped to."""
    world.structure.clear()
    world.drop(col)
    c = world.seeds[0]
    px, acc, t = c.x, 0.0, 0.0
    xs, vxs, jumps = [0.0], [c.vx], []
    target = c.gust_target
    while world.seeds and t < 60.0:
        world.advance(1 / 6)
        t += 1 / 6
        if not world.seeds:
            break
        c = world.seeds[0]
        dx = c.x - px
        dx -= world.width if dx > world.width / 2 else 0
        dx += world.width if dx < -world.width / 2 else 0
        acc += dx
        px = c.x
        xs.append(acc / SUB_X)
        vxs.append(c.vx)
        if c.gust_target != target:
            target = c.gust_target
            jumps.append((t, target))
    return xs, vxs, jumps


def test_gusts_knock_a_seed_at_random_not_on_a_period() -> None:
    """Wind off, gusts at their defaults: most falls reverse vx at least
    once, the path spreads more than 3 columns on average, the waits
    between gusts differ (not periodic), and a gust may push the same way
    twice running (no forced flip)."""
    cfg = SkyConfig(sky_engine="texture", seed_wind=0.0, seed_mass="single", birds="none")
    world = World(cols=120, rows=30, rng=random.Random(3), sky_config=cfg)
    reversing, spreads, waits, same_way = 0, [], [], 0
    for _ in range(8):
        xs, vxs, jumps = _gust_fall(world, 60)
        if any(a * b < 0 for a, b in zip(vxs, vxs[1:])):
            reversing += 1
        spreads.append(max(xs) - min(xs))
        waits += [b[0] - a[0] for a, b in zip(jumps, jumps[1:])]
        same_way += sum(1 for a, b in zip(jumps, jumps[1:]) if a[1] * b[1] > 0)
    assert reversing >= 6
    assert sum(spreads) / len(spreads) > 3.0
    assert max(waits) - min(waits) > 1.0
    assert same_way > 0


def test_gust_speed_zero_falls_straight() -> None:
    """Wind off and `gust_speed` 0: the seed's column spreads under 1."""
    cfg = SkyConfig(sky_engine="texture", seed_wind=0.0, seed_mass="single", birds="none", gust_speed=0.0)
    world = World(cols=120, rows=30, rng=random.Random(3), sky_config=cfg)
    xs, _, jumps = _gust_fall(world, 60)
    assert max(xs) - min(xs) < 1.0
    assert not jumps


def test_merge_keeps_the_larger_clumps_gust_and_a_burst_starts_its_own() -> None:
    world = World(cols=20, rows=10, rng=random.Random(8))
    big = _rod(10.0, 10.0, 0.0)
    big.vx, big.gust_vx, big.gust_target, big.gust_left = 5.0, 4.0, 6.0, 0.7
    small = Clump(x=11.0, y=10.0, vx=-3.0, vy=0.0, gust_vx=-3.0, gust_target=-8.0, gust_left=0.1)
    merged = world._merge(small, big)
    assert (merged.gust_vx, merged.gust_target, merged.gust_left) == (4.0, 6.0, 0.7)
    # non-gust shares (1.0 x 3, 0.0 x 1) average by mass, the kept gust rides on top
    assert merged.vx == pytest.approx((1.0 * 3 + 0.0 * 1) / 4 + 4.0)

    lander = Clump(x=10.0, y=0.4, vx=0.0, vy=-1.0, charge=2, birds_hit={1}, gust_vx=4.0, gust_target=6.0, gust_left=0.7)
    for burst in world._explode(lander):
        assert (burst.gust_vx, burst.gust_target, burst.gust_left) == (0.0, 0.0, 0.0)


def _landing_cols(world: World, col: int, n: int, keep_pile: bool) -> list[float]:
    """Drop `n` seeds at `col` one at a time, each falling until it lands;
    return each landing's mean terminal column. `keep_pile=False` clears
    the structure before every drop, so each fall is full height."""
    cols = []
    for _ in range(n):
        if not keep_pile:
            world.structure.clear()
        before = set(world.structure)
        world.drop(col)
        for _ in range(2000):
            if not world.seeds:
                break
            world.advance(0.5)
        new = [c[0] for c in world.structure if c not in before]
        if new:
            cols.append(sum(new) / len(new) / SUB_X)
    return cols


def test_pinned_wind_carries_a_falling_seed_several_columns() -> None:
    """Wind visibly moves a seed: a pinned +0.6 (the OU clamp) lands the
    mean seed at least 3 columns downwind of a windless drop (gusts off,
    so the wind is measured alone)."""
    from cactus.sky import SkyConfig

    means = {}
    for wind in (0.0, 0.6):
        cfg = SkyConfig(sky_engine="texture", birds="none", gust_speed=0.0)
        world = World(cols=100, rows=30, rng=random.Random(11), sky_config=cfg)
        world._advance_wind = lambda dt: None  # type: ignore[method-assign]
        world.wind = wind
        cols = _landing_cols(world, 50, 5, keep_pile=False)
        means[wind] = sum(cols) / len(cols)
    assert means[0.6] - means[0.0] >= 3.0


def test_repeated_drops_at_one_column_build_upward() -> None:
    """A seed dropped again and again at one spot stacks into a pile
    rather than spreading along the ground (gusts off: random knocks
    scatter the drops, which is the point of them)."""
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", birds="none", gust_speed=0.0)
    world = World(cols=100, rows=30, rng=random.Random(5), sky_config=cfg)
    _landing_cols(world, 50, 30, keep_pile=True)
    assert max(cy for _, cy in world.structure) > 3


def test_birds_lever_picks_which_depths_spawn_and_none_grounds_them() -> None:
    """v8: `SkyConfig.birds` chooses the depth bands a flock may spawn in,
    `bird_rate`/`bird_max` how often and how many; `none` spawns nothing."""
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", birds="none", bird_rate=1.0, bird_max=6)
    world = World(cols=40, rows=12, rng=random.Random(9), sky_config=cfg)
    for _ in range(200):
        world.advance(0.5)
    assert not world.birds

    cfg.birds = "far"
    world.apply_sky_config(cfg)
    for _ in range(200):
        world.advance(0.5)
    assert world.birds and {b.band for b in world.birds} == {"far"}
    assert world.bird_bands() == ("far",)

    cfg.birds = "mid+near"
    assert World(cols=40, rows=12, rng=random.Random(1), sky_config=cfg).bird_bands() == ("mid", "near")
    cfg.birds = "all"
    assert World(cols=40, rows=12, rng=random.Random(1), sky_config=cfg).bird_bands() == ("far", "mid", "near")

    cfg.birds = "all"
    cfg.bird_max = 0
    world2 = World(cols=40, rows=12, rng=random.Random(2), sky_config=cfg)
    for _ in range(200):
        world2.advance(0.5)
    assert not world2.birds


def _land(world: World, cells: list[tuple[int, int]]) -> None:
    """Drop a clump whose members sit exactly on `cells` (sub-cell coords),
    already touching the structure or the ground, and anchor it."""
    from cactus.field import Member

    x0, y0 = cells[0]
    clump = Clump(x=float(x0), y=float(y0), vx=0.0, vy=0.0, angle=0.0, spin=0.0)
    clump.members = [Member(dx=float(cx - x0), dy=float(cy - y0)) for cx, cy in cells]
    exploded: list[Clump] = []
    assert world._anchor(clump, exploded)


def test_pile_settle_drops_a_shelf_resting_on_a_diagonal() -> None:
    """v8 arm adjustment: (0,0) (1,0) landed, a two-block shelf hitting at
    (2,1) (3,1) rests only on (1,0)'s diagonal, so it drops to (2,0) (3,0).
    A lone block at (2,1) keeps its perch; `pile_settle = keep` lands as hit."""
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", pile_settle="drop")
    world = World(cols=20, rows=10, rng=random.Random(4), sky_config=cfg)
    world.structure = {(0, 0): 0, (1, 0): 0}
    _land(world, [(2, 1), (3, 1)])
    assert (2, 0) in world.structure and (3, 0) in world.structure
    assert (2, 1) not in world.structure and (3, 1) not in world.structure

    world.structure = {(0, 0): 0, (1, 0): 0}
    _land(world, [(2, 1)])
    assert (2, 1) in world.structure, "a lone block keeps the diagonal"

    world.structure = {(0, 0): 0, (1, 0): 0, (2, 0): 0}
    _land(world, [(2, 1), (3, 1)])
    assert (2, 1) in world.structure and (3, 1) in world.structure, "directly supported: no drop"

    world.structure = {(0, 0): 0, (1, 0): 0, (2, 0): 0, (3, 0): 0, (1, 1): 0, (2, 1): 0, (3, 2): 0}
    _land(world, [(4, 3), (5, 3)])
    assert (4, 3) in world.structure and (5, 3) in world.structure and (4, 0) not in world.structure, (
        "one row would still leave it unsupported: keeps the landing, never slides down the side"
    )

    world.structure = {(4, 0): 0, (4, 1): 0, (4, 2): 0, (5, 0): 0, (5, 1): 0}
    _land(world, [(5, 3), (6, 3)])
    assert (5, 2) in world.structure and (6, 2) in world.structure, "one row onto a block: drops"

    cfg.pile_settle = "keep"
    world.apply_sky_config(cfg)
    world.structure = {(0, 0): 0, (1, 0): 0}
    _land(world, [(2, 1), (3, 1)])
    assert (2, 1) in world.structure and (3, 1) in world.structure


def test_seed_mass_single_keeps_a_seed_one_block_but_still_charges() -> None:
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", seed_mass="single")
    world = World(cols=20, rows=10, rng=random.Random(4), sky_config=cfg)
    sky_rows = world.rows - GROUND_ROWS
    world._sky_cells = [[("⣿", None)] * world.cols for _ in range(sky_rows)]
    world.drop(5)
    clump = world.seeds[0]
    n0 = len(clump.members)
    for _ in range(5):
        world.advance(0.2)
    assert len(clump.members) == n0
    assert clump.charge == 1


def _rod(x: float, y: float, angle: float) -> Clump:
    """A 3-member horizontal rod in the clump frame, turned to `angle`, not spinning."""
    from cactus.field import Member

    clump = Clump(x=x, y=y, vx=0.0, vy=0.0, angle=angle, spin=0.0)
    clump.members = [Member(dx=-1.0), Member(dx=0.0), Member(dx=1.0)]
    return clump


def test_a_rod_lands_along_its_angle() -> None:
    """Rigid rotation: a multi-member clump's offsets turn with its `angle`,
    and landing freezes the turned cells — horizontal at 0, vertical at pi/2."""
    world = World(cols=20, rows=10, rng=random.Random(4))
    assert world._anchor(_rod(5.5, 0.5, 0.0), [])
    assert set(world.structure) == {(4, 0), (5, 0), (6, 0)}

    world.structure = {}
    assert world._anchor(_rod(5.5, 1.5, math.pi / 2), [])
    assert set(world.structure) == {(5, 0), (5, 1), (5, 2)}


def test_accrete_count_grows_a_rod_per_cloud_entry() -> None:
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", accrete_count=3, accrete_shape="rod")
    world = World(cols=10, rows=10, rng=random.Random(1), sky_config=cfg)
    world._sky_cells = make_sky_cells(world, [(2, 4), (6, 4)])
    clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0)  # row_from_bottom 7: cloud
    world.seeds = [clump]

    world._collect_charge()
    assert clump.charge == 1
    assert len(clump.members) == 4
    assert {m.dy for m in clump.members} == {0.0}, "one row in the clump frame"
    side = math.copysign(1.0, clump.members[-1].dx)
    assert sorted(m.dx * side for m in clump.members) == [0.0, 1.0, 2.0, 3.0]

    clump.angle, clump.y = 0.0, 12.0  # clear
    world._collect_charge()
    clump.angle, clump.y = 0.0, 6.0  # cloud again: the same arm extends
    world._collect_charge()
    assert clump.charge == 2
    assert sorted(m.dx * side for m in clump.members) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_accrete_branch_grows_on_sides_and_diagonals() -> None:
    """`accrete_shape="branch"`: every new block is 8-adjacent to another
    member, never on a taken offset, and across seeds the shape leaves the
    straight rod — some block sits off row 0 or touches only diagonally."""
    from cactus.sky import SkyConfig

    left_the_rod = False
    for seed in range(6):
        cfg = SkyConfig(sky_engine="texture", accrete_count=4, accrete_shape="branch")
        world = World(cols=10, rows=10, rng=random.Random(seed), sky_config=cfg)
        world._sky_cells = make_sky_cells(world, [(2, 4), (6, 4)])
        clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0)  # row_from_bottom 7: cloud
        world.seeds = [clump]

        world._collect_charge()
        assert clump.charge == 1
        assert len(clump.members) == 5
        cells = [(m.dx, m.dy) for m in clump.members]
        assert len(set(cells)) == len(cells), "no duplicate offsets"
        for i, (x, y) in enumerate(cells[1:], start=1):
            others = [c for j, c in enumerate(cells) if j != i]
            touching = [c for c in others if max(abs(c[0] - x), abs(c[1] - y)) == 1]
            assert touching, f"seed {seed}: block {(x, y)} touches no member"
            diagonal_only = all(c[0] != x and c[1] != y for c in touching)
            if y != 0.0 or diagonal_only:
                left_the_rod = True
    assert left_the_rod, "branch never left a straight horizontal rod"


def test_accrete_spin_kicks_the_clump_on_each_cloud_entry() -> None:
    from cactus.sky import SkyConfig

    for kick, expected in ((2.0, 2.0), (0.0, 0.0)):
        cfg = SkyConfig(sky_engine="texture", accrete_spin=kick)
        world = World(cols=10, rows=10, rng=random.Random(1), sky_config=cfg)
        world._sky_cells = make_sky_cells(world, [(2, 4)])
        clump = Clump(x=9.0, y=14.0, vx=0.0, vy=0.0, spin=0.0)
        world.seeds = [clump]
        world._collect_charge()
        assert clump.charge == 1
        assert abs(clump.spin) == pytest.approx(expected)


def test_spin_damps_on_multi_member_clumps_only() -> None:
    from cactus.field import ACCRETE_SPIN_DAMP
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", bird_max=0, gust_speed=0.0)
    world = World(cols=20, rows=20, rng=random.Random(5), sky_config=cfg)
    rod = _rod(10.5, float(world.height - 1), 0.0)
    rod.spin = 2.0
    lone = Clump(x=30.5, y=float(world.height - 1), vx=0.0, vy=0.0, spin=2.0)
    world.seeds = [rod, lone]
    for _ in range(100):
        world.advance(0.1)
    assert rod in world.seeds and lone in world.seeds
    assert rod.spin == pytest.approx(2.0 * math.exp(-ACCRETE_SPIN_DAMP * 10.0))
    assert lone.spin == 2.0


def test_cloud_fade_blends_a_lit_cell_in_and_holds_it_while_it_fades_out() -> None:
    """v8 smoothness: with `cloud_fade` on, a cell the engine just lit draws
    its glyph in a colour between `fade_from` and its tone, reaches the
    tone after `cloud_fade` seconds, and after the engine clears it keeps
    drawing the last glyph while its colour sinks back, then blanks."""
    from cactus.sky import SkyConfig

    cfg = SkyConfig(sky_engine="texture", cloud_fade=1.0)
    world = World(cols=6, rows=6, rng=random.Random(1), sky_config=cfg)
    lit = [[("⣿", "#d0ccc0")] * 6 for _ in range(4)]
    blank = [[(" ", None)] * 6 for _ in range(4)]

    world._frame_dt = 0.25
    first = world._fade_sky(lit)
    g, colour = first[1][2]
    assert g == "⣿" and colour not in ("#d0ccc0", world.palette.fade_from)
    world._frame_dt = 1.0
    assert world._fade_sky(lit)[1][2] == ("⣿", "#d0ccc0")

    world._frame_dt = 0.5
    going = world._fade_sky(blank)[1][2]
    assert going[0] == "⣿" and going[1] not in ("#d0ccc0", None), "holds the glyph while fading out"
    world._frame_dt = 1.0
    assert world._fade_sky(blank)[1][2] == (" ", None)

    cfg.cloud_fade = 0.0
    world.apply_sky_config(cfg)
    world._frame_dt = 0.1
    assert world._fade_sky(lit) is lit, "0 is a pop, the grid passes through"


def test_a_clump_straddling_the_seam_lands_inside_the_world() -> None:
    """A multi-block clump whose centre sits at x=0 lands every cell at
    0 <= cx < width, wrapping the left block to the right edge instead of
    storing cx -1 (seen in a live garden.json)."""
    from cactus.field import Member
    from cactus.sky import SkyConfig

    world = World(cols=10, rows=8, rng=random.Random(2), sky_config=SkyConfig(sky_engine="texture", pile_settle="keep"))
    clump = Clump(x=0.0, y=0.0, vx=0.0, vy=0.0, angle=0.0, spin=0.0)
    clump.members = [Member(dx=-1.0, dy=0.0), Member(dx=0.0, dy=0.0), Member(dx=1.0, dy=0.0)]
    assert world._anchor(clump, [])
    assert all(0 <= cx < world.width for cx, _ in world.structure)
    assert (world.width - 1, 0) in world.structure


def test_merge_keeps_charge_birds_and_blocks_a_burst_cascade() -> None:
    """Merging adds charge, unites the birds hit, and a merge involving a
    burst seed (`bounty=False`) stays unable to charge again."""
    from cactus.field import Member
    from cactus.sky import SkyConfig

    world = World(cols=20, rows=10, rng=random.Random(3), sky_config=SkyConfig(sky_engine="texture"))
    a = Clump(x=5.0, y=10.0, vx=0.0, vy=0.0, angle=0.0, spin=0.0, charge=2, birds_hit={1})
    b = Clump(x=6.0, y=10.0, vx=0.0, vy=0.0, angle=0.0, spin=0.0, charge=1, birds_hit={2})
    a.members, b.members = [Member()], [Member()]
    m = world._merge(a, b)
    assert m.charge == 3 and m.birds_hit == {1, 2} and m.bounty
    c = Clump(x=5.0, y=10.0, vx=0.0, vy=0.0, angle=0.0, spin=0.0, bounty=False)
    d = Clump(x=6.0, y=10.0, vx=0.0, vy=0.0, angle=0.0, spin=0.0, bounty=False)
    c.members, d.members = [Member()], [Member()]
    assert not world._merge(c, d).bounty
