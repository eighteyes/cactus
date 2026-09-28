"""
test_sky.py — the cellular-automaton sky: grids, tuning config, downsample.

Responsibilities:
- `Air.tick` conserves mass under advection alone, spreads anisotropically
  under diffusion alone (further along x than y), grows a puff inside one of
  its bands and lets one outside fade, and shears rows near the bottom of the
  sky faster than rows near the top.
- `Air.d` (and every row inside it) is the same object across ticks; only
  `resize` ever rebuilds it.
- `downsample` picks blank, a fringe speck, an ordered-dither braille
  pattern, or a solid core by block mean, with a monotonic dot count as
  density rises, and colours a block from its owning grid's own dark/light
  tone ramp plus the shared atmospheric depth shift.
- `Sky.render_cells` uses at least 24 distinct colours across a real sky and
  stays inside the 40 ms frame budget at 100x20.
- `SkyConfig.load`/`overlay`/`dump` round-trip through TOML, overlay only the
  keys a file supplies, and raise `ValueError` naming the offending key.
"""

from __future__ import annotations

import random
import time

import pytest
from rich.cells import cell_len

from cactus.field import MONO_PLUS
from cactus.sky import (
    _SPECK_GLYPHS,
    CORE_GLYPH,
    GRID_BAND_REGION,
    GRID_ORDER,
    Air,
    GridConfig,
    Sky,
    SkyConfig,
    _ordered_dither,
    downsample,
)


def _still_config(**overrides) -> GridConfig:
    """A grid config with every dynamic process off by default, so a test can
    turn exactly one back on."""
    base = dict(
        wind_scale=1.0, kx=0.0, ky=0.0, growth=0.0, evaporation=0.0,
        nucleate_p=0.0, band_count=0, floor=0.0, allee=0.0, uptake=0.0, replenish=0.0,
    )
    base.update(overrides)
    return GridConfig(**base)


def _tiny_grids(cfg: SkyConfig | None = None, width: int = 2, height: int = 4):
    cfg = cfg or SkyConfig()
    return {
        name: Air(width, height, random.Random(i), getattr(cfg, name), GRID_BAND_REGION[name], warm=False)
        for i, name in enumerate(GRID_ORDER)
    }, cfg


# ---- Air: the cellular automaton ---------------------------------------


def test_advection_alone_conserves_mass() -> None:
    cfg = _still_config()
    air = Air(20, 8, random.Random(1), cfg, (0.4, 0.6), warm=False)
    for x in range(3):
        air.d[4][x] = 0.6
    start = sum(sum(row) for row in air.d)
    for _ in range(100):
        air.tick(0.37, shear_floor=0.0, shear_base=1.0, shear_span=0.0)
    end = sum(sum(row) for row in air.d)
    assert end == pytest.approx(start, abs=1e-6)


def test_diffusion_is_anisotropic() -> None:
    cfg = _still_config(kx=0.10, ky=0.006)
    air = Air(30, 20, random.Random(2), cfg, (0.4, 0.6), warm=False)
    cx, cy = 15, 10
    air.d[cy][cx] = 1.0
    for _ in range(50):
        air.tick(0.0, shear_floor=0.0, shear_base=1.0, shear_span=0.0)

    total = sum(sum(row) for row in air.d)
    mx = sum(x * v for row in air.d for x, v in enumerate(row)) / total
    my = sum(y * v for y, row in enumerate(air.d) for v in row) / total
    var_x = sum((x - mx) ** 2 * v for row in air.d for x, v in enumerate(row)) / total
    var_y = sum((y - my) ** 2 * v for y, row in enumerate(air.d) for v in row) / total
    assert var_x > var_y


