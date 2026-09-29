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
- `GridConfig`/`SkyConfig`: every tunable constant, per grid and shared,
  as a dataclass rather than a module constant, so it can be loaded from a
  TOML file (`SkyConfig.load`), written back out with a one-line comment per
  key (`SkyConfig.dump`), and swapped live into a running `Sky`
  (`Sky.apply`) without disturbing the grids' drawn bands. Every numeric
  field also carries `step`/`lo`/`hi` in its dataclass metadata, and
  `tuning_fields()` flattens the whole set (far/mid/near/shared) into
  `TuneField` rows for tui.py's `T` overlay.
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
_SPECK_GLYPHS = ". · ˙".split()  # ". · ˙"

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

    def dump(self, path: str | Path | None = None) -> Path:
        """Write the current values to `path` (or `config_path()`), one
        commented line per key, and return the path written."""
        p = Path(path) if path is not None else config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = [
            "# every rate below is per second (v6b); a v6 file's numbers still load,",
            "# but now mean 10x less per frame at the default 0.1s sampling",
            "",
        ]
        for gname in ("far", "mid", "near"):
            lines.append(f"[{gname}]")
            gcfg = getattr(self, gname)
            for f in fields(gcfg):
                v = getattr(gcfg, f.name)
                lines.append(f"{f.name} = {v!r}  # {_GRID_COMMENTS[f.name]}")
            lines.append("")
        lines.append("[shared]")
        for key in _SHARED_COMMENTS:
            v = getattr(self, key)
            lines.append(f"{key} = {v!r}  # {_SHARED_COMMENTS[key]}")
        p.write_text("\n".join(lines) + "\n")
        return p


@dataclass(frozen=True)
class TuneField:
    """One row of `tuning_fields()`: a key's group, name, comment, and its
    nudge `step`/`lo`/`hi` (all `None` for a key with no numeric metadata)."""

    group: str
    name: str
    comment: str
    step: float | int | None
    lo: float | int | None
    hi: float | int | None


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
            ))
    shared_fields = {f.name: f for f in fields(SkyConfig)}
    for name, comment in _SHARED_COMMENTS.items():
        f = shared_fields[name]
        rows.append(TuneField("shared", name, comment, f.metadata.get("step"), f.metadata.get("lo"), f.metadata.get("hi")))
    return rows


