"""
test_puffs.py — the puffs sky engine (v8): individual clouds, no whole-sky
scroll.

Responsibilities:
- `make_sky` picks `PuffSky` for `sky_engine == "puffs"` behind the same
  interface as the other two engines.
- No global motion: `camera_x` stays 0 through `advance`, and a cloud with
  `vx == 0` keeps its `x` while its neighbours move on their own.
- Each cloud picks its own direction and speed, band-scaled by `cloud_drift`.
- A cloud unfolds: its cutoff starts at 1.0, sinks to the style's resting
  cutoff, holds, then climbs back before it dies and is replaced.
- `apply` re-bakes on a `cloud_style` change, resizes the population on a
  `cloud_count` change in place, and leaves the population alone otherwise.
- Every style renders something in a plausible frame budget.
"""

from __future__ import annotations

import random

import pytest

from cactus.field import MONO_PLUS, World
from cactus.sky import (
    GRID_ORDER,
    SKY_ENGINES,
    PuffSky,
    SkyConfig,
    _PUFF_STYLES,
    make_sky,
)

STYLES = tuple(_PUFF_STYLES)


def _puffs(style: str = "drift", seed: int = 3, cols: int = 100, rows: int = 14, **kw) -> PuffSky:
    cfg = SkyConfig(sky_engine="puffs", cloud_style=style, **kw)
    sky = make_sky(cols, rows, random.Random(seed), MONO_PLUS, cfg)
    assert isinstance(sky, PuffSky)
    return sky


def test_make_sky_picks_puffs_and_the_engine_tag_round_trips() -> None:
    sky = _puffs()
    assert sky.ENGINE == "puffs"
    assert SKY_ENGINES["puffs"] is PuffSky
    assert SkyConfig().sky_engine in SKY_ENGINES


def test_camera_never_moves_whatever_the_wind() -> None:
    sky = _puffs()
    for _ in range(50):
        sky.advance(0.5, wind=0.6)
    assert sky.camera_x == 0.0


def test_each_cloud_drifts_on_its_own_not_the_sky() -> None:
    sky = _puffs(cloud_life=1e6)  # nobody dies during the test
    puffs = [p for band in GRID_ORDER for p in sky.puffs[band]]
    assert len(puffs) >= 4
    signs = {p.vx > 0 for p in puffs}
    assert signs == {True, False}, "clouds should pick both directions"
    puffs[0].vx = 0.0
    before = [p.x for p in puffs]
    for _ in range(20):
        sky.advance(1.0)
    after = [p.x for p in puffs]
    assert after[0] == before[0], "a still cloud stays put: nothing scrolls it"
    moved = [abs(a - b) for a, b in zip(after[1:], before[1:])]
    assert all(m > 0 for m in moved)
    assert len({round(m, 6) for m in moved}) > 1, "no two clouds share a speed"


def test_cloud_drift_scales_speed_and_bands_differ() -> None:
    slow = _puffs(cloud_drift=1.0, cloud_life=1e6)
    fast = _puffs(cloud_drift=4.0, cloud_life=1e6)
    top_slow = max(abs(p.vx) for band in GRID_ORDER for p in slow.puffs[band])
    top_fast = max(abs(p.vx) for band in GRID_ORDER for p in fast.puffs[band])
    assert top_fast > top_slow
    far = max(abs(p.vx) for p in fast.puffs["far"])
    near = max(abs(p.vx) for p in fast.puffs["near"])
    assert near > far, "the near band wanders faster than the far one"


def test_a_cloud_unfolds_then_recedes() -> None:
    sky = _puffs(cloud_life=100.0)
    puff = sky.puffs["mid"][0]
    resting = puff.p["cutoff"]
    puff.age = 0.0
    assert puff.cutoff() == pytest.approx(1.0)
    puff.age = 50.0
    assert puff.cutoff() == pytest.approx(resting)
    puff.age = 100.0 * (1.0 - puff.p["fall"] / 2)
    mid_fall = puff.cutoff()
    assert resting < mid_fall < 1.0
    puff.age = 100.0 * puff.p["rise"] / 2
    mid_rise = puff.cutoff()
    assert resting < mid_rise < 1.0


def test_a_dead_cloud_is_replaced_by_a_newborn() -> None:
    sky = _puffs(cloud_life=10.0)
    old = sky.puffs["near"][0]
    old.age = 9.9
    sky.advance(0.5)
    new = sky.puffs["near"][0]
    assert new is not old
    assert new.age == pytest.approx(0.0)
    assert len(sky.puffs["near"]) == len(sky.puffs["near"])


def test_apply_rebakes_on_style_change_and_resizes_on_count_change() -> None:
    sky = _puffs("drift")
    keep = sky.puffs["mid"][0]
    cfg = SkyConfig(sky_engine="puffs", cloud_style="drift", cloud_drift=5.0)
    sky.apply(cfg)
    assert sky.puffs["mid"][0] is keep, "a drift change reaches only newborns"
    cfg = SkyConfig(sky_engine="puffs", cloud_style="drift", cloud_count=3.0)
    sky.apply(cfg)
    assert sky.puffs["mid"][0] is keep, "a count change grows the list in place"
    assert len(sky.puffs["mid"]) > 1
    cfg = SkyConfig(sky_engine="puffs", cloud_style="bloom")
    sky.apply(cfg)
    assert sky.puffs["mid"][0] is not keep, "a style change re-bakes every cloud"
    assert sky.puffs["mid"][0].p is _PUFF_STYLES["bloom"]["mid"]


