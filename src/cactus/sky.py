"""
sky.py — value-noise sky renderer: cirrus clouds downsampled to toned glyphs.

Responsibilities:
- Bake two tileable, anisotropic value-noise textures per parallax depth band
  (far, mid, near) — each sampled far wider in x than in y so features read
  as long, thin streaks (cirrus), not blobs — with its own octave count,
  scroll speed, and a per-layer vertical shape: a shared bell envelope
  bunched a little above mid-height, times a thin horizontal comb so streaks
  stack in bands rather than filling one wide layer.
- Bake each texture exactly one lattice-period wide (`Layer.period_px`), so
  scrolling wraps by plain modulo indexing with no seam — the old
  double-width-then-snap trick is gone.
- Scroll each layer's texture independently by depth, and slowly morph it
  from one baked texture toward a fresh one and back (`Sky.tick`), so the
  sky keeps changing shape, not just drifting; and breathe its density
  cutoff on a slower cycle, so clouds swell and thin without a rebake.
- Composite the layers into a density canvas front-to-back, so a nearer
  layer's pixel is never overwritten by one further back
  (`Sky.render_cells`).
- Downsample the canvas, `PX_X` by `PX_Y` pixels per terminal cell, to one
  toned glyph: blank, a fringe speck, an ordered-dither braille pattern (nine
  visible tones per cell via a 2x4 Bayer matrix), a flat cirrus stroke, a
  tapering edge stroke, or a solid core — plus a colour shifted toward
  `palette.haze` by depth, by height, and by the cell's own density, so thin
  fringes read dimmer than dense cores in the same cloud (`downsample`).
- Stay pure Python (no numpy) and free of Textual or store imports; `field.py`
  is the only caller, and it duck-types `palette` (no import of its type here,
  to avoid a cycle). Keeps its own `TICK_SECONDS`, matching field.py's, so its
  morph/breath cycles read in real seconds without importing field.py.
"""

from __future__ import annotations

import math
import random

PX_X = 2  # pixels per terminal cell, horizontal (braille dot geometry)
PX_Y = 4  # pixels per terminal cell, vertical

# Compositing ownership floor and the fringe-speck peak threshold are the
# same number by design: a pixel the canvas ever zeroes out for compositing
# is exactly a pixel too faint to earn even a speck (v5 plan §1, "below that,
# nothing").
DENSITY_FLOOR = 0.02
BLANK_MEAN = 0.10
CORE_MEAN = 0.92  # block mean at or above this is a solid core
SEMI_CORE_MEAN = 0.80  # [SEMI_CORE_MEAN, CORE_MEAN) alternates core/dither
FLAT_GX = 0.15  # a flat cirrus stroke needs a horizontal gradient at least this strong
FLAT_GY_MAX = 0.10  # ...and a vertical gradient no stronger than this
FLAT_MEAN_LO = 0.25
FLAT_MEAN_HI = 0.70
EDGE_MEAN_HI = 0.65  # tapering-tip edge strokes are only tried below this block mean
EDGE_GX = 0.15
EDGE_GY = 0.10

CORE_GLYPH = "⣿"  # "⣿" — all eight braille dots, same bits an all-lit dither gives
_SPECK_GLYPHS = ". · ˙".split()  # ". · ˙"

# Kept in step with field.TICK_SECONDS by convention, not import (see module
# docstring) — the morph/breath cycles below are expressed in seconds only
# to read naturally; nothing here depends on field.py.
TICK_SECONDS = 0.1
MORPH_SECONDS = 120.0  # a layer's texture fully morphs into a fresh one
BREATH_SECONDS = 90.0  # the cutoff's swell/thin cycle
MORPH_TICKS = MORPH_SECONDS / TICK_SECONDS
BREATH_TICKS = BREATH_SECONDS / TICK_SECONDS
BREATH_AMPLITUDE = 0.06