def _set_typed(obj, key: str, value, label: str) -> None:
    typ = type(getattr(obj, key))
    try:
        setattr(obj, key, typ(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad value for {label}: {value!r}") from exc


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

    # ---- advance ----------------------------------------------------------

    def advance(self, dt: float, world_wind: float, shear_floor: float, shear_base: float, shear_span: float) -> None:
        wind = world_wind * self.config.wind_scale
        self._advect(wind, shear_floor, shear_base, shear_span, dt)
        self._diffuse(dt)
        self._react(dt)
        self._nucleate(dt)
        self._clamp()

    def tick(self, world_wind: float, shear_floor: float, shear_base: float, shear_span: float) -> None:
        """Thin wrapper for tests: one frame of `_DEFAULT_DT` wall time."""
        self.advance(_DEFAULT_DT, world_wind, shear_floor, shear_base, shear_span)

    def _advect(self, wind: float, shear_floor: float, shear_base: float, shear_span: float, dt: float) -> None:
        h, w = self.height, self.width
        d = self.d
        new_rows = []
        for y in range(h):
            u = wind * (shear_base + shear_span * (1.0 - y / h))
            if abs(u) < shear_floor:
                u = math.copysign(shear_floor, u) if u != 0.0 else shear_floor
            shift = u * dt
            k = math.floor(shift)
            frac = shift - k
            row = d[y]
            i0 = _rotate(row, k + 1)
            i1 = _rotate(row, k)
            new_rows.append([a * frac + b * (1.0 - frac) for a, b in zip(i0, i1)])
        for y in range(h):
            d[y][:] = new_rows[y]

    def _diffuse(self, dt: float) -> None:
        h, w = self.height, self.width
        kx, ky = self.config.kx * dt, self.config.ky * dt
        d = self.d
        new_rows = []
        for y in range(h):
            row = d[y]
            left = _rotate(row, 1)
            right = _rotate(row, -1)
            up = d[y + 1] if y + 1 < h else row
            down = d[y - 1] if y - 1 >= 0 else row
            new_rows.append([
                row[x] + kx * (left[x] + right[x] - 2.0 * row[x]) + ky * (up[x] + down[x] - 2.0 * row[x])
                for x in range(w)
            ])
        for y in range(h):
            d[y][:] = new_rows[y]

    def _react(self, dt: float) -> None:
        g, e = self.config.growth, self.config.evaporation
        uptake, replenish = self.config.uptake, self.config.replenish
        allee = self.config.allee
        env = self.env
        d, m = self.d, self.m
        for y in range(self.height):
            gy = g * env[y]
            drow, mrow = d[y], m[y]
            # Bistable growth: below `allee` the term is negative and a faint
            # wisp thins away; above it a streak grows toward full. `grown`
            # is a rate (per second); `dt` integrates it and the evaporation/
            # uptake/replenish terms alongside it, Euler-style.
            grown = [gy * v * (v - allee) * (1.0 - v) * w for v, w in zip(drow, mrow)]
            drow[:] = [v + dt * (gr - e * v) for v, gr in zip(drow, grown)]
            mrow[:] = [w + dt * (replenish * (1.0 - w) - uptake * max(gr, 0.0)) for w, gr in zip(mrow, grown)]

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

    def _clamp(self) -> None:
        # Below `floor` a pixel snaps to zero: evaporation is exponential and
        # would otherwise leave a faint haze of specks over the whole sky.
        floor = self.config.floor
        for row in self.d:
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


def _cell_colour(cfg: SkyConfig, palette, owner: str, m: float, row_from_bottom: int, sky_rows: int) -> str:
    name = owner or "near"
    tone = m ** cfg.tone_exp
    base = _ramp16(getattr(palette, f"cloud_{name}_dark"), getattr(palette, f"cloud_{name}_light"), tone)
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


def downsample(grids: dict[str, Air], palette, sky_rows: int, cols: int, cfg: SkyConfig) -> list[list[tuple[str, str | None]]]:
    """One `(glyph, colour)` per terminal cell from the grids' composited
    `PX_X x PX_Y` pixel block, top row first."""
    density, owner = _composite(grids)
    density = density[::-1]  # Air is bottom-up; render top-down
    owner = owner[::-1]
    out: list[list[tuple[str, str | None]]] = []
    for row_i in range(sky_rows):
        y0 = row_i * PX_Y
        block_density = density[y0: y0 + PX_Y]
        block_owner = owner[y0: y0 + PX_Y]
        row_from_bottom = (sky_rows - 1) - row_i
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
                colour = _cell_colour(cfg, palette, owner_name, m, row_from_bottom, sky_rows)
                out_row.append((glyph, colour))
                continue
            gx, gy = _gradients(pixels)
            if m >= cfg.core_mean:
                glyph = CORE_GLYPH
            elif m >= cfg.semi_core_mean:
                glyph = CORE_GLYPH if _cell_hash(x0, y0) % 2 == 0 else _ordered_dither(pixels)
            elif abs(gx) > cfg.flat_gx and abs(gy) <= cfg.flat_gy_max and cfg.flat_mean_lo <= m < cfg.flat_mean_hi:
                glyph = "-" if _cell_hash(x0, y0) % 2 == 0 else "~"
            elif m < cfg.edge_mean_hi and abs(gx) > cfg.edge_gx and abs(gy) > cfg.edge_gy:
                glyph = "/" if (gx > 0) == (gy > 0) else "\\"
            else:
                glyph = _ordered_dither(pixels)
            owner_name = _majority_owner(block_owner, x0)
            colour = _cell_colour(cfg, palette, owner_name, m, row_from_bottom, sky_rows)
            out_row.append((glyph, colour))
        out.append(out_row)
    return out


# ---- Sky ----------------------------------------------------------------


class Sky:
    """Owns the three depth grids for one field."""

    def __init__(self, cols: int, sky_rows: int, rng: random.Random, palette, config: SkyConfig | None = None) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        self.rng = rng
        self.palette = palette
        self.config = config or SkyConfig()
        self._bake()

    def _bake(self) -> None:
        width_px = max(self.cols * PX_X, 1)
        height_px = max(self.sky_rows * PX_Y, 1)
        self.grids: dict[str, Air] = {
            name: Air(width_px, height_px, self.rng, getattr(self.config, name), GRID_BAND_REGION[name])
            for name in GRID_ORDER
        }

    def apply(self, config: SkyConfig) -> None:
        """Swap tuning constants into the running grids without resetting
        them — their drawn bands and current weather stay exactly as they
        are; only the live physics/render knobs change."""
        self.config = config
        for name in GRID_ORDER:
            self.grids[name].config = getattr(config, name)

    def resize(self, cols: int, sky_rows: int) -> None:
        self.cols = max(cols, 0)
        self.sky_rows = max(sky_rows, 0)
        width_px = max(self.cols * PX_X, 1)
        height_px = max(self.sky_rows * PX_Y, 1)
        for grid in self.grids.values():
            grid.resize(width_px, height_px)

    def advance(self, dt: float, wind: float = 0.0) -> None:
        cfg = self.config
        for grid in self.grids.values():
            grid.advance(dt, wind, cfg.shear_floor, cfg.shear_base, cfg.shear_span)

    def tick(self, wind: float = 0.0) -> None:
        """Thin wrapper for tests: one frame of `_DEFAULT_DT` wall time."""
        self.advance(_DEFAULT_DT, wind)

    def render_cells(self) -> list[list[tuple[str, str | None]]]:
        if self.cols <= 0 or self.sky_rows <= 0:
            return []
        return downsample(self.grids, self.palette, self.sky_rows, self.cols, self.config)