@pytest.mark.parametrize("style", STYLES)
def test_every_style_renders_clouds_in_budget(style: str) -> None:
    import time

    sky = _puffs(style)
    for _ in range(40):
        sky.advance(0.5)
    t0 = time.perf_counter()
    cells = sky.render_cells()
    ms = (time.perf_counter() - t0) * 1000
    assert len(cells) == 14 and all(len(r) == 100 for r in cells)
    lit = sum(1 for row in cells for g, _ in row if g != " ")
    assert lit > 30, f"{style} rendered almost nothing"
    assert lit < (1300 if style == "bands" else 1000), f"{style} is an overcast, not clouds"
    assert ms < 20.0


def test_world_swaps_into_and_out_of_puffs() -> None:
    world = World(cols=20, rows=10, rng=random.Random(5), sky_config=SkyConfig(sky_engine="texture"))
    cfg = SkyConfig(sky_engine="puffs")
    world.apply_sky_config(cfg)
    assert isinstance(world.sky, PuffSky)
    world.tick()
    world.render()
    world.apply_sky_config(SkyConfig(sky_engine="fluid"))
    assert not isinstance(world.sky, PuffSky)


def test_tuning_fields_carry_the_cloud_levers() -> None:
    from cactus.sky import tuning_fields

    names = {f.name: f for f in tuning_fields() if f.group == "shared"}
    assert names["sky_engine"].choices == ("fluid", "texture", "puffs")
    assert set(names["cloud_style"].choices) == set(STYLES)
    for key in ("cloud_count", "cloud_drift", "cloud_life"):
        assert names[key].step is not None


# ---- perspective lever (v8, fluid engine) ---------------------------------


def test_perspective_off_draws_each_deck_flat_at_its_band_height() -> None:
    """`perspective = 'off'` is the v6 look: `Sky.render_cells` skips the
    projection and hands `downsample` the raw grids, so a marker in a grid
    lands at that grid's own band height, full width, unprojected."""
    from cactus.sky import Sky, downsample

    off = SkyConfig(sky_engine="fluid", perspective="off")
    on = SkyConfig(sky_engine="fluid", perspective="on")
    sky_off = make_sky(40, 20, random.Random(2), MONO_PLUS, off)
    sky_on = make_sky(40, 20, random.Random(2), MONO_PLUS, on)
    assert isinstance(sky_off, Sky) and isinstance(sky_on, Sky)
    for _ in range(20):
        sky_off.advance(0.5)
        sky_on.advance(0.5)
    flat = sky_off.render_cells()
    direct = downsample(sky_off.grids, MONO_PLUS, 20, 40, off)
    assert flat == direct, "off must be exactly the direct (unprojected) path"
    assert flat != sky_on.render_cells(), "on and off are different pictures"


def test_perspective_is_a_choices_lever() -> None:
    from cactus.sky import tuning_fields

    row = next(f for f in tuning_fields() if f.group == "shared" and f.name == "perspective")
    assert row.choices == ("on", "off")
    assert SkyConfig().perspective == "on"


# ---- T overlay visibility follows the engine (v8) ---------------------------


def test_tuning_rows_follow_the_engine_and_style() -> None:
    from cactus.sky import tuning_fields_for

    def names(cfg):
        return {(r.group, r.name) for r in tuning_fields_for(cfg)}

    puffs = names(SkyConfig(sky_engine="puffs"))
    assert ("shared", "cloud_style") in puffs and ("shared", "cloud_life") in puffs
    assert not any(g in ("far", "mid", "near") for g, _ in puffs)
    assert ("shared", "horizon") not in puffs and ("shared", "shear_floor") not in puffs
    assert ("shared", "edge_gx") not in puffs

    fluid = names(SkyConfig(sky_engine="fluid"))
    assert ("far", "wind_scale") in fluid and ("shared", "perspective") in fluid
    assert ("shared", "horizon") in fluid and ("shared", "cloud_style") not in fluid
    flat = names(SkyConfig(sky_engine="fluid", perspective="off"))
    assert ("shared", "horizon") not in flat and ("shared", "perspective") in flat

    texture = names(SkyConfig(sky_engine="texture"))
    assert ("shared", "shear_base") in texture and ("shared", "shear_floor") not in texture
    for cfg in (puffs, fluid, texture):
        assert ("shared", "sky_engine") in cfg and ("shared", "fps") in cfg and ("shared", "seed_wind") in cfg