# depth (for colour), octave count, the anisotropic feature scale — `scale_x`
# in terminal cells, `scale_y` in pixel rows, deliberately very different so
# fbm reads long and thin (cirrus, not blobs) — the fbm cutoff and post-cutoff
# gain that shape density, the scroll speed in px/tick, this layer's stagger
# in [0, 1) (its starting point on both the morph cycle and the breath cycle,
# so the three layers never morph-rebake or crest together), and the vertical
# comb's period in pixel rows (far/mid/near stack thinner streaks nearer).
BANDS = {
    "far": dict(depth=0.9, octaves=3, scale_x=40, scale_y=3, cutoff=0.55, gain=3.5, speed=0.02, stagger=0.0, comb_period=6),
    "mid": dict(depth=0.6, octaves=3, scale_x=28, scale_y=4, cutoff=0.51, gain=3.2, speed=0.05, stagger=0.33, comb_period=8),
    "near": dict(depth=0.2, octaves=2, scale_x=18, scale_y=6, cutoff=0.48, gain=3.0, speed=0.10, stagger=0.66, comb_period=10),
}
# Compositing and colour-tiebreak order: front (nearest) to back.
LAYER_ORDER = ("near", "mid", "far")
# Braille dot bit for each (col, row) position in a PX_X x PX_Y block,
# standard braille bit order: col 0 is bits 0,1,2,6 top to bottom, col 1 is
# bits 3,4,5,7 top to bottom.
_BRAILLE_BIT = {
    (0, 0): 0, (0, 1): 1, (0, 2): 2, (0, 3): 6,
    (1, 0): 3, (1, 1): 4, (1, 2): 5, (1, 3): 7,
}
# 2x4 ordered (Bayer) dither matrix, one fixed threshold per dot position in
# a cell, so a cell's tone (0-8 lit dots) reads as a stable spatial pattern
# rather than every dot snapping on together at one density.
_BAYER = ((0, 4), (6, 2), (1, 5), (7, 3))
_BAYER_THRESHOLD = tuple(tuple(v / 8.0 + 1.0 / 16.0 for v in row) for row in _BAYER)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _smoothstep(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _lerp_hex(a: str, b: str, t: float) -> str:
    """Mix two `#rrggbb` strings per channel; `t=0` is `a`, `t=1` is `b`."""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    c = round(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{c:02x}"


def atmospheric_colour(band_colour: str, depth: float, row: int, sky_rows: int, palette) -> str:
    """Shift `band_colour` toward `palette.haze` by depth and by height.

    `row` is 0 at the bottom of the sky and `sky_rows - 1` at the top, so a
    colour fades further toward the haze the higher and the further back it
    sits. Shared by the downsampler's cloud cells and, at a fixed depth of
    0.5, by a bird at its own row.
    """
    denom = sky_rows - 1 if sky_rows > 1 else 1
    t = 0.55 * depth + 0.30 * (row / denom)
    return _lerp_hex(band_colour, palette.haze, _clamp(t, 0.0, 0.85))


class Noise:
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


def _read_window(row: list[float], off: int, w: int, period: int) -> list[float]:
    """`w` values starting at `off`, wrapping at `period` — the seamless scroll."""
    end = off + w
    if end <= period:
        return row[off:end]
    return row[off:period] + row[0:end - period]


class Layer:
    """One depth band's pair of baked, scrolling, morphing raw-fbm textures.

    `tex_a`/`tex_b` hold raw fbm values in [0, 1] — no cutoff, gain, or
    envelope baked in, so the cutoff can breathe at composite time for free.
    Each is baked exactly `period_px` wide, one full period of the lattice
    noise in x (`Noise.sample` already wraps at the lattice width), chosen
    `>= 2 * width_px` — so a `width_px`-wide read window can start anywhere
    `offset` (itself wrapped at `period_px`) reaches and wrap by plain modulo
    indexing (`_read_window`) with no seam, unlike a double-width bake that
    has to snap the visible window back once per cycle.
    """

    def __init__(self, band: str, width_px: int, height_px: int, rng: random.Random, stagger: float | None = None) -> None:
        p = BANDS[band]
        self.band = band
        self.depth = p["depth"]
        self.width_px = width_px
        self.height_px = height_px
        self.speed = p["speed"]
        self.rng = rng

        # scale_x is documented in terminal cells (anisotropic: far wider in
        # x than in y so features read as long, thin streaks); scale_y is
        # already in pixel rows.
        self.scale_x_px = p["scale_x"] * PX_X
        self.scale_y_px = p["scale_y"]
        self.octaves = p["octaves"]
        self.base_cutoff = p["cutoff"]
        self.gain = p["gain"]
        self.comb_period = p["comb_period"]
        self.comb_phase = rng.uniform(0.0, 2.0 * math.pi)

        stagger = p["stagger"] if stagger is None else stagger
        self.blend = stagger
        self.breath_phase = 2.0 * math.pi * stagger
        self._tick = 0

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
        self.tex_a = self._bake_raw()
        self.tex_b = self._bake_raw()

    def _comb(self, y: int) -> float:
        phase = 2.0 * math.pi * y / self.comb_period + self.comb_phase
        return 0.8 + 0.2 * (0.5 + 0.5 * math.cos(phase))

    def _bake_raw(self) -> list[list[float]]:
        """Bake one fresh raw-fbm texture, exactly `period_px` wide and
        periodic by construction — `Noise.sample` wraps at `lattice_w`, and
        `period_px` is a whole multiple of it."""
        noise = Noise(self.rng, self.lattice_w, self.lattice_h)
        tex: list[list[float]] = []
        for y in range(self.height_px):
            if self.envelope[y] < 1e-4:
                # Zero envelope means composite always multiplies this row to
                # 0 regardless of fbm value or cutoff — skip the fbm work.
                tex.append([0.0] * self.period_px)
                continue
            ys = y / self.scale_y_px
            tex.append([
                noise.fbm(x / self.scale_x_px, ys, self.octaves)
                for x in range(self.period_px)
            ])
        return tex

    def tick(self) -> None:
        self._tick += 1
        self.offset = (self.offset + self.speed) % self.period_px
        self.blend += 1.0 / MORPH_TICKS
        if self.blend >= 1.0:
            self.blend = 0.0
            self.tex_a = self.tex_b
            self.tex_b = self._bake_raw()

    def _effective_cutoff(self) -> float:
        phase = 2.0 * math.pi * self._tick / BREATH_TICKS + self.breath_phase
        return self.base_cutoff + BREATH_AMPLITUDE * math.sin(phase)

    def density_row(self, y: int) -> list[float]:
        """This layer's composited density for row `y`, `width_px` wide,
        already windowed by `offset`: blend the two textures, apply the
        (breathing) cutoff and gain with a `** 0.7` curve so a cloud's fringe
        spends many pixels between faint and solid instead of snapping, then
        the row's envelope."""
        env = self.envelope[y]
        if env < 1e-4:
            return [0.0] * self.width_px
        off = int(self.offset)
        w = self.width_px
        period = self.period_px
        row_a = _read_window(self.tex_a[y], off, w, period)
        row_b = _read_window(self.tex_b[y], off, w, period)
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


class Canvas:
    """Per-pixel density and owning-layer-index, rebuilt fresh every composite."""

    def __init__(self, width_px: int, height_px: int) -> None:
        self.width_px = width_px
        self.height_px = height_px
        self.density: list[list[float]] = [[0.0] * width_px for _ in range(height_px)]
        self.layer_id: list[list[int]] = [[-1] * width_px for _ in range(height_px)]

    def composite(self, layers: list[Layer]) -> None:
        """Rebuild from scratch, `layers[0]` (nearest) to last (farthest);
        a pixel already claimed by an earlier layer is not overwritten."""
        w = self.width_px
        for y in range(self.height_px):
            rows = [layer.density_row(y) for layer in layers]
            owned_row = self.layer_id[y]
            dens_row = self.density[y]
            for x in range(w):
                owner = -1
                value = 0.0
                for idx, row in enumerate(rows):
                    v = row[x]
                    if v > DENSITY_FLOOR:
                        owner = idx
                        value = v
                        break
                owned_row[x] = owner
                dens_row[x] = value


def _majority_layer(id_rows: list[list[int]], x0: int) -> int:
    """The block's most-common owning layer, ties broken toward the nearest
    (lowest index, since layers are ordered front to back)."""
    counts: dict[int, int] = {}
    for row in id_rows:
        for v in row[x0: x0 + PX_X]:
            if v != -1:
                counts[v] = counts.get(v, 0) + 1
    if not counts:
        return -1
    best_idx, best_count = -1, -1
    for idx in sorted(counts):
        if counts[idx] > best_count:
            best_idx, best_count = idx, counts[idx]
    return best_idx


def _ordered_dither(pixels: list[list[float]]) -> str:
    """A braille glyph from per-pixel density against the fixed Bayer
    thresholds — nine visible tones per cell (0-8 lit dots) with a stable
    spatial pattern; the scroll moves the pattern along with the cloud."""
    bits = 0
    for row in range(PX_Y):
        for col in range(PX_X):
            if pixels[row][col] > _BAYER_THRESHOLD[row][col]:
                bits |= 1 << _BRAILLE_BIT[(col, row)]
    return chr(0x2800 | bits)


def _gradients(pixels: list[list[float]]) -> tuple[float, float]:
    left = (pixels[0][0] + pixels[1][0] + pixels[2][0] + pixels[3][0]) / 4.0
    right = (pixels[0][1] + pixels[1][1] + pixels[2][1] + pixels[3][1]) / 4.0
    top = sum(pixels[0]) / 2.0 + sum(pixels[1]) / 2.0
    bottom = sum(pixels[2]) / 2.0 + sum(pixels[3]) / 2.0
    return right - left, (top / 2.0) - (bottom / 2.0)


def _cell_hash(x0: int, y0: int) -> int:
    """A cheap, deterministic per-cell hash — stable for a given pixel
    position, so it reads as a fixed spatial pattern that scrolls with the
    windowed canvas rather than flickering frame to frame."""
    h = (x0 * 374761393 + y0 * 668265263) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h & 0x7FFFFFFF


def _speck_glyph(x0: int, y0: int) -> str:
    return _SPECK_GLYPHS[_cell_hash(x0, y0) % len(_SPECK_GLYPHS)]


def _cell_colour(
    id_rows: list[list[int]], x0: int, layers: list[Layer], palette,
    row_from_bottom: int, sky_rows: int, m: float,
) -> str:
    """A cell's colour: atmospheric shift by the owning layer's depth and
    height, then a further mix toward haze by the cell's own density — a
    thin fringe reads dimmer than a dense core in the same cloud."""
    owner = _majority_layer(id_rows, x0)
    layer = layers[owner] if owner != -1 else layers[0]
    colour = atmospheric_colour(
        getattr(palette, f"cloud_{layer.band}"), layer.depth, row_from_bottom, sky_rows, palette,
    )
    return _lerp_hex(colour, palette.haze, _clamp((1.0 - m) * 0.35, 0.0, 1.0))


def downsample(canvas: Canvas, layers: list[Layer], palette, sky_rows: int) -> list[list[tuple[str, str | None]]]:
    """One `(glyph, colour)` per terminal cell from its `PX_X x PX_Y` block.

    `layers` must be the same front-to-back list `Canvas.composite` used, so
    a block's owning index resolves to the right band's depth and colour.
    """
    cols = canvas.width_px // PX_X
    grid: list[list[tuple[str, str | None]]] = []
    for row_i in range(sky_rows):
        y0 = row_i * PX_Y
        block_rows = canvas.density[y0: y0 + PX_Y]
        id_rows = canvas.layer_id[y0: y0 + PX_Y]
        row_from_bottom = (sky_rows - 1) - row_i
        out_row: list[tuple[str, str | None]] = []
        for col_i in range(cols):
            x0 = col_i * PX_X
            pixels = [r[x0: x0 + PX_X] for r in block_rows]
            flat = [v for prow in pixels for v in prow]
            m = sum(flat) / 8.0
            if m < BLANK_MEAN:
                peak = max(flat)
                if peak <= DENSITY_FLOOR or _cell_hash(x0, y0) % 3:
                    out_row.append((" ", None))
                    continue
                glyph = _speck_glyph(x0, y0)
                colour = _cell_colour(id_rows, x0, layers, palette, row_from_bottom, sky_rows, m)
                out_row.append((glyph, colour))
                continue
            gx, gy = _gradients(pixels)
            if m >= CORE_MEAN:
                glyph = CORE_GLYPH
            elif m >= SEMI_CORE_MEAN:
                glyph = CORE_GLYPH if _cell_hash(x0, y0) % 2 == 0 else _ordered_dither(pixels)
            elif abs(gx) > FLAT_GX and abs(gy) <= FLAT_GY_MAX and FLAT_MEAN_LO <= m < FLAT_MEAN_HI:
                glyph = "-" if _cell_hash(x0, y0) % 2 == 0 else "~"
            elif m < EDGE_MEAN_HI and abs(gx) > EDGE_GX and abs(gy) > EDGE_GY:
                glyph = "/" if (gx > 0) == (gy > 0) else "\\"
            else:
                glyph = _ordered_dither(pixels)
            colour = _cell_colour(id_rows, x0, layers, palette, row_from_bottom, sky_rows, m)
            out_row.append((glyph, colour))
        grid.append(out_row)
    return grid


class Sky:
    """Owns the three depth layers and the density canvas for one field."""

    def __init__(self, cols: int, sky_rows: int, rng: random.Random, palette) -> None:
        self.cols = cols
        self.sky_rows = max(sky_rows, 0)
        self.rng = rng
        self.palette = palette
        self._bake()

    def _bake(self) -> None:
        width_px = self.cols * PX_X
        height_px = self.sky_rows * PX_Y
        self.canvas = Canvas(width_px, height_px)
        self.layers = {name: Layer(name, width_px, height_px, self.rng) for name in LAYER_ORDER}

    def resize(self, cols: int, sky_rows: int) -> None:
        self.cols = cols
        self.sky_rows = max(sky_rows, 0)
        self._bake()

    def tick(self) -> None:
        for layer in self.layers.values():
            layer.tick()

    def render_cells(self) -> list[list[tuple[str, str | None]]]:
        if self.cols <= 0 or self.sky_rows <= 0:
            return []
        ordered = [self.layers[name] for name in LAYER_ORDER]
        self.canvas.composite(ordered)
        return downsample(self.canvas, ordered, self.palette, self.sky_rows)
