"""
sky.py — cellular-automaton sky: three persistent air grids downsampled to
toned glyphs.

Responsibilities:
- `Air`: one depth's persistent density grid at braille-pixel resolution,
  evolved in place by `advance(dt, ...)` — advect along x with a
  height-sheared wind, diffuse anisotropically (far more along x than y, so
  mass stays 1-3 rows tall), react with a banded logistic growth against a
  flat evaporation, and nucleate the occasional puff, all at rates per second
  scaled by `dt`. Nothing is regenerated: `advance()` mutates `Air.d`,
  `resize()` is the only method that reassigns it wholesale. `tick()` is a
  thin wrapper for tests, `advance(_DEFAULT_DT, ...)`.
- `Sky`: owns three `Air` grids (far/mid/near), each its own share of the
  world's wind, its own band placement, and composites them front-to-back
  into one canvas the same way v5's layers did — the nearest grid whose
  density clears `DENSITY_FLOOR` owns a pixel. `advance(dt, wind)` steps
  every grid by `dt`; `tick(wind)` is a thin wrapper, `advance(_DEFAULT_DT,
  wind)`.
- Perspective (v7): the three grids stay three decks (own wind_scale,
  color pair, and `GRID_BAND_REGION`), but a grid's own row axis is now read
  as world distance `z`, not screen row. `_screen_projection_row` turns a
  screen pixel row into `(is_sky, z, xscale)` against the shared `horizon`/
  `focal`/`z_far`/`deck_altitude_px` levers; `Sky._build_projection` caches
  one row of that per pixel row of sky height, rebuilt on `resize`/`apply`.
  `_project_composite` bilinear-samples every grid at each pixel's projected
  `(x, z)` and composites nearest-first, same ownership rule as `_composite`
  — `Sky.render_cells` feeds its output into `downsample` instead of the old
  1:1 pixel copy, so far rows compress and crawl and near rows stretch and
  move fast, and haze follows `z` instead of screen row. `Sky.camera_x`
  drifts with the wind so the whole projected scene pans, never a fixed
  frame. `downsample`'s old direct-array path (`density`/`owner` omitted)
  is unchanged — every pre-v7 test still drives it pixel-for-pixel.
- `GridConfig`/`SkyConfig`: every tunable constant, per grid and shared,
  as a dataclass rather than a module constant, so it can be loaded from a
  TOML file (`SkyConfig.load`), written back out with a one-line comment per
  key (`SkyConfig.dump`), and swapped live into a running `Sky`
  (`Sky.apply`) without disturbing the grids' drawn bands. Every numeric
  field also carries `step`/`lo`/`hi` in its dataclass metadata; the one
  string-valued lever, `pile_style` (v6d, "blocks" or "dots" — how field.py
  renders a landed cactus cell), carries a `choices` tuple instead.
  `tuning_fields()` flattens both shapes, the whole set (far/mid/near/shared),
  into `TuneField` rows for tui.py's `T` overlay. Nine save/recall slots
  (v6g) live beside `config_path()` as `sky-slot-N.toml`: `save_slot`/
  `load_slot` round-trip through the same sparse `dump`/`load`, each slot
  optionally carrying a human `name` (a top-level TOML key, written first,
  ignored by `overlay()`); `slots_present()` reports which are filled,
  `slot_name`/`slots()` report their names, for the overlay to show.
- Downsample the composited canvas, `PX_X` by `PX_Y` pixels per terminal
  cell, to one toned glyph: blank, a fringe speck, an ordered-dither braille
  pattern, a flat cirrus stroke, a tapering edge stroke, or a solid core —
  coloured by a 16-step tone ramp between the owning grid's own dark/light
  pair, then shifted toward `palette.haze` by that grid's fixed depth and
  the cell's own height (`atmospheric_colour`, shared with a bird's colour
  at its own row).
- Stay pure Python (no numpy) and free of Textual or store imports; `field.py`
  is the only caller, and it duck-types `palette` (no import of its type
  here, to avoid a cycle).
- Perf (v6f, q384 "horrible, sucks up a ton of cpu"): each `Air` tracks which
  rows are `active` (carry density, or sit beside a row that does) and skips
  advect/diffuse/react/clamp on the rest; `_project_composite` skips a grid's
  bilinear tap the same way, and flags a pixel row `row_empty` when every
  grid skipped it so `downsample` can fast-path a whole blank terminal row.
  `SkyConfig.fps` (shared group) is how often the TUI samples the field at
  all — `Air.advance`/`Sky.advance` still take the true elapsed `dt`, so
  raising or lowering it only changes the sampling rate, not the physics.
  `SkyConfig.perspective` (v8, "on"/"off") keeps the v6 flat look reachable:
  "off" makes `Sky.render_cells` skip the projection and feed `downsample`
  the raw grids, each deck's bands drawn flat at their own band height.
  `SkyConfig.sky_engine` ("texture" default, "fluid", "puffs") picks the
  engine from `SKY_ENGINES` — this module's cellular automaton, `TextureSky`
  (v5's baked-noise sky restored behind the same four-method interface), or
  `PuffSky` (`make_sky` is the one place that chooses; each class carries an
  `ENGINE` tag `field.py` reads back). `field.py`'s `run_bench()` (`cactus
  sky --bench`) times the default engine.
- Puffs (v8): `PuffSky` is a population of individual clouds, no whole-sky
  scroll. Each `_Puff` has its own drift (`cloud_drift`, band-scaled, its
  own sign), its own life (`cloud_life`), and two baked noise patches it
  morphs between; its cutoff starts at 1.0 and sinks to the style's resting
  value, so the cloud unfolds from its densest cores outward, holds, then
  recedes the same way and is replaced. `cloud_style` picks a `_PUFF_STYLES`
  table (`drift`, `bloom`, `streaks`), `cloud_count` scales the population.
  `camera_x` stays 0: the sky changes more than it travels.
"""

from __future__ import annotations

import math
import os
import random
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

PX_X = 2  # pixels per terminal cell, horizontal (braille dot geometry)
PX_Y = 4  # pixels per terminal cell, vertical

# The TUI's default sampling interval — not a "tick" the physics runs in,
# only the anchor `tick()`'s thin wrapper advances by and the value every
# rate-typed `GridConfig`/`SkyConfig` default below was converted against, so
# the sky looks exactly as it did pre-v6b at this sampling rate.
_DEFAULT_DT = 0.1

# Compositing ownership floor and the fringe-speck peak threshold are the
# same number by design: a pixel too faint to ever own a composited cell is
# exactly a pixel too faint to earn even a speck.
DENSITY_FLOOR = 0.02

CORE_GLYPH = "⣿"  # "⣿" — all eight braille dots, same bits an all-lit dither gives
_SPECK_GLYPHS = ". · ˙ , ' `".split()  # fringe specks, one per cell by hash
# Grain (v8): a flat plateau of density would otherwise render one identical
# dither glyph across a whole run of cells, which reads as a coarse slab.
# On a cloud's *outside* — a cell whose block mean sits under
# `_GRAIN_EDGE_MEAN` — one dither cell in three (by hash) takes a small
# embellishment (`, . ' \``) instead, so a rim breaks into texture. Inside
# the cloud only braille draws: the dither's dot count is the depth cue and
# a marker there reads as a glyph, not as cloud.
_GRAIN_EDGE_MEAN = 0.35
_GRAIN_GLYPHS = (",", ".", "'", "`")


def _grain_glyph(m: float, x0: int, y0: int) -> str | None:
    if m >= _GRAIN_EDGE_MEAN:
        return None
    return _GRAIN_GLYPHS[_cell_hash(x0, y0 + 7) % len(_GRAIN_GLYPHS)]

# Compositing order, nearest first — the first grid whose pixel clears
# DENSITY_FLOOR owns it, exactly as v5's near/mid/far layers did.
GRID_ORDER = ("near", "mid", "far")
# Fixed per-grid identity: not tunable (unlike GridConfig below). `depth` is
# the haze weight `atmospheric_colour` shifts by, matching field.py's
# DEPTH_BAND for birds one-for-one. `band_region` is the fraction of sky
# height (0 at the bottom) each grid's bands are drawn within — far sits in
# the top half, mid the middle, near the lower half.
GRID_DEPTH = {"far": 0.9, "mid": 0.6, "near": 0.2}
GRID_BAND_REGION = {"far": (0.67, 0.97), "mid": (0.36, 0.64), "near": (0.03, 0.33)}

# Where a user's sky tuning file lives, overridable for tests and tooling.
CONFIG_ENV = "CACTUS_SKY"


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    return Path(override) if override else Path.home() / ".config" / "cactus" / "sky.toml"


# Save/recall slots (v6g): nine spare config files beside sky.toml, for a
# tuning session to stash and swap between without overwriting the file the
# TUI keeps live-dumping to.
SLOT_COUNT = 9


def slot_path(n: int) -> Path:
    if not 1 <= n <= SLOT_COUNT:
        raise ValueError(f"slot {n} out of range 1..{SLOT_COUNT}")
    return config_path().with_name(f"sky-slot-{n}.toml")


def slots_present() -> dict[int, bool]:
    """`{n: slot_path(n).exists()}` for every slot, 1..`SLOT_COUNT`."""
    return {n: slot_path(n).exists() for n in range(1, SLOT_COUNT + 1)}


def slot_name(n: int) -> str | None:
    """The `name` key stored in slot `n`'s file, or `None` if the slot is
    empty, has no name, or fails to parse."""
    p = slot_path(n)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError:
        return None
    name = data.get("name")
    return name if isinstance(name, str) else None