def test_puff_inside_a_band_grows_and_outside_fades() -> None:
    cfg = _still_config(growth=2.0, evaporation=0.04, band_count=1, band_sigma_lo=2.0, band_sigma_hi=2.0)
    air = Air(10, 40, random.Random(3), cfg, (0.5, 0.5), warm=False)
    centre, _sigma = air.bands[0]
    inside_y = int(round(centre))
    outside_y = 2
    air.d[inside_y][3] = 0.2
    air.d[outside_y][3] = 0.2
    for _ in range(600):
        air.tick(0.0, shear_floor=0.0, shear_base=1.0, shear_span=0.0)
    assert air.d[inside_y][3] > 0.2
    assert air.d[outside_y][3] < 0.01


def test_shear_moves_bottom_rows_faster_than_top() -> None:
    cfg = _still_config()
    h = 20
    air = Air(40, h, random.Random(4), cfg, (0.4, 0.6), warm=False)
    bottom_y, top_y = 1, h - 2
    air.d[bottom_y][5] = 1.0
    air.d[top_y][5] = 1.0
    for _ in range(200):
        air.tick(0.3, shear_floor=0.03, shear_base=0.7, shear_span=0.3)

    def centroid_x(y: int) -> float:
        row = air.d[y]
        total = sum(row)
        return sum(x * v for x, v in enumerate(row)) / total

    assert (centroid_x(bottom_y) - 5) > (centroid_x(top_y) - 5)


def test_air_d_identity_is_stable_across_ticks_only_resize_rebuilds_it() -> None:
    cfg = _still_config(kx=0.1, ky=0.006, growth=0.01, evaporation=0.004, nucleate_p=0.1, band_count=2)
    air = Air(10, 8, random.Random(5), cfg, (0.4, 0.6), warm=False)
    d_id = id(air.d)
    row_ids = [id(r) for r in air.d]
    for _ in range(30):
        air.tick(0.2, shear_floor=0.03, shear_base=0.7, shear_span=0.3)
    assert id(air.d) == d_id
    assert [id(r) for r in air.d] == row_ids
    air.resize(20, 8)
    assert id(air.d) != d_id


# ---- Sky: three grids composited, rendered, and timed ------------------


def test_render_uses_at_least_24_distinct_colours() -> None:
    sky = Sky(cols=100, sky_rows=14, rng=random.Random(1), palette=MONO_PLUS)
    for _ in range(300):
        sky.tick(0.1)
    grid = sky.render_cells()
    colours = {colour for row in grid for glyph, colour in row if glyph != " " and colour is not None}
    assert len(colours) >= 24


def test_frame_time_budget_at_100x20() -> None:
    sky = Sky(cols=100, sky_rows=20, rng=random.Random(1), palette=MONO_PLUS)
    start = time.perf_counter()
    for _ in range(20):
        sky.tick(0.1)
        sky.render_cells()
    elapsed = (time.perf_counter() - start) / 20
    assert elapsed < 0.040, f"{elapsed * 1000:.1f} ms/frame, over the 40 ms budget"


# ---- downsample: kept from v5 ------------------------------------------


def test_downsample_blank_dither_and_core() -> None:
    grids, cfg = _tiny_grids()
    assert downsample(grids, MONO_PLUS, sky_rows=1, cols=1, cfg=cfg)[0][0] == (" ", None)

    grids, cfg = _tiny_grids()
    for row in grids["near"].d:
        row[:] = [0.1, 0.1]
    glyph, _ = downsample(grids, MONO_PLUS, sky_rows=1, cols=1, cfg=cfg)[0][0]
    assert glyph not in (" ", CORE_GLYPH)

    grids, cfg = _tiny_grids()
    for row in grids["near"].d:
        row[:] = [1.0, 1.0]
    glyph, _ = downsample(grids, MONO_PLUS, sky_rows=1, cols=1, cfg=cfg)[0][0]
    assert glyph == CORE_GLYPH


def test_downsample_mid_density_cell_is_neither_blank_nor_full() -> None:
    grids, cfg = _tiny_grids()
    for row in grids["near"].d:
        row[:] = [0.5, 0.5]
    glyph, _ = downsample(grids, MONO_PLUS, sky_rows=1, cols=1, cfg=cfg)[0][0]
    assert glyph not in (" ", CORE_GLYPH)