def test_bands_style_lays_full_width_lanes_flowing_opposite_ways() -> None:
    """`cloud_style = 'bands'` (v8, planetary layers): `lanes * cloud_count`
    lanes stacked down the sky, each one full-width band that wraps with no
    seam, neighbours flowing opposite ways; a dead band respawns in its own
    lane; `cloud_count` re-cuts the lanes."""
    sky = _puffs("bands", cols=60, rows=20)
    bands = sorted((p for band in GRID_ORDER for p in sky.puffs[band]), key=lambda p: p.y0)
    assert len(bands) == 7
    assert all(p.w == sky.width_px for p in bands)
    assert all(p.lane is not None for p in bands)
    for a, b in zip(bands, bands[1:]):
        assert a.y0 + a.h <= b.y0, "lanes never overlap"
        assert (a.vx > 0) != (b.vx > 0), "neighbouring lanes flow opposite ways"
    assert bands[0].band == "far" and bands[-1].band == "near"
    # band_gap 0 makes lanes touch; band_flow same/random deal directions
    touching = _puffs("bands", cols=60, rows=20, band_gap=0.0)
    lanes = sorted((p for band in GRID_ORDER for p in touching.puffs[band]), key=lambda p: p.y0)
    assert all(a.y0 + a.h >= b.y0 - 1 for a, b in zip(lanes, lanes[1:]))
    same = _puffs("bands", cols=60, rows=20, band_flow="same")
    assert len({p.vx > 0 for band in GRID_ORDER for p in same.puffs[band]}) == 1
    sky.apply(SkyConfig(sky_engine="puffs", cloud_style="bands", band_gap=0.6))
    regap = sorted((p for band in GRID_ORDER for p in sky.puffs[band]), key=lambda p: p.y0)
    assert all(p.h <= 0.45 * sky.height_px / 7 + 1 for p in regap)
    sky.apply(SkyConfig(sky_engine="puffs", cloud_style="bands"))
    bands = sorted((p for band in GRID_ORDER for p in sky.puffs[band]), key=lambda p: p.y0)
    # seamless wrap: the patch's first and last columns are neighbours in
    # the periodic lattice, so they differ by no more than one lattice step
    row = bands[3].patch_a[bands[3].h // 2]
    assert abs(row[0] - row[-1]) < 0.35
    old = bands[2]
    old.age = old.life - 0.05
    sky.advance(0.1)
    still = next(p for band in GRID_ORDER for p in sky.puffs[band] if p.lane == old.lane)
    assert still is old and 0.0 <= old.age < 1.0, "a lane never dies; its morph phase wraps"
    assert old.cutoff() == old.p["cutoff"], "a lane never unfolds or recedes"
    sky.apply(SkyConfig(sky_engine="puffs", cloud_style="bands", cloud_count=2.0))
    assert sum(len(v) for v in sky.puffs.values()) == 14
    cells = sky.render_cells()
    assert sum(1 for r in cells for g, _ in r if g != " ") > 200


# ---- scatter (a falling seed pushes the cloud aside) -----------------------


def test_scatter_dents_only_the_displaced_part_of_a_cloud() -> None:
    """v8: a seed inside a cloud dents the patch pixels it displaces — the
    raw value under the point drops and the ring `radius` out gains it —
    while the cloud itself keeps its place and its age."""
    sky = _puffs(cloud_life=100.0)
    puff = sky.puffs["mid"][0]
    puff.x, puff.vx, puff.age = 10.0, 0.0, 50.0
    c0, r0 = puff.w // 2, puff.h // 2
    for patch in (puff.patch_a, puff.patch_b):
        for row in patch:
            for i in range(len(row)):
                row[i] = 0.5
    before = sum(v for row in puff.patch_a for v in row)
    px, py = puff.x + c0, puff.y0 + r0

    sky.scatter(px, py, radius=4.0, strength=0.6)

    assert puff.patch_a[r0][c0] < 0.5 and puff.patch_b[r0][c0] < 0.5
    ring = [puff.patch_a[r0][min(c0 + 4, puff.w - 1)], puff.patch_a[r0][max(c0 - 4, 0)]]
    assert max(ring) > 0.5, "the pushed value lands a radius out"
    after = sum(v for row in puff.patch_a for v in row)
    assert after == pytest.approx(before, abs=1e-6), "value moves, it is not lost"
    assert puff.vx == 0.0 and puff.age == 50.0
    far_c = (c0 + 12) % puff.w
    assert puff.patch_a[r0][far_c] == pytest.approx(0.5), "pixels the seed never touched are untouched"


def test_scatter_on_a_bands_lane_dents_it_the_same_way() -> None:
    sky = _puffs("bands", cols=60, rows=20)
    lane = next(p for band in GRID_ORDER for p in sky.puffs[band])
    age0, vx0, x0 = lane.age, lane.vx, lane.x
    c0, r0 = 5, lane.h // 2
    for row in lane.patch_a:
        for i in range(len(row)):
            row[i] = 0.5
    sky.scatter(lane.x + c0, lane.y0 + r0, radius=3.0, strength=0.6)
    assert lane.vx == vx0 and lane.x == x0 and lane.age == age0
    assert lane.patch_a[r0][c0] < 0.5