def slots() -> dict[int, str | None]:
    """`{n: name}` for every slot, 1..`SLOT_COUNT`: the slot's `name` (`""`
    when the file exists but carries none), or `None` when the slot is
    empty."""
    result: dict[int, str | None] = {}
    for n in range(1, SLOT_COUNT + 1):
        p = slot_path(n)
        if not p.exists():
            result[n] = None
            continue
        result[n] = slot_name(n) or ""
    return result


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _lerp_hex(a: str, b: str, t: float) -> str:
    """Mix two `#rrggbb` strings per channel; `t=0` is `a`, `t=1` is `b`."""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    c = round(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{c:02x}"


def _ramp16(a: str, b: str, t: float) -> str:
    """`a` to `b` in 16 quantised steps, so runs of equal tone merge."""
    step = round(_clamp(t, 0.0, 1.0) * 15) / 15
    return _lerp_hex(a, b, step)


def atmospheric_colour(
    band_colour: str, depth: float, row: int, sky_rows: int, palette,
    depth_weight: float = 0.55, row_weight: float = 0.30, clamp_at: float = 0.85,
) -> str:
    """Shift `band_colour` toward `palette.haze` by `depth` and by height.

    `row` is 0 at the bottom of the sky and `sky_rows - 1` at the top, so a
    colour fades further toward the haze the higher and the further back it
    sits. Shared by the downsampler's cloud cells (`depth` is the owning
    grid's fixed `GRID_DEPTH`) and, at a bird's own depth and row, by
    `field.py`'s `_bird_colour`. `depth_weight`/`row_weight`/`clamp_at` are
    `SkyConfig`'s shared haze weights; a caller with no config (birds) gets
    the tuned defaults.
    """
    denom = sky_rows - 1 if sky_rows > 1 else 1
    t = depth_weight * depth + row_weight * (row / denom)
    return _lerp_hex(band_colour, palette.haze, _clamp(t, 0.0, clamp_at))


def _rotate(row: list[float], k: int) -> list[float]:
    """`result[x] == row[(x - k) % len(row)]` — a wrapping shift by `k`."""
    w = len(row)
    k %= w
    if k == 0:
        return row[:]
    return row[-k:] + row[:-k]


# ---- tuning: every constant a builder or a user can retune -----------------


@dataclass
class GridConfig:
    """One grid's physics and weather knobs. `wind_scale` is this grid's
    share of the world's wind (parallax); the rest shape its cellular
    automaton (v6 plan's "five constants" plus the puff and band knobs).

    `kx`, `ky`, `growth`, `evaporation`, and `replenish` are all per second
    now — `Air.advance(dt, ...)` scales each by `dt`, and `nucleate_p` (a
    probability) the same way. Their defaults are v6's per-tick-at-
    `_DEFAULT_DT` values divided by `_DEFAULT_DT`, so the sky looks the same
    at the TUI's default sampling. `uptake` stays dimensionless — it scales
    an already-per-second growth amount, not a rate of its own — so its
    default is unchanged.

    Every numeric field carries `step`/`lo`/`hi` in its `metadata` (v6c): the
    `T` tuning overlay's h/l nudge and clamp, chosen from the field's own
    default — step about 1/20 of it, lo 0, hi about 10x it, ints stepping by
    a flat 1. `wind_scale` has no single default at this class (it varies
    per grid, set by `SkyConfig`'s factories below), so its range is chosen
    against `near`'s 1.0, the largest of the three."""

    wind_scale: float = field(metadata={"step": 0.05, "lo": 0.0, "hi": 10.0})
    kx: float = field(default=0.05 / _DEFAULT_DT, metadata={"step": 0.025, "lo": 0.0, "hi": 5.0})
    ky: float = field(default=0.003 / _DEFAULT_DT, metadata={"step": 0.0015, "lo": 0.0, "hi": 0.3})
    growth: float = field(default=3.0 / _DEFAULT_DT, metadata={"step": 1.5, "lo": 0.0, "hi": 300.0})
    evaporation: float = field(default=0.015 / _DEFAULT_DT, metadata={"step": 0.0075, "lo": 0.0, "hi": 1.5})
    nucleate_p: float = field(default=0.05 / _DEFAULT_DT, metadata={"step": 0.025, "lo": 0.0, "hi": 5.0})
    puff_lo: float = field(default=0.5, metadata={"step": 0.025, "lo": 0.0, "hi": 5.0})
    puff_hi: float = field(default=0.8, metadata={"step": 0.04, "lo": 0.0, "hi": 8.0})
    puff_width: int = field(default=30, metadata={"step": 1, "lo": 0, "hi": 300})
    puff_height: int = field(default=2, metadata={"step": 1, "lo": 0, "hi": 20})
    band_sigma_lo: float = field(default=1.5, metadata={"step": 0.075, "lo": 0.0, "hi": 15.0})
    band_sigma_hi: float = field(default=2.5, metadata={"step": 0.125, "lo": 0.0, "hi": 25.0})
    band_count: int = field(default=2, metadata={"step": 1, "lo": 0, "hi": 20})
    uptake: float = field(default=2.5, metadata={"step": 0.125, "lo": 0.0, "hi": 25.0})
    replenish: float = field(default=0.002 / _DEFAULT_DT, metadata={"step": 0.001, "lo": 0.0, "hi": 0.2})
    floor: float = field(default=0.03, metadata={"step": 0.0015, "lo": 0.0, "hi": 0.3})
    allee: float = field(default=0.15, metadata={"step": 0.0075, "lo": 0.0, "hi": 1.5})


GRID_FIELD_NAMES = tuple(f.name for f in fields(GridConfig))

_GRID_COMMENTS = {
    "wind_scale": "fraction of the world's wind this grid drifts at",
    "kx": "horizontal diffusion per second — spreads mass along a streak",
    "ky": "vertical diffusion per second — spreads mass across a streak (keep small)",
    "growth": "logistic growth rate per second inside a band",
    "evaporation": "decay rate per second everywhere, strongest outside a band",
    "nucleate_p": "probability per second of a new puff",
    "puff_lo": "a puff's minimum added density",
    "puff_hi": "a puff's maximum added density",
    "puff_width": "a puff's width in pixels",
    "puff_height": "a puff's height in pixels",
    "uptake": "moisture a unit of growth spends; higher means shorter-lived streaks",
    "replenish": "moisture return rate per second toward 1",
    "floor": "density below this snaps to zero, so evaporation leaves no haze",
    "allee": "density a streak must reach to grow; below it, it thins away",
    "band_sigma_lo": "a band's minimum vertical spread in pixels",
    "band_sigma_hi": "a band's maximum vertical spread in pixels",
    "band_count": "how many bands this grid draws at startup",
}

_SHARED_COMMENTS = {
    "pile_style": "landed-cactus rendering: 'blocks' (quadrant blocks) or 'dots' (splatted, dithered)",
    "stick_distance": "how close two falling seeds' members must be, in sub-cells, to merge into one clump",
    "shear_floor": "minimum drift speed per row, pixels/second, so drift never stalls",
    "shear_base": "row shear's base fraction of a grid's own wind, per second",
    "shear_span": "row shear's extra fraction at the bottom of the sky, per second",
    "tone_exp": "block-mean lift before the 16-step tone ramp",
    "haze_depth_weight": "how much a grid's fixed depth mixes toward haze",
    "haze_row_weight": "how much a cell's height mixes toward haze",
    "haze_clamp": "ceiling on the haze mix, however deep or high",
    "blank_mean": "block mean below this renders blank",
    "core_mean": "block mean at or above this renders a solid core",
    "semi_core_mean": "block mean at or above this alternates core/dither",
    "flat_gx": "minimum x gradient for a flat cirrus stroke",
    "flat_gy_max": "maximum y gradient allowed for a flat cirrus stroke",
    "flat_mean_lo": "flat stroke's minimum block mean",
    "flat_mean_hi": "flat stroke's maximum block mean",
    "edge_mean_hi": "tapering edge strokes are only tried below this mean",
    "edge_gx": "minimum x gradient for a tapering edge stroke",
    "edge_gy": "minimum y gradient for a tapering edge stroke",
    "horizon": "the horizon line, as a fraction of sky height down from the top",
    "focal": "perspective focal length in pixels — z(r) = focal / (r - horizon_px)",
    "z_far": "world distance a grid's far edge (and the haze mix) clamps to",
    "ground_lines": "how many faint perspective lines cross the ground band (0 disables)",
    "deck_altitude_px": "the deck's world y — how far above the horizon its top peeks through",
    "fps": "how often the TUI samples and redraws the field, per second",
    "sky_engine": "which sky renderer runs: 'fluid' (cellular automaton), 'texture' (cheaper baked noise), or 'puffs' (individual clouds, no whole-sky scroll)",
    "cloud_style": "puffs engine look: 'drift' (each cloud wanders its own way), 'bloom' (near-still clouds unfold and recede), 'streaks' (long thin bands)",
    "cloud_count": "puffs engine population scale: 1.0 is one cloud per band per ~40 columns",
    "cloud_drift": "puffs engine top drift speed, pixels per second, before a band's own wind_scale; each cloud picks its own direction",
    "cloud_life": "puffs engine seconds a cloud lives, unfold to recede",
    "perspective": "fluid engine: 'on' projects the three decks through horizon/focal/z_far (v7); 'off' draws each deck's bands flat across the sky, the v6 look",
    "seed_wind": "a falling seed's wind as a multiple of the near deck's (world wind x near.wind_scale x this)",
}


@dataclass
class SkyConfig:
    """Every sky constant, per grid and shared. `load`/`dump` round-trip
    this through a TOML file; `Sky.apply` swaps one in live.

    `shear_floor`/`shear_base`/`shear_span` are per second, same conversion
    as `GridConfig`'s rate fields: v6's per-tick-at-`_DEFAULT_DT` value
    divided by `_DEFAULT_DT`. The TOML keys keep their v6 names throughout —
    only the numbers they hold changed meaning, from "per tick" to "per
    second". Every field below also carries `step`/`lo`/`hi` metadata, same
    convention as `GridConfig` (v6c)."""

    far: GridConfig = field(default_factory=lambda: GridConfig(wind_scale=0.25))
    mid: GridConfig = field(default_factory=lambda: GridConfig(wind_scale=0.55))
    near: GridConfig = field(default_factory=lambda: GridConfig(wind_scale=1.0))

    # A style lever, not a numeric knob (v6d): no step/lo/hi, just the two
    # values a T-overlay `h`/`l` press cycles between (see TuneField.choices).
    pile_style: str = field(default="blocks", metadata={"choices": ("blocks", "dots")})

    # A falling-seed merge lever (v6e), in the same sub-cell units as a
    # `Seed`/`Clump`'s own `x`/`y` — not a pixel-space knob like the splat
    # radii above it.
    stick_distance: float = field(default=1.4, metadata={"step": 0.1, "lo": 0.0, "hi": 6.0})

    shear_floor: float = field(default=0.03 / _DEFAULT_DT, metadata={"step": 0.015, "lo": 0.0, "hi": 3.0})
    shear_base: float = field(default=0.7 / _DEFAULT_DT, metadata={"step": 0.35, "lo": 0.0, "hi": 70.0})
    shear_span: float = field(default=0.3 / _DEFAULT_DT, metadata={"step": 0.15, "lo": 0.0, "hi": 30.0})
    tone_exp: float = field(default=0.45, metadata={"step": 0.0225, "lo": 0.0, "hi": 4.5})
    haze_depth_weight: float = field(default=0.55, metadata={"step": 0.0275, "lo": 0.0, "hi": 5.5})
    haze_row_weight: float = field(default=0.30, metadata={"step": 0.015, "lo": 0.0, "hi": 3.0})
    haze_clamp: float = field(default=0.85, metadata={"step": 0.0425, "lo": 0.0, "hi": 8.5})
    blank_mean: float = field(default=0.10, metadata={"step": 0.005, "lo": 0.0, "hi": 1.0})
    core_mean: float = field(default=0.92, metadata={"step": 0.046, "lo": 0.0, "hi": 9.2})
    semi_core_mean: float = field(default=0.80, metadata={"step": 0.04, "lo": 0.0, "hi": 8.0})
    flat_gx: float = field(default=0.15, metadata={"step": 0.0075, "lo": 0.0, "hi": 1.5})
    flat_gy_max: float = field(default=0.10, metadata={"step": 0.005, "lo": 0.0, "hi": 1.0})
    flat_mean_lo: float = field(default=0.25, metadata={"step": 0.0125, "lo": 0.0, "hi": 2.5})
    flat_mean_hi: float = field(default=0.70, metadata={"step": 0.035, "lo": 0.0, "hi": 7.0})
    edge_mean_hi: float = field(default=0.65, metadata={"step": 0.0325, "lo": 0.0, "hi": 6.5})
    edge_gx: float = field(default=0.15, metadata={"step": 0.0075, "lo": 0.0, "hi": 1.5})
    edge_gy: float = field(default=0.10, metadata={"step": 0.005, "lo": 0.0, "hi": 1.0})

    # Perspective (v7): the cloud deck's single shared projection. `horizon`
    # is a fraction of sky height from the top; `focal` and `z_far` are in
    # the same pixel units as a grid's own width/height; `ground_lines` is a
    # count, `deck_altitude_px` a pixel offset — see `_screen_projection_row`.
    perspective: str = field(default="on", metadata={"choices": ("on", "off")})
    horizon: float = field(default=0.36, metadata={"step": 0.02, "lo": 0.05, "hi": 0.9})
    focal: float = field(default=24.0, metadata={"step": 2.0, "lo": 4.0, "hi": 200.0})
    z_far: float = field(default=32.0, metadata={"step": 4.0, "lo": 8.0, "hi": 400.0})
    ground_lines: int = field(default=7, metadata={"step": 1, "lo": 0, "hi": 9})
    deck_altitude_px: float = field(default=0.0, metadata={"step": 2.0, "lo": 0.0, "hi": 64.0})

    # Perf (v6f): how often the TUI samples the field, independent of the
    # physics' own `dt` integration — `advance(dt)` still takes the true
    # elapsed wall time, so raising or lowering `fps` only changes how often
    # a frame is drawn, never how fast the sky or a falling seed moves.
    fps: int = field(default=5, metadata={"step": 1, "lo": 1, "hi": 20})
    # Which sky renderer runs: "fluid" is the cellular-automaton `Sky` above,
    # "texture" is the cheaper v5 baked-noise `TextureSky` (same interface),
    # restored as a lever rather than a replacement (v6f, q384).
    sky_engine: str = field(default="texture", metadata={"choices": ("fluid", "texture", "puffs")})
    # Puffs engine levers (v8): a population of individual clouds, each with
    # its own drift and life, no whole-sky scroll — see `PuffSky`.
    cloud_style: str = field(default="drift", metadata={"choices": ("drift", "bloom", "streaks")})
    cloud_count: float = field(default=1.0, metadata={"step": 0.1, "lo": 0.2, "hi": 4.0})
    cloud_drift: float = field(default=1.5, metadata={"step": 0.25, "lo": 0.0, "hi": 12.0})
    cloud_life: float = field(default=90.0, metadata={"step": 10.0, "lo": 10.0, "hi": 900.0})
    # A falling seed's share of the wind (v8): the near deck's wind times
    # this, so a sky tuned to creep does not leave the seeds swaying in a
    # gale — `World.seed_wind()` is the one reader.
    seed_wind: float = field(default=1.0, metadata={"step": 0.1, "lo": 0.0, "hi": 5.0})

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SkyConfig":
        """Defaults overlaid with whatever `path` (or `config_path()`)
        holds; a missing file is silently the defaults."""
        p = Path(path) if path is not None else config_path()
        cfg = cls()
        if not p.exists():
            return cfg
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
        return cfg.overlay(data)

    def overlay(self, data: dict) -> "SkyConfig":
        grids = {name: replace(getattr(self, name)) for name in ("far", "mid", "near")}
        for gname, gcfg in grids.items():
            table = data.get(gname, {})
            if not isinstance(table, dict):
                raise ValueError(f"bad value for {gname}: expected a table")
            for key, value in table.items():
                if key not in GRID_FIELD_NAMES:
                    raise ValueError(f"bad value for {gname}.{key}: unknown key")
                _set_typed(gcfg, key, value, f"{gname}.{key}")
        shared = replace(self, far=grids["far"], mid=grids["mid"], near=grids["near"])
        table = data.get("shared", {})
        if not isinstance(table, dict):
            raise ValueError("bad value for shared: expected a table")
        for key, value in table.items():
            if key not in _SHARED_COMMENTS:
                raise ValueError(f"bad value for shared.{key}: unknown key")
            _set_typed(shared, key, value, f"shared.{key}")
        return shared

    def dump(self, path: str | Path | None = None, *, name: str | None = None) -> Path:
        """Write only the keys that differ from `SkyConfig()`'s defaults to
        `path` (or `config_path()`), as live lines; every other key still
        appears, commented out, so the file documents every lever without
        pinning it. Sparse on purpose: a file dumped under one set of
        defaults must not freeze them past a later default change. When
        `name` is given, a top-level `name = "<escaped>"` line is written
        first, before `[far]` — `overlay()` ignores unknown top-level keys,
        so it never affects loading. Returns the path written."""
        p = Path(path) if path is not None else config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        default = SkyConfig()
        lines: list[str] = [
            "# every rate below is per second (v6b); a v6 file's numbers still load,",
            "# but now mean 10x less per frame at the default 0.1s sampling",
            "# a commented line shows the current default; uncomment and edit to pin it",
            "",
        ]
        if name is not None:
            escaped = name.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'name = "{escaped}"')
            lines.append("")
        for gname in ("far", "mid", "near"):
            lines.append(f"[{gname}]")
            gcfg = getattr(self, gname)
            default_gcfg = getattr(default, gname)
            for f in fields(gcfg):
                v = getattr(gcfg, f.name)
                dv = getattr(default_gcfg, f.name)
                if v == dv:
                    lines.append(f"# {f.name} = {dv!r}  # {_GRID_COMMENTS[f.name]}")
                else:
                    lines.append(f"{f.name} = {v!r}  # {_GRID_COMMENTS[f.name]}")
            lines.append("")
        lines.append("[shared]")
        for key in _SHARED_COMMENTS:
            v = getattr(self, key)
            dv = getattr(default, key)
            if v == dv:
                lines.append(f"# {key} = {dv!r}  # {_SHARED_COMMENTS[key]}")
            else:
                lines.append(f"{key} = {v!r}  # {_SHARED_COMMENTS[key]}")
        p.write_text("\n".join(lines) + "\n")
        return p

    def save_slot(self, n: int, name: str | None = None) -> Path:
        """Dump this config to slot `n`, same sparse format as `dump`, with
        `name` written as the top-level `name` key when given."""
        return self.dump(slot_path(n), name=name)

    @classmethod
    def load_slot(cls, n: int) -> "SkyConfig | None":
        """Load slot `n`, or `None` when that slot has never been saved."""
        p = slot_path(n)
        if not p.exists():
            return None
        return cls.load(p)