def test_downsample_fringe_cell_renders_a_speck() -> None:
    grids, cfg = _tiny_grids()
    # (0, 0)'s cell hash is checked to land in the speck bucket below.
    grids["near"].d[0][0] = 0.03
    glyph, _ = downsample(grids, MONO_PLUS, sky_rows=1, cols=1, cfg=cfg)[0][0]
    assert glyph in _SPECK_GLYPHS


def test_downsample_colour_follows_the_owning_grids_tone_pair() -> None:
    grids, cfg = _tiny_grids()
    for row in grids["far"].d:
        row[:] = [1.0, 1.0]
    _, colour = downsample(grids, MONO_PLUS, sky_rows=1, cols=1, cfg=cfg)[0][0]
    # m = 1.0: tone is 1.0, so the base is the far grid's light end, pushed
    # toward haze only by the far grid's own fixed depth (row 0 of 1 adds no
    # further row-height shift).
    from cactus.sky import GRID_DEPTH, _lerp_hex, atmospheric_colour
    expected = atmospheric_colour(
        MONO_PLUS.cloud_far_light, GRID_DEPTH["far"], 0, 1, MONO_PLUS,
        cfg.haze_depth_weight, cfg.haze_row_weight, cfg.haze_clamp,
    )
    assert colour == expected


def test_ordered_dither_dot_count_is_monotonic_with_uniform_density() -> None:
    prior = -1
    counts_seen = set()
    steps = [i * 0.05 for i in range(21)]
    for d in steps:
        pixels = [[d, d], [d, d], [d, d], [d, d]]
        glyph = _ordered_dither(pixels)
        count = bin(ord(glyph) - 0x2800).count("1")
        assert count >= prior
        prior = count
        counts_seen.add(count)
    assert len(counts_seen) >= 6


def test_braille_bit_order() -> None:
    top_left = [[1.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    assert _ordered_dither(top_left) == "⠁"
    bottom_right = [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 1.0]]
    assert _ordered_dither(bottom_right) == "⢀"


def test_alphabet_glyphs_are_all_single_cell_width() -> None:
    """Every glyph the sky can draw must be one terminal cell wide in a
    monospace font — a double-width character would desync the field's
    column grid from the canvas it was downsampled from."""
    alphabet = list(" .·˙:∘•-~") + [CORE_GLYPH]
    alphabet += [chr(0x2800 | bits) for bits in range(256)]
    for glyph in alphabet:
        assert cell_len(glyph) == 1, repr(glyph)


# ---- SkyConfig: load / overlay / dump -----------------------------------


def test_overlay_changes_one_key_and_keeps_the_rest() -> None:
    cfg = SkyConfig().overlay({"far": {"growth": 0.5}, "shared": {"tone_exp": 0.8}})
    assert cfg.far.growth == 0.5
    assert cfg.far.kx == SkyConfig().far.kx
    assert cfg.mid.growth == SkyConfig().mid.growth
    assert cfg.tone_exp == 0.8
    assert cfg.blank_mean == SkyConfig().blank_mean


def test_overlay_bad_value_raises_naming_the_key() -> None:
    with pytest.raises(ValueError, match=r"far\.kx"):
        SkyConfig().overlay({"far": {"kx": "not a number"}})


def test_overlay_unknown_key_raises_naming_the_key() -> None:
    with pytest.raises(ValueError, match=r"shared\.bogus"):
        SkyConfig().overlay({"shared": {"bogus": 1}})


def test_dump_then_load_round_trips(tmp_path) -> None:
    path = tmp_path / "sky.toml"
    written = SkyConfig().overlay({"near": {"nucleate_p": 0.9}})
    written.dump(path)
    loaded = SkyConfig.load(path)
    assert loaded == written


def test_load_missing_file_is_defaults(tmp_path) -> None:
    assert SkyConfig.load(tmp_path / "does-not-exist.toml") == SkyConfig()