@dataclass(frozen=True)
class TuneField:
    """One row of `tuning_fields()`: a key's group, name, comment, and its
    nudge `step`/`lo`/`hi` (all `None` for a key with no numeric metadata).

    `choices` (v6d) is the alternative to `step`/`lo`/`hi` for a string-valued
    lever like `pile_style`: the fixed tuple of values a `h`/`l` press cycles
    through, `None` for every numeric field."""

    group: str
    name: str
    comment: str
    step: float | int | None
    lo: float | int | None
    hi: float | int | None
    choices: tuple[str, ...] | None = None


def tuning_fields() -> list[TuneField]:
    """Every tunable key, far/mid/near then shared, declaration order — the
    `T` overlay in tui.py lists against this, never against the private
    comment dicts directly."""
    rows: list[TuneField] = []
    for gname in ("far", "mid", "near"):
        for f in fields(GridConfig):
            rows.append(TuneField(
                gname, f.name, _GRID_COMMENTS[f.name],
                f.metadata.get("step"), f.metadata.get("lo"), f.metadata.get("hi"),
                choices=f.metadata.get("choices"),
            ))
    shared_fields = {f.name: f for f in fields(SkyConfig)}
    for name, comment in _SHARED_COMMENTS.items():
        f = shared_fields[name]
        rows.append(TuneField(
            "shared", name, comment, f.metadata.get("step"), f.metadata.get("lo"), f.metadata.get("hi"),
            choices=f.metadata.get("choices"),
        ))
    return rows


def _set_typed(obj, key: str, value, label: str) -> None:
    typ = type(getattr(obj, key))
    try:
        typed = typ(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad value for {label}: {value!r}") from exc
    choices = next((f.metadata.get("choices") for f in fields(obj) if f.name == key), None)
    if choices is not None and typed not in choices:
        raise ValueError(f"bad value for {label}: {value!r}, expected one of {choices!r}")
    setattr(obj, key, typed)


# ---- the grid ---------------------------------------------------------


class Air:
    """One depth's persistent density grid, `y = 0` at the bottom, wrapping
    in x. `advance()` mutates `d` in place — neither it nor any row inside it
    is ever rebound except by `resize`."""

    def __init__(
        self, width_px: int, height_px: int, rng: random.Random,
        config: GridConfig, band_region: tuple[float, float], *, warm: bool = True,
    ) -> None:
        self.width = max(width_px, 1)
        self.height = max(height_px, 1)
        self.rng = rng
        self.config = config
        self.band_region = band_region
        self.d: list[list[float]] = [[0.0] * self.width for _ in range(self.height)]
        # Moisture: growth spends it, and it returns slowly, so a streak has
        # a finite life and the sky never saturates a whole row.
        self.m: list[list[float]] = [[1.0] * self.width for _ in range(self.height)]
        self.bands = self._draw_bands()
        self.env = self._build_env()
        # Perf (v6f): `_nonzero[y]` is true when row `y` itself carries any
        # density; `active` (its dilation by one row either side, since a
        # neighbour can still diffuse into an otherwise-empty row) is what
        # advect/diffuse/react/clamp — and `_project_composite`'s bilinear
        # taps — actually gate on. Both are tracked incrementally: `advance()`
        # only ever re-derives a row's `_nonzero` from the rows it just
        # touched, never rescanning the whole grid. `active` is a property
        # rather than a plain attribute so any *external* reader (a test that
        # pokes `d`/`m` directly and never ticks, or `_project_composite`
        # reading a grid it did not just advance) still gets a correct answer
        # — `_active_dirty` forces exactly one full rescan on the first read
        # after construction (or `resize`), never repeated after.
        self._nonzero = [False] * self.height
        self._m_settled = [True] * self.height  # `m` starts at 1.0 everywhere
        self._active_cache: list[bool] = [False] * self.height
        self._active_dirty = True
        if warm:
            for _ in range(40):
                self._nucleate(_DEFAULT_DT, force=True)
            for _ in range(300):
                self.advance(_DEFAULT_DT, 0.0, 0.03 / _DEFAULT_DT, 0.7 / _DEFAULT_DT, 0.3 / _DEFAULT_DT)

    def _draw_bands(self) -> list[tuple[float, float]]:
        lo_frac, hi_frac = self.band_region
        lo, hi = lo_frac * self.height, hi_frac * self.height
        return [
            (self.rng.uniform(lo, hi), self.rng.uniform(self.config.band_sigma_lo, self.config.band_sigma_hi))
            for _ in range(self.config.band_count)
        ]

    def _build_env(self) -> list[float]:
        return [
            sum(math.exp(-((y - centre) / sigma) ** 2) for centre, sigma in self.bands)
            for y in range(self.height)
        ]

    @property
    def active(self) -> list[bool]:
        """Which rows advect/diffuse/react/clamp (and `_project_composite`)
        should bother with — see the note in `__init__`. Lazily refreshed
        from `d` on the first read after construction/`resize`; every read
        after that is the cache `advance()` keeps current incrementally."""
        if self._active_dirty:
            self._nonzero = [any(v > 0.0 for v in row) for row in self.d]
            self._m_settled = [all(w == 1.0 for w in row) for row in self.m]
            self._active_cache = self._dilate(self._nonzero)
            self._active_dirty = False
        return self._active_cache

    # ---- advance ----------------------------------------------------------

    def advance(self, dt: float, world_wind: float, shear_floor: float, shear_base: float, shear_span: float) -> None:
        wind = world_wind * self.config.wind_scale
        active = self.active  # triggers the lazy refresh above if needed
        self._advect(active, wind, shear_floor, shear_base, shear_span, dt)
        self._diffuse(active, dt)
        # `_react` also has to run on a row with zero density (and no active
        # neighbour) whose moisture has not yet fully replenished back to
        # 1.0 — skipping it there would freeze that recovery mid-flight,
        # changing the growth this row gets once density reaches it again.
        # A row that is neither is a true no-op for `_react` (`v == 0`
        # zeroes `grown` regardless of `env`, and `replenish * (1 - 1.0)` is
        # exactly 0), so skipping it is exact, not an approximation.
        react_active = [active[y] or not self._m_settled[y] for y in range(self.height)]
        self._react(react_active, dt)
        self._nucleate(dt)
        # `_nucleate` may have just set `_nonzero` true on a row `active`
        # didn't cover; re-dilate before `clamp` so that row gets floor-
        # snapped too, then refresh `_nonzero`/`_m_settled` only for the rows
        # this frame actually touched — every other row is exactly as it
        # was, so its state cannot have changed.
        touched = self._dilate(self._nonzero)
        self._clamp(touched)
        for y in range(self.height):
            if touched[y]:
                self._nonzero[y] = any(v > 0.0 for v in self.d[y])
            if react_active[y]:
                self._m_settled[y] = all(w == 1.0 for w in self.m[y])
        self._active_cache = self._dilate(self._nonzero)

    def tick(self, world_wind: float, shear_floor: float, shear_base: float, shear_span: float) -> None:
        """Thin wrapper for tests: one frame of `_DEFAULT_DT` wall time."""
        self.advance(_DEFAULT_DT, world_wind, shear_floor, shear_base, shear_span)

    def _dilate(self, nz: list[bool]) -> list[bool]:
        """`nz` widened by one row either side — a row with all-zero density
        still needs advect/diffuse to run on it while an active neighbour can
        bleed density into it."""
        h = self.height
        return [nz[y] or (y > 0 and nz[y - 1]) or (y + 1 < h and nz[y + 1]) for y in range(h)]

    def _advect(
        self, active: list[bool], wind: float, shear_floor: float, shear_base: float, shear_span: float, dt: float,
    ) -> None:
        h = self.height
        d = self.d
        for y in range(h):
            if not active[y]:
                continue
            u = wind * (shear_base + shear_span * (1.0 - y / h))
            if abs(u) < shear_floor:
                u = math.copysign(shear_floor, u) if u != 0.0 else shear_floor
            shift = u * dt
            k = math.floor(shift)
            frac = shift - k
            row = d[y]
            i0 = _rotate(row, k + 1)
            i1 = _rotate(row, k)
            d[y][:] = [a * frac + b * (1.0 - frac) for a, b in zip(i0, i1)]

    def _diffuse(self, active: list[bool], dt: float) -> None:
        h, w = self.height, self.width
        kx, ky = self.config.kx * dt, self.config.ky * dt
        d = self.d
        updates = []
        for y in range(h):
            if not active[y]:
                continue
            row = d[y]
            left = _rotate(row, 1)
            right = _rotate(row, -1)
            up = d[y + 1] if y + 1 < h else row
            down = d[y - 1] if y - 1 >= 0 else row
            updates.append((y, [
                row[x] + kx * (left[x] + right[x] - 2.0 * row[x]) + ky * (up[x] + down[x] - 2.0 * row[x])
                for x in range(w)
            ]))
        for y, new_row in updates:
            d[y][:] = new_row

    def _react(self, active: list[bool], dt: float) -> None:
        g, e = self.config.growth, self.config.evaporation
        uptake, replenish = self.config.uptake, self.config.replenish
        allee = self.config.allee
        env = self.env
        d, m = self.d, self.m
        for y in range(self.height):
            if not active[y]:
                continue
            envy = env[y]
            drow, mrow = d[y], m[y]
            if envy == 0.0:
                # `gy = g * envy` is exactly 0.0 here (a row far enough from
                # every band that the Gaussian underflows), so `grown` is
                # exactly 0.0 for every pixel — skip the per-pixel growth
                # polynomial, but keep the same floating-point expression
                # the general branch would reduce to with `gr = 0.0`, so
                # this is bit-identical, not an approximation.
                drow[:] = [v + dt * (0.0 - e * v) for v in drow]
                mrow[:] = [w + dt * (replenish * (1.0 - w) - uptake * 0.0) for w in mrow]
                continue
            gy = g * envy
            # Bistable growth: below `allee` the term is negative and a faint
            # wisp thins away; above it a streak grows toward full. `grown`
            # is a rate (per second); `dt` integrates it and the evaporation/
            # uptake/replenish terms alongside it, Euler-style.
            grown = [gy * v * (v - allee) * (1.0 - v) * w for v, w in zip(drow, mrow)]
            drow[:] = [v + dt * (gr - e * v) for v, gr in zip(drow, grown)]
            mrow[:] = [
                w + dt * (replenish * (1.0 - w) - uptake * (gr if gr > 0.0 else 0.0))
                for w, gr in zip(mrow, grown)
            ]

    def _nucleate(self, dt: float, force: bool = False) -> None:
        cfg = self.config
        if not self.bands:
            return
        if not force and self.rng.random() >= cfg.nucleate_p * dt:
            return
        centre, sigma = self.bands[self.rng.randrange(len(self.bands))]
        y = max(0, min(self.height - 1, int(round(self.rng.gauss(centre, sigma)))))
        x0 = self.rng.randrange(self.width)
        amt = self.rng.uniform(cfg.puff_lo, cfg.puff_hi)
        w = self.width
        for dy in range(cfg.puff_height):
            yy = y + dy
            if yy >= self.height:
                break
            row = self.d[yy]
            for i in range(cfg.puff_width):
                xx = (x0 + i) % w
                row[xx] = min(1.0, row[xx] + amt)
            self._nonzero[yy] = True  # a puff always adds positive density

    def _clamp(self, active: list[bool]) -> None:
        # Below `floor` a pixel snaps to zero: evaporation is exponential and
        # would otherwise leave a faint haze of specks over the whole sky.
        floor = self.config.floor
        d = self.d
        for y in range(self.height):
            if not active[y]:
                continue
            row = d[y]
            row[:] = [0.0 if v < floor else 1.0 if v > 1.0 else v for v in row]

    # ---- resize -----------------------------------------------------------

    def resize(self, width_px: int, height_px: int) -> None:
        """Bilinearly resample `d` (wrapping in x, clamped in y) into the new
        size, keeping the weather that was there; the only place `d` (and
        `bands`/`env`) are rebuilt wholesale."""
        new_w, new_h = max(width_px, 1), max(height_px, 1)
        old_w, old_h, old_d = self.width, self.height, self.d

        def sample(x: float, y: float) -> float:
            x %= old_w
            x0 = int(math.floor(x))
            x1 = (x0 + 1) % old_w
            tx = x - x0
            y0 = max(0, min(old_h - 1, int(math.floor(y))))
            y1 = max(0, min(old_h - 1, y0 + 1))
            ty = y - y0
            row0, row1 = old_d[y0], old_d[y1]
            a = row0[x0] + (row0[x1] - row0[x0]) * tx
            b = row1[x0] + (row1[x1] - row1[x0]) * tx
            return a + (b - a) * ty

        new_d = []
        for ny in range(new_h):
            sy = ny * (old_h - 1) / (new_h - 1) if new_h > 1 and old_h > 1 else 0.0
            sx_scale = old_w / new_w
            new_d.append([sample(nx * sx_scale, sy) for nx in range(new_w)])

        scale = new_h / old_h if old_h else 1.0
        self.width, self.height = new_w, new_h
        self.d = new_d
        self.m = [[1.0] * new_w for _ in range(new_h)]
        self.bands = [(c * scale, s * scale) for c, s in self.bands]
        self.env = self._build_env()
        self._nonzero = [any(v > 0.0 for v in row) for row in self.d]
        self._m_settled = [True] * self.height  # `m` was just rebuilt at 1.0 everywhere
        self._active_cache = self._dilate(self._nonzero)
        self._active_dirty = False


# ---- downsample -------------------------------------------------------


def _gradients(pixels: list[list[float]]) -> tuple[float, float]:
    left = (pixels[0][0] + pixels[1][0] + pixels[2][0] + pixels[3][0]) / 4.0
    right = (pixels[0][1] + pixels[1][1] + pixels[2][1] + pixels[3][1]) / 4.0
    top = sum(pixels[0]) / 2.0 + sum(pixels[1]) / 2.0
    bottom = sum(pixels[2]) / 2.0 + sum(pixels[3]) / 2.0
    return right - left, (top / 2.0) - (bottom / 2.0)


def _cell_hash(x0: int, y0: int) -> int:
    """A cheap, deterministic per-cell hash — stable for a given pixel
    position, so it reads as a fixed spatial pattern rather than flickering
    frame to frame."""
    h = (x0 * 374761393 + y0 * 668265263) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h & 0x7FFFFFFF


def _speck_glyph(x0: int, y0: int) -> str:
    return _SPECK_GLYPHS[_cell_hash(x0, y0) % len(_SPECK_GLYPHS)]


# 2x4 ordered (Bayer) dither matrix, one fixed threshold per dot position in
# a cell, so a cell's tone (0-8 lit dots) reads as a stable spatial pattern
# rather than every dot snapping on together at one density.
_BAYER = ((0, 4), (6, 2), (1, 5), (7, 3))
_BAYER_THRESHOLD = tuple(tuple(v / 8.0 + 1.0 / 16.0 for v in row) for row in _BAYER)
# Braille dot bit for each (col, row) position in a PX_X x PX_Y block,
# standard braille bit order: col 0 is bits 0,1,2,6 top to bottom, col 1 is
# bits 3,4,5,7 top to bottom.
_BRAILLE_BIT = {
    (0, 0): 0, (0, 1): 1, (0, 2): 2, (0, 3): 6,
    (1, 0): 3, (1, 1): 4, (1, 2): 5, (1, 3): 7,
}


def _ordered_dither(pixels: list[list[float]]) -> str:
    """A braille glyph from per-pixel density against the fixed Bayer
    thresholds — nine visible tones per cell (0-8 lit dots)."""
    bits = 0
    for row in range(PX_Y):
        for col in range(PX_X):
            if pixels[row][col] > _BAYER_THRESHOLD[row][col]:
                bits |= 1 << _BRAILLE_BIT[(col, row)]
    return chr(0x2800 | bits)


def _majority_owner(owner_rows: list[list[str]], x0: int) -> str:
    """The block's most-common owning grid, ties broken toward the nearest
    (`GRID_ORDER`); `""` if no pixel in the block has an owner."""
    counts: dict[str, int] = {}
    for row in owner_rows:
        for v in row[x0: x0 + PX_X]:
            if v:
                counts[v] = counts.get(v, 0) + 1
    if not counts:
        return ""
    rank = {name: i for i, name in enumerate(GRID_ORDER)}
    return min(counts, key=lambda k: (-counts[k], rank[k]))


def _cell_colour(
    cfg: SkyConfig, palette, owner: str, m: float, row_from_bottom: int, sky_rows: int,
    z: float | None = None, z_far: float | None = None,
) -> str:
    """A cell's colour, haze-shifted either by screen row (pre-v7, `z` and
    `z_far` omitted) or by world distance `z` (v7, `Sky.render_cells`'
    perspective path) — same shape shift, `clamp(z / z_far)` standing in for
    `row / (sky_rows - 1)`."""
    name = owner or "near"
    tone = m ** cfg.tone_exp
    base = _ramp16(getattr(palette, f"cloud_{name}_dark"), getattr(palette, f"cloud_{name}_light"), tone)
    if z is not None and z_far:
        t = cfg.haze_depth_weight * GRID_DEPTH[name] + cfg.haze_row_weight * _clamp(z / z_far, 0.0, 1.0)
        return _lerp_hex(base, palette.haze, _clamp(t, 0.0, cfg.haze_clamp))
    return atmospheric_colour(
        base, GRID_DEPTH[name], row_from_bottom, sky_rows, palette,
        cfg.haze_depth_weight, cfg.haze_row_weight, cfg.haze_clamp,
    )


def _composite(grids: dict[str, Air]) -> tuple[list[list[float]], list[list[str]]]:
    """Front-to-back (`GRID_ORDER`) composite: the nearest grid whose pixel
    clears `DENSITY_FLOOR` owns it, never overwritten by one further back."""
    any_grid = next(iter(grids.values()))
    h, w = any_grid.height, any_grid.width
    density = [[0.0] * w for _ in range(h)]
    owner = [[""] * w for _ in range(h)]
    for y in range(h):
        rows = [(name, grids[name].d[y]) for name in GRID_ORDER]
        drow, orow = density[y], owner[y]
        for x in range(w):
            for name, row in rows:
                v = row[x]
                if v > DENSITY_FLOOR:
                    drow[x] = v
                    orow[x] = name
                    break
    return density, owner


_BLANK_ROW_CACHE: dict[int, list[tuple[str, None]]] = {}


def _blank_row(cols: int) -> list[tuple[str, None]]:
    """A whole row of `(" ", None)` cells, cached by width — the fast path
    for a terminal row `downsample` already knows carries no density at all
    (v6f, `row_empty`)."""
    row = _BLANK_ROW_CACHE.get(cols)
    if row is None:
        row = [(" ", None)] * cols
        _BLANK_ROW_CACHE[cols] = row
    return row


def downsample(
    grids: dict[str, Air], palette, sky_rows: int, cols: int, cfg: SkyConfig, *,
    density: list[list[float]] | None = None,
    owner: list[list[str]] | None = None,
    z_by_row: list[float] | None = None,
    row_empty: list[bool] | None = None,
) -> list[list[tuple[str, str | None]]]:
    """One `(glyph, colour)` per terminal cell from a composited `PX_X x
    PX_Y` pixel block, top row first.

    `density`/`owner` are already-built top-down pixel arrays — v7's
    `Sky.render_cells` passes its perspective-projected canvas
    (`_project_composite`) here instead of a 1:1 copy of the grids. Omitted
    (every pre-v7 caller, including every direct-array test), this falls
    back to `_composite(grids)` reversed, exactly as before. `z_by_row`, one
    world distance per terminal row, drives the v7 z-based haze mix; omitted,
    haze falls back to the old row/sky_rows shift. `row_empty`, one flag per
    *pixel* row from `_project_composite` (v6f), lets a terminal row whose
    whole `PX_Y`-pixel block is empty skip the per-cell loop outright — a
    fully empty block's mean is always 0 and its peak never clears
    `DENSITY_FLOOR`, so every cell in it would render blank anyway.
    """
    if density is None or owner is None:
        density, owner = _composite(grids)
        density = density[::-1]  # Air is bottom-up; render top-down
        owner = owner[::-1]
    out: list[list[tuple[str, str | None]]] = []
    for row_i in range(sky_rows):
        y0 = row_i * PX_Y
        if row_empty is not None and all(row_empty[y0: y0 + PX_Y]):
            out.append(_blank_row(cols))
            continue
        block_density = density[y0: y0 + PX_Y]
        block_owner = owner[y0: y0 + PX_Y]
        row_from_bottom = (sky_rows - 1) - row_i
        z_for_row = z_by_row[row_i] if z_by_row is not None else None
        z_far_for_row = cfg.z_far if z_for_row is not None else None
        out_row: list[tuple[str, str | None]] = []
        for col_i in range(cols):
            x0 = col_i * PX_X
            pixels = [r[x0: x0 + PX_X] for r in block_density]
            flat = [v for prow in pixels for v in prow]
            m = sum(flat) / 8.0
            if m < cfg.blank_mean:
                peak = max(flat)
                if peak <= DENSITY_FLOOR or _cell_hash(x0, y0) % 3:
                    out_row.append((" ", None))
                    continue
                glyph = _speck_glyph(x0, y0)
                owner_name = _majority_owner(block_owner, x0)
                colour = _cell_colour(cfg, palette, owner_name, m, row_from_bottom, sky_rows, z_for_row, z_far_for_row)
                out_row.append((glyph, colour))
                continue
            gx, gy = _gradients(pixels)
            if m >= cfg.core_mean:
                glyph = CORE_GLYPH
            elif m >= cfg.semi_core_mean:
                glyph = CORE_GLYPH if _cell_hash(x0, y0) % 2 == 0 else _ordered_dither(pixels)
            elif abs(gx) > cfg.flat_gx and abs(gy) <= cfg.flat_gy_max and cfg.flat_mean_lo <= m < cfg.flat_mean_hi:
                glyph = "-" if _cell_hash(x0, y0) % 2 == 0 else "~"
            elif _cell_hash(x0, y0) % 3 == 0 and (grain := _grain_glyph(m, x0, y0)) is not None:
                glyph = grain
            else:
                glyph = _ordered_dither(pixels)
            owner_name = _majority_owner(block_owner, x0)
            colour = _cell_colour(cfg, palette, owner_name, m, row_from_bottom, sky_rows, z_for_row, z_far_for_row)
            out_row.append((glyph, colour))
        out.append(out_row)
    return out


# ---- perspective (v7) ---------------------------------------------------


def _screen_projection_row(py: int, height_px: int, cfg: SkyConfig) -> tuple[bool, float, float]:
    """One screen pixel row's `(is_sky, z, xscale)`.

    `horizon_px` is the horizon line in pixel-row units, `cfg.horizon` down
    from the top of the sky. A row at or above it (`py <= horizon_px -
    deck_altitude_px`) is open sky. `deck_altitude_px` (world y of the deck)
    lets a thin sliver of rows just above the horizon still show the deck at
    its farthest (`z_far`) — 0 by default, so the deck stays entirely below
    the horizon. Below the horizon, `z = focal / (py - horizon_px)`: smaller
    at the bottom of the screen (near), larger just below the horizon (far),
    clamped to `z_far`. `xscale = z / focal` is the row's horizontal scale —
    a world-x offset reads `xscale` screen pixels wide at this row."""
    horizon_px = cfg.horizon * height_px
    deck_start_px = horizon_px - cfg.deck_altitude_px
    if py <= deck_start_px:
        return True, 0.0, 0.0
    if py <= horizon_px:
        z = cfg.z_far
    elif cfg.focal > 0:
        z = min(cfg.focal / (py - horizon_px), cfg.z_far)
    else:
        z = 0.0
    xscale = z / cfg.focal if cfg.focal > 0 else 0.0
    return False, z, xscale


def _build_projection_rows(
    height_px: int, width_px: int, cfg: SkyConfig,
) -> list[tuple[bool, float, int, int, float, list[float] | None]]:
    """`Sky._build_projection`'s whole per-pixel-row cache, built once per
    resize/`apply` and never touched per frame.

    Each entry is `(is_sky, z, y0, y1, ty, base_row)`: `y0`/`y1`/`ty` are the
    row's fixed grid-space bilinear tap (two grid rows and a weight between
    them — every grid shares `height_px`, so one tap serves all three);
    `base_row`, `[(px - centre) * xscale for px in range(width_px)]`, is the
    row's whole horizontal sample pattern *before* the frame's `camera_x`
    offset — the one part of a pixel's world-x that can't change without a
    resize. A sky row's entry carries only `is_sky`; nothing else is read
    for it. Frame time then only ever adds `camera_x` to a precomputed list
    and taps two precomputed grid rows — no `math` calls, no per-pixel
    function calls, in the per-frame path (`_project_composite`)."""
    centre_px = width_px / 2.0
    base_cols = [px - centre_px for px in range(width_px)]
    rows: list[tuple[bool, float, int, int, float, list[float] | None]] = []
    for py in range(height_px):
        is_sky, z, xscale = _screen_projection_row(py, height_px, cfg)
        if is_sky:
            rows.append((True, 0.0, 0, 0, 0.0, None))
            continue
        z_frac = 0.0 if cfg.z_far <= 0 else _clamp(z / cfg.z_far, 0.0, 1.0)
        gy = z_frac * (height_px - 1) if height_px > 1 else 0.0
        y0 = int(gy)
        y1 = min(height_px - 1, y0 + 1)
        ty = gy - y0
        base_row = [b * xscale for b in base_cols]
        rows.append((False, z, y0, y1, ty, base_row))
    return rows


def _project_composite(
    grids: dict[str, Air], proj_rows: list[tuple[bool, float, int, int, float, list[float] | None]],
    width_px: int, camera_x: float,
) -> tuple[list[list[float]], list[list[str]], list[float], list[bool]]:
    """Perspective-projected composite (v7), top row first (unlike
    `_composite`'s bottom-up `Air.d`).

    Per frame, per deck row: add `camera_x` to the row's precomputed
    `base_row` (one list comprehension), split into integer/fractional parts
    (two more), then bilinear-tap each grid's two precomputed rows at those
    indices (one comprehension per grid) and pick nearest-first
    (`GRID_ORDER`) with a final comprehension. Every step is a row-level list
    comprehension over plain arithmetic and indexing — no per-pixel function
    calls, no `math` module in this path at all. A grid's tap is skipped
    outright (v6f) when neither tapped row is `Air.active`; the fourth
    return value, `row_empty`, flags a pixel row where every grid's tap was
    skipped, so `downsample` can fast-path a whole blank terminal row.
    """
    g_width = next(iter(grids.values())).width
    near_d, mid_d, far_d = grids["near"].d, grids["mid"].d, grids["far"].d
    near_active, mid_active, far_active = grids["near"].active, grids["mid"].active, grids["far"].active
    zero_row = [0.0] * width_px
    empty_owner_row = [""] * width_px
    density: list[list[float]] = []
    owner: list[list[str]] = []
    z_by_pixel_row: list[float] = []
    row_empty: list[bool] = []
    for is_sky, z, y0, y1, ty, base_row in proj_rows:
        if is_sky:
            density.append(zero_row)
            owner.append(empty_owner_row)
            z_by_pixel_row.append(0.0)
            row_empty.append(True)
            continue
        z_by_pixel_row.append(z)
        xs = [(b + camera_x) % g_width for b in base_row]
        x0 = [int(x) for x in xs]
        tx = [x - i for x, i in zip(xs, x0)]
        x1 = [i + 1 if i + 1 < g_width else 0 for i in x0]
        oty = 1.0 - ty
        # Skip a grid's bilinear tap outright when neither tapped row carries
        # any density (perf, v6f) — the projection reads two arbitrary grid
        # rows per screen row, so it plugs into the same `Air.active` sparsity
        # signal advect/diffuse/react already gate on, not screen-row bands.
        if near_active[y0] or near_active[y1]:
            near0, near1 = near_d[y0], near_d[y1]
            near_v = [
                (near0[a] + (near0[b] - near0[a]) * t) * oty + (near1[a] + (near1[b] - near1[a]) * t) * ty
                for a, b, t in zip(x0, x1, tx)
            ]
        else:
            near_v = zero_row
        if mid_active[y0] or mid_active[y1]:
            mid0, mid1 = mid_d[y0], mid_d[y1]
            mid_v = [
                (mid0[a] + (mid0[b] - mid0[a]) * t) * oty + (mid1[a] + (mid1[b] - mid1[a]) * t) * ty
                for a, b, t in zip(x0, x1, tx)
            ]
        else:
            mid_v = zero_row
        # The far deck only ever owns a pixel behind near and mid, and is the
        # most compressed layer anyway — half the horizontal taps (every
        # other column, nearest-neighbour-duplicated back to full width)
        # keeps the frame budget without a visible loss (perf note, v7).
        if far_active[y0] or far_active[y1]:
            far0, far1 = far_d[y0], far_d[y1]
            far_half = [
                (far0[a] + (far0[b] - far0[a]) * t) * oty + (far1[a] + (far1[b] - far1[a]) * t) * ty
                for a, b, t in zip(x0[::2], x1[::2], tx[::2])
            ]
            far_v = [far_half[i >> 1] for i in range(len(x0))]
        else:
            far_v = zero_row
        if near_v is zero_row and mid_v is zero_row and far_v is zero_row:
            # None of the three grids had density at either tapped row —
            # this whole pixel row is empty, no per-pixel picking needed.
            density.append(zero_row)
            owner.append(empty_owner_row)
            row_empty.append(True)
            continue
        picks = [
            (nv, "near") if nv > DENSITY_FLOOR else
            (mv, "mid") if mv > DENSITY_FLOOR else
            (fv, "far") if fv > DENSITY_FLOOR else
            (0.0, "")
            for nv, mv, fv in zip(near_v, mid_v, far_v)
        ]
        drow, orow = zip(*picks) if picks else ((), ())
        density.append(list(drow))
        owner.append(list(orow))
        row_empty.append(False)
    return density, owner, z_by_pixel_row, row_empty


# ---- Sky ----------------------------------------------------------------


class Sky:
    """Owns the three depth grids for one field."""

    ENGINE = "fluid"

    def __init__(self, cols: int, sky_rows: int, rng: random.Random, palette, config: SkyConfig | None = None) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        self.rng = rng
        self.palette = palette
        self.config = config or SkyConfig()
        self.camera_x = 0.0
        self._bake()
        self._build_projection()

    def _bake(self) -> None:
        width_px = max(self.cols * PX_X, 1)
        height_px = max(self.sky_rows * PX_Y, 1)
        self.grids: dict[str, Air] = {
            name: Air(width_px, height_px, self.rng, getattr(self.config, name), GRID_BAND_REGION[name])
            for name in GRID_ORDER
        }

    def _build_projection(self) -> None:
        """v7: `_build_projection_rows`'s cache, one entry per pixel row of
        sky height, rebuilt whenever the size or the shared projection
        levers can have changed (`__init__`, `resize`, `apply`) — never per
        frame."""
        height_px = max(self.sky_rows * PX_Y, 1)
        self._proj_width_px = max(self.cols * PX_X, 1)
        self._proj_rows = _build_projection_rows(height_px, self._proj_width_px, self.config)

    def apply(self, config: SkyConfig) -> None:
        """Swap tuning constants into the running grids without resetting
        them — their drawn bands and current weather stay exactly as they
        are; only the live physics/render knobs change."""
        self.config = config
        for name in GRID_ORDER:
            self.grids[name].config = getattr(config, name)
        self._build_projection()

    def resize(self, cols: int, sky_rows: int) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        width_px = max(self.cols * PX_X, 1)
        height_px = max(self.sky_rows * PX_Y, 1)
        for grid in self.grids.values():
            grid.resize(width_px, height_px)
        self._build_projection()

    def advance(self, dt: float, wind: float = 0.0) -> None:
        cfg = self.config
        for grid in self.grids.values():
            grid.advance(dt, wind, cfg.shear_floor, cfg.shear_base, cfg.shear_span)
        # v7: the camera pans with the wind too, at the same base rate the
        # grids' own row shear uses, so the whole projected scene drifts —
        # never a perfectly fixed frame.
        if self._proj_width_px:
            self.camera_x = (self.camera_x + wind * cfg.shear_base * dt) % self._proj_width_px

    def tick(self, wind: float = 0.0) -> None:
        """Thin wrapper for tests: one frame of `_DEFAULT_DT` wall time."""
        self.advance(_DEFAULT_DT, wind)

    def render_cells(self) -> list[list[tuple[str, str | None]]]:
        if self.cols <= 0 or self.sky_rows <= 0:
            return []
        if self.config.perspective == "off":
            # The v6 path (v8, `perspective = 'off'`): no projection, each
            # deck's bands drawn flat across the sky at their own height.
            return downsample(self.grids, self.palette, self.sky_rows, self.cols, self.config)
        density, owner, z_by_pixel_row, row_empty = _project_composite(
            self.grids, self._proj_rows, self._proj_width_px, self.camera_x,
        )
        z_by_row = [z_by_pixel_row[min(row_i * PX_Y, len(z_by_pixel_row) - 1)] for row_i in range(self.sky_rows)]
        return downsample(
            self.grids, self.palette, self.sky_rows, self.cols, self.config,
            density=density, owner=owner, z_by_row=z_by_row, row_empty=row_empty,
        )


# ---- texture engine (v5, restored as `sky_engine == "texture"`, v6f) -------
#
# The look q384 ("field-best") tagged, from before the cellular-automaton
# grids existed: two baked, scrolling, slowly-morphing value-noise textures
# per depth, composited nearest-first and read through the very same
# `downsample()` the fluid engine uses. No cellular automaton, no
# perspective projection — a fraction of `Sky`'s per-frame cost, behind the
# same four-method interface (`advance`, `render_cells`, `resize`, `apply`).
# Every per-tick-at-0.1s rate from the original v5 module is divided by
# `_DEFAULT_DT` here, the same conversion `GridConfig`'s rates got in v6b, so
# `advance(dt)` integrates continuously and the look at the TUI's default
# sampling is unchanged from v5.

_TEX_MORPH_SECONDS = 120.0  # a layer's texture fully morphs into a fresh one
_TEX_BREATH_SECONDS = 90.0  # the density cutoff's swell/thin cycle
_TEX_BREATH_AMPLITUDE = 0.06

# depth (for colour parity with GRID_DEPTH), octave count, the anisotropic
# feature scale (`scale_x` in terminal cells, `scale_y` in pixel rows — very
# different so fbm reads long and thin, cirrus rather than blobs), the fbm
# cutoff/gain that shape density, scroll speed (per second), this layer's
# stagger in [0, 1) (its own starting point on the morph/breath cycles, so
# the three layers never crest together), and the vertical comb's period.
_TEX_BANDS = {
    "far": dict(depth=0.9, octaves=3, scale_x=40, scale_y=3, cutoff=0.55, gain=3.5,
                speed=0.02 / _DEFAULT_DT, stagger=0.0, comb_period=6),
    "mid": dict(depth=0.6, octaves=3, scale_x=28, scale_y=4, cutoff=0.51, gain=3.2,
                speed=0.05 / _DEFAULT_DT, stagger=0.33, comb_period=8),
    "near": dict(depth=0.2, octaves=2, scale_x=18, scale_y=6, cutoff=0.48, gain=3.0,
                 speed=0.10 / _DEFAULT_DT, stagger=0.66, comb_period=10),
}


def _smoothstep(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class _TexNoise:
    """A lattice of random floats, wrapping horizontally, bilinear-sampled."""

    def __init__(self, rng: random.Random, lattice_w: int, lattice_h: int) -> None:
        self.lattice_w = lattice_w
        self.lattice_h = lattice_h
        self.lattice = [[rng.random() for _ in range(lattice_w)] for _ in range(lattice_h)]

    def sample(self, x: float, y: float) -> float:
        lw, lh = self.lattice_w, self.lattice_h
        x = x % lw
        x0 = int(x)
        x1 = (x0 + 1) % lw
        tx = _smoothstep(x - x0)
        y0f = int(y)
        y1f = y0f + 1
        ty = _smoothstep(y - y0f)
        y0 = min(max(y0f, 0), lh - 1)
        y1 = min(max(y1f, 0), lh - 1)
        row0, row1 = self.lattice[y0], self.lattice[y1]
        a = row0[x0] + (row0[x1] - row0[x0]) * tx
        b = row1[x0] + (row1[x1] - row1[x0]) * tx
        return a + (b - a) * ty

    def fbm(self, x: float, y: float, octaves: int, lacunarity: float = 2.0, gain: float = 0.5) -> float:
        freq, amp, total, norm = 1.0, 1.0, 0.0, 0.0
        for _ in range(octaves):
            total += amp * self.sample(x * freq, y * freq)
            norm += amp
            freq *= lacunarity
            amp *= gain
        return total / norm if norm else 0.0


def _tex_read_window(row: list[float], off: int, w: int, period: int) -> list[float]:
    """`w` values starting at `off`, wrapping at `period` — the seamless scroll."""
    end = off + w
    if end <= period:
        return row[off:end]
    return row[off:period] + row[0:end - period]


class _TexLayer:
    """One depth band's pair of baked, scrolling, morphing raw-fbm textures
    (v5). `tex_a`/`tex_b` hold raw fbm values in [0, 1] — no cutoff, gain, or
    envelope baked in, so the cutoff can breathe at composite time for free.
    Each is baked exactly `period_px` wide, one full period of the lattice
    noise in x, so a `width_px`-wide read window wraps by plain modulo
    indexing (`_tex_read_window`) with no seam."""

    def __init__(self, band: str, width_px: int, height_px: int, rng: random.Random) -> None:
        p = _TEX_BANDS[band]
        self.band = band
        self.depth = p["depth"]
        self.width_px = width_px
        self.height_px = height_px
        self.speed = p["speed"]

        self.scale_x_px = p["scale_x"] * PX_X
        self.scale_y_px = p["scale_y"]
        self.octaves = p["octaves"]
        self.base_cutoff = p["cutoff"]
        self.gain = p["gain"]
        self.comb_period = p["comb_period"]
        self.comb_phase = rng.uniform(0.0, 2.0 * math.pi)

        self.blend = p["stagger"]
        self.breath_phase = 2.0 * math.pi * p["stagger"]
        self._time = 0.0

        # Vertical envelope: a shared bell shape (bunched a little above mid
        # height) times this layer's own thin horizontal comb, so streaks sit
        # in stacked bands instead of one wide blob.
        centre = 0.55 * height_px
        sigma = max(0.22 * height_px, 1e-6)
        self.envelope = [
            math.exp(-((y - centre) / sigma) ** 2) * self._comb(y)
            for y in range(height_px)
        ]

        min_period = max(2 * width_px, 1)
        self.lattice_w = max(3, -(-min_period // self.scale_x_px))  # ceil div
        self.period_px = self.lattice_w * self.scale_x_px
        self.lattice_h = max(3, round(height_px / self.scale_y_px) + 2)

        self.offset = 0.0
        self.rng = rng
        self.tex_a = self._bake_raw()
        self.tex_b = self._bake_raw()

    def _comb(self, y: int) -> float:
        phase = 2.0 * math.pi * y / self.comb_period + self.comb_phase
        return 0.8 + 0.2 * (0.5 + 0.5 * math.cos(phase))

    def _bake_raw(self) -> list[list[float]]:
        noise = _TexNoise(self.rng, self.lattice_w, self.lattice_h)
        tex: list[list[float]] = []
        for y in range(self.height_px):
            if self.envelope[y] < 1e-4:
                tex.append([0.0] * self.period_px)
                continue
            ys = y / self.scale_y_px
            tex.append([
                noise.fbm(x / self.scale_x_px, ys, self.octaves)
                for x in range(self.period_px)
            ])
        return tex

    def tick(self, dt: float) -> None:
        self._time += dt
        self.offset = (self.offset + self.speed * dt) % self.period_px
        self.blend += dt / _TEX_MORPH_SECONDS
        if self.blend >= 1.0:
            self.blend = 0.0
            self.tex_a = self.tex_b
            self.tex_b = self._bake_raw()

    def _effective_cutoff(self) -> float:
        phase = 2.0 * math.pi * self._time / _TEX_BREATH_SECONDS + self.breath_phase
        return self.base_cutoff + _TEX_BREATH_AMPLITUDE * math.sin(phase)

    def density_row(self, y: int) -> list[float]:
        """This layer's composited density for row `y`, `width_px` wide,
        already windowed by `offset`."""
        env = self.envelope[y]
        if env < 1e-4:
            return [0.0] * self.width_px
        off = int(self.offset)
        w = self.width_px
        period = self.period_px
        row_a = _tex_read_window(self.tex_a[y], off, w, period)
        row_b = _tex_read_window(self.tex_b[y], off, w, period)
        blend = self.blend
        cut = self._effective_cutoff()
        gain = self.gain
        out = []
        for a, b in zip(row_a, row_b):
            raw = a + (b - a) * blend
            d = (raw - cut) * gain
            d = 0.0 if d < 0.0 else (1.0 if d > 1.0 else d)
            out.append(env * (d ** 0.7 if d > 0.0 else 0.0))
        return out


def _texture_composite(
    layers: dict[str, "_TexLayer"], height_px: int, width_px: int,
) -> tuple[list[list[float]], list[list[str]]]:
    """Front-to-back (`GRID_ORDER`) composite of every layer's `density_row`,
    top row first — the same ownership rule `_composite` uses for `Air`."""
    density = [[0.0] * width_px for _ in range(height_px)]
    owner = [[""] * width_px for _ in range(height_px)]
    for y in range(height_px):
        rows = [(name, layers[name].density_row(y)) for name in GRID_ORDER]
        drow, orow = density[y], owner[y]
        for x in range(width_px):
            for name, row in rows:
                v = row[x]
                if v > DENSITY_FLOOR:
                    drow[x] = v
                    orow[x] = name
                    break
    return density, owner


class TextureSky:
    """v5's baked-noise sky, restored as the `sky_engine == "texture"` lever
    (v6f, q384): same four-method interface as `Sky` (`advance`,
    `render_cells`, `resize`, `apply`), read through the same tonal
    `downsample()`, but with no cellular automaton and no perspective
    projection — the cheap look a fraction of the fluid engine's frame cost."""

    ENGINE = "texture"

    def __init__(self, cols: int, sky_rows: int, rng: random.Random, palette, config: SkyConfig | None = None) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        self.rng = rng
        self.palette = palette
        self.config = config or SkyConfig()
        self.camera_x = 0.0
        self._bake()

    def _bake(self) -> None:
        self.width_px = max(self.cols * PX_X, 1)
        self.height_px = max(self.sky_rows * PX_Y, 1)
        self.layers: dict[str, _TexLayer] = {
            name: _TexLayer(name, self.width_px, self.height_px, self.rng) for name in GRID_ORDER
        }

    def apply(self, config: SkyConfig) -> None:
        self.config = config

    def resize(self, cols: int, sky_rows: int) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        self._bake()

    def advance(self, dt: float, wind: float = 0.0) -> None:
        for layer in self.layers.values():
            layer.tick(dt)
        # Same base drift `Sky.advance` gives its projected camera, so a
        # falling seed and field.py's ground lines still read the same wind.
        if self.width_px:
            self.camera_x = (self.camera_x + wind * self.config.shear_base * dt) % self.width_px

    def tick(self, wind: float = 0.0) -> None:
        """Thin wrapper for tests: one frame of `_DEFAULT_DT` wall time."""
        self.advance(_DEFAULT_DT, wind)

    def render_cells(self) -> list[list[tuple[str, str | None]]]:
        if self.cols <= 0 or self.sky_rows <= 0:
            return []
        density, owner = _texture_composite(self.layers, self.height_px, self.width_px)
        return downsample(self.layers, self.palette, self.sky_rows, self.cols, self.config, density=density, owner=owner)


# ---- puffs engine (v8) --------------------------------------------------
#
# The third engine: a population of individual clouds. Nothing scrolls the
# whole sky — `camera_x` stays 0 — and each cloud carries its own slow
# left-or-right drift, its own life, and its own pair of baked noise patches
# it morphs between. A cloud is born invisible and *unfolds*: its cutoff
# starts at 1.0 and sinks to the style's resting cutoff over the first part
# of its life, so the densest cores appear first and the fringes grow out of
# them; it holds, then the cutoff climbs back and the cloud recedes the same
# way in reverse. The look the texture engine's whole-layer scroll and morph
# could only approximate — clouds that change more than they travel.
#
# `_PUFF_STYLES` is one table per `cloud_style`, one entry per band:
#   w, h         a cloud's pixel width/height range (inclusive)
#   scale_x/y    noise lattice spacing inside the patch, pixels per node
#   octaves      fbm octaves
#   cutoff       the resting cutoff once unfolded (lower = fuller)
#   gain         density slope above the cutoff
#   drift        this band's share of `cloud_drift` (px/s), on top of a
#                random 0.3-1.0 per cloud; each cloud picks its own sign
#   spacing      columns of sky per cloud at `cloud_count == 1.0`
#   rise/fall    fraction of `cloud_life` spent unfolding / receding
#   morph        seconds for one a -> b -> a morph cycle
_PUFF_STYLES: dict[str, dict[str, dict]] = {
    "drift": {
        "far": dict(w=(30, 60), h=(4, 7), scale_x=10, scale_y=3, octaves=3, cutoff=0.38, gain=3.2,
                    drift=0.25, spacing=22, rise=0.30, fall=0.30, morph=80.0),
        "mid": dict(w=(26, 52), h=(6, 10), scale_x=9, scale_y=3, octaves=3, cutoff=0.36, gain=3.2,
                    drift=0.55, spacing=26, rise=0.30, fall=0.30, morph=70.0),
        "near": dict(w=(20, 44), h=(8, 14), scale_x=8, scale_y=4, octaves=2, cutoff=0.34, gain=3.0,
                     drift=1.0, spacing=32, rise=0.30, fall=0.30, morph=60.0),
    },
    "bloom": {
        "far": dict(w=(40, 80), h=(5, 8), scale_x=12, scale_y=3, octaves=3, cutoff=0.32, gain=2.8,
                    drift=0.05, spacing=26, rise=0.45, fall=0.35, morph=120.0),
        "mid": dict(w=(34, 70), h=(8, 12), scale_x=11, scale_y=4, octaves=3, cutoff=0.30, gain=2.8,
                    drift=0.10, spacing=30, rise=0.45, fall=0.35, morph=100.0),
        "near": dict(w=(28, 60), h=(10, 16), scale_x=10, scale_y=5, octaves=2, cutoff=0.28, gain=2.6,
                     drift=0.15, spacing=38, rise=0.45, fall=0.35, morph=90.0),
    },
    "streaks": {
        "far": dict(w=(70, 140), h=(2, 4), scale_x=14, scale_y=2, octaves=2, cutoff=0.40, gain=3.4,
                    drift=0.20, spacing=28, rise=0.35, fall=0.35, morph=90.0),
        "mid": dict(w=(60, 120), h=(3, 5), scale_x=12, scale_y=2, octaves=2, cutoff=0.38, gain=3.2,
                    drift=0.40, spacing=34, rise=0.35, fall=0.35, morph=80.0),
        "near": dict(w=(50, 100), h=(4, 6), scale_x=10, scale_y=2, octaves=2, cutoff=0.36, gain=3.0,
                     drift=0.70, spacing=40, rise=0.35, fall=0.35, morph=70.0),
    },
}


def _plateau(n: int, margin: float = 0.3) -> list[float]:
    """`n` weights: 1 across the middle, a cosine fade to 0 over the outer
    `margin` of each end — a cloud's soft rim around a body that keeps its
    full weight."""
    if n <= 1:
        return [1.0] * n
    m = max(margin * n, 1.0)
    out = []
    for i in range(n):
        edge = min(i + 0.5, n - i - 0.5)
        out.append(1.0 if edge >= m else 0.5 - 0.5 * math.cos(math.pi * edge / m))
    return out


def _puff_patch(rng: random.Random, w: int, h: int, p: dict) -> tuple[list[list[float]], list[list[float]]]:
    """One cloud's raw fbm patch, `h` rows of `w` in [0, 1], plus its edge
    window: a raised cosine in both axes, applied to the *thresholded*
    density at draw time so the cloud's cores keep their full weight and
    only its rim fades — windowing the raw noise would push every pixel
    under the cutoff."""
    lw = max(3, -(-w // p["scale_x"]) + 1)
    lh = max(3, -(-h // p["scale_y"]) + 1)
    noise = _TexNoise(rng, lw, lh)
    ex = _plateau(w)
    ey = _plateau(h)
    sx, sy, octaves = p["scale_x"], p["scale_y"], p["octaves"]
    raw = [[noise.fbm(x / sx, y / sy, octaves) for x in range(w)] for y in range(h)]
    win = [[ex[x] * ey[y] for x in range(w)] for y in range(h)]
    return raw, win


class _Puff:
    """One cloud: where it is, how it drifts, and how far through its life."""

    __slots__ = ("x", "y0", "w", "h", "vx", "age", "life", "patch_a", "patch_b", "window", "p", "band")

    def __init__(self, band: str, p: dict, width_px: int, height_px: int, rng: random.Random,
                 drift: float, life: float, *, age: float | None = None) -> None:
        self.band = band
        self.p = p
        self.w = min(rng.randint(*p["w"]), max(width_px, 1))
        self.h = min(rng.randint(*p["h"]), max(height_px, 1))
        lo, hi = GRID_BAND_REGION[band]
        # Band regions count from the bottom; the canvas is top-down.
        centre = (1.0 - rng.uniform(lo, hi)) * height_px
        self.y0 = int(_clamp(centre - self.h / 2.0, 0.0, max(height_px - self.h, 0)))
        self.x = rng.uniform(0.0, max(width_px, 1))
        self.vx = rng.choice((-1.0, 1.0)) * rng.uniform(0.3, 1.0) * drift * p["drift"]
        self.life = max(life, 1.0)
        self.age = rng.uniform(0.0, self.life) if age is None else age
        self.patch_a, self.window = _puff_patch(rng, self.w, self.h, p)
        self.patch_b, _ = _puff_patch(rng, self.w, self.h, p)

    def cutoff(self) -> float:
        """1.0 unborn, sinking to the style's resting cutoff as the cloud
        unfolds, climbing back as it recedes."""
        t = self.age / self.life
        rise, fall = self.p["rise"], self.p["fall"]
        if t < rise:
            reveal = _smoothstep(t / rise)
        elif t > 1.0 - fall:
            reveal = _smoothstep((1.0 - t) / fall)
        else:
            reveal = 1.0
        base = self.p["cutoff"]
        return base + (1.0 - base) * (1.0 - reveal)

    def blend(self) -> float:
        return 0.5 - 0.5 * math.cos(2.0 * math.pi * self.age / self.p["morph"])


class PuffSky:
    """Individual clouds, no whole-sky scroll (v8, `sky_engine == "puffs"`).
    Same four-method interface as `Sky` and `TextureSky`, read through the
    same `downsample()`. `cloud_style` picks a `_PUFF_STYLES` table,
    `cloud_count` scales the population, `cloud_drift` the top speed a
    cloud may wander at, `cloud_life` how long one lasts. `camera_x` never
    moves: the ground lines and the falling seeds still read the world's
    wind, but the sky behind them only unfolds, never slides."""

    ENGINE = "puffs"

    def __init__(self, cols: int, sky_rows: int, rng: random.Random, palette, config: SkyConfig | None = None) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        self.rng = rng
        self.palette = palette
        self.config = config or SkyConfig()
        self.camera_x = 0.0
        self._bake()

    # ---- population -------------------------------------------------

    def _style(self) -> dict[str, dict]:
        return _PUFF_STYLES.get(self.config.cloud_style, _PUFF_STYLES["drift"])

    def _target_count(self, p: dict) -> int:
        return max(1, round(self.cols / p["spacing"] * self.config.cloud_count))

    def _spawn(self, band: str, *, age: float | None = None) -> _Puff:
        p = self._style()[band]
        return _Puff(band, p, self.width_px, self.height_px, self.rng,
                     self.config.cloud_drift, self.config.cloud_life, age=age)

    def _bake(self) -> None:
        self.width_px = max(self.cols * PX_X, 1)
        self.height_px = max(self.sky_rows * PX_Y, 1)
        self._baked_style = self.config.cloud_style
        self.puffs: dict[str, list[_Puff]] = {}
        for band in GRID_ORDER:
            p = self._style()[band]
            self.puffs[band] = [self._spawn(band) for _ in range(self._target_count(p))]

    def apply(self, config: SkyConfig) -> None:
        """Retune live. A style change re-bakes the population — every patch
        was cut to the old style's shape. A count change grows or trims each
        band's list in place so the surviving clouds keep their place; drift
        and life reach only clouds born after the change."""
        old = self.config
        self.config = config
        if config.cloud_style != self._baked_style:
            self._bake()
            return
        if config.cloud_count != old.cloud_count:
            for band in GRID_ORDER:
                want = self._target_count(self._style()[band])
                have = self.puffs[band]
                while len(have) < want:
                    have.append(self._spawn(band))
                del have[want:]

    def resize(self, cols: int, sky_rows: int) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        self._bake()

    # ---- time -------------------------------------------------------

    def advance(self, dt: float, wind: float = 0.0) -> None:
        """Every cloud ages and drifts by its own `vx`; one past its life is
        replaced by a newborn at a fresh spot. `wind` is accepted for
        interface parity and ignored: no whole-sky motion here."""
        w = self.width_px
        for band, puffs in self.puffs.items():
            for i, puff in enumerate(puffs):
                puff.age += dt
                if puff.age >= puff.life:
                    puffs[i] = self._spawn(band, age=0.0)
                    continue
                puff.x = (puff.x + puff.vx * dt) % w

    def tick(self, wind: float = 0.0) -> None:
        """Thin wrapper for tests: one frame of `_DEFAULT_DT` wall time."""
        self.advance(_DEFAULT_DT, wind)

    # ---- draw -------------------------------------------------------

    def composite(self) -> tuple[list[list[float]], list[list[str]], list[bool]]:
        """Top-down `density`/`owner` canvases plus a per-pixel-row empty
        flag. Bands stamp far to near, so a nearer cloud overwrites where
        it clears `DENSITY_FLOOR` — the same nearest-first ownership rule
        `_composite` and `_texture_composite` use."""
        W, H = self.width_px, self.height_px
        density = [[0.0] * W for _ in range(H)]
        owner = [[""] * W for _ in range(H)]
        row_empty = [True] * H
        for band in reversed(GRID_ORDER):
            for puff in self.puffs[band]:
                cut = puff.cutoff()
                if cut >= 1.0:
                    continue
                gain = puff.p["gain"]
                blend = puff.blend()
                x0 = int(puff.x)
                pa, pb, win = puff.patch_a, puff.patch_b, puff.window
                for r in range(puff.h):
                    y = puff.y0 + r
                    if y >= H:
                        break
                    drow, orow = density[y], owner[y]
                    ra, rb, wr = pa[r], pb[r], win[r]
                    touched = False
                    for c in range(puff.w):
                        a = ra[c]
                        raw = a + (rb[c] - a) * blend
                        d = (raw - cut) * gain
                        if d <= 0.0:
                            continue
                        d = (1.0 if d > 1.0 else d ** 0.7) * wr[c]
                        if d <= DENSITY_FLOOR:
                            continue
                        x = (x0 + c) % W
                        if d > drow[x] or orow[x] != band:
                            drow[x] = d
                            orow[x] = band
                        touched = True
                    if touched:
                        row_empty[y] = False
        return density, owner, row_empty

    def render_cells(self) -> list[list[tuple[str, str | None]]]:
        if self.cols <= 0 or self.sky_rows <= 0:
            return []
        density, owner, row_empty = self.composite()
        return downsample({}, self.palette, self.sky_rows, self.cols, self.config,
                          density=density, owner=owner, row_empty=row_empty)


SKY_ENGINES: dict[str, type] = {"fluid": Sky, "texture": TextureSky, "puffs": PuffSky}


def make_sky(cols: int, sky_rows: int, rng: random.Random, palette, config: SkyConfig | None = None) -> "Sky | TextureSky | PuffSky":
    """The engine `config.sky_engine` names (`SKY_ENGINES`; `SkyConfig()`'s
    default when `config` is omitted, an unknown name falls back to the
    fluid `Sky`) — the one place that picks, so `field.py` never has to
    know which it got; it reads the class's `ENGINE` tag back instead."""
    engine = (config or SkyConfig()).sky_engine
    cls = SKY_ENGINES.get(engine, Sky)
    return cls(cols, sky_rows, rng, palette, config)
