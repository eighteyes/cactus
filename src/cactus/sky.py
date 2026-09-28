"""
sky.py — value-noise sky renderer: layered clouds downsampled to glyphs.

Responsibilities:
- Bake two tileable value-noise textures per parallax depth band (far, mid,
  near), each with its own octave count, feature scale, vertical band, and
  scroll speed.
- Scroll each layer's texture independently by depth, and slowly morph it
  from one baked texture toward a fresh one and back (`Sky.tick`), so the
  sky keeps changing shape, not just drifting; and breathe its density
  cutoff on a slower cycle, so clouds swell and thin without a rebake.
- Composite the layers into a density canvas front-to-back, so a nearer
  layer's pixel is never overwritten by one further back
  (`Sky.render_cells`).
- Downsample the canvas, `PX_X` by `PX_Y` pixels per terminal cell, to one
  glyph — blank, a braille dot pattern, a slanted edge stroke, or a
  punctuation-ramp character — plus a colour shifted toward `palette.haze`
  by depth and by height (atmospheric perspective).
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

DENSITY_FLOOR = 0.05  # below this a pixel has no owning layer
BLANK_MEAN = 0.04  # block mean below this renders as blank space
BRAILLE_MEAN = 0.30  # block mean below this (and above BLANK_MEAN) is braille
BRAILLE_DOT = 0.12  # per-pixel threshold for a lit braille dot
EDGE_MEAN_HI = 0.65  # edge strokes are only tried below this block mean
EDGE_GX = 0.15
EDGE_GY = 0.10

RAMP = ". : ; ~ = + * o O @".split()

# Kept in step with field.TICK_SECONDS by convention, not import (see module
# docstring) — the morph/breath cycles below are expressed in seconds only
# to read naturally; nothing here depends on field.py.
TICK_SECONDS = 0.1
MORPH_SECONDS = 120.0  # a layer's texture fully morphs into a fresh one
BREATH_SECONDS = 90.0  # the cutoff's swell/thin cycle
MORPH_TICKS = MORPH_SECONDS / TICK_SECONDS
BREATH_TICKS = BREATH_SECONDS / TICK_SECONDS
BREATH_AMPLITUDE = 0.06

# depth (for colour), octave count, feature scale in px, the fbm cutoff and
# post-cutoff gain that shape density, the vertical band as a (lo, hi)
# fraction of sky height from the top, the scroll speed in px/tick, and this
# layer's stagger in [0, 1) — its starting point on both the morph cycle
# (`blend`) and the breath cycle (as a phase fraction), so the three layers
# never morph-rebake or crest together.
BANDS = {
    "far": dict(depth=0.9, octaves=3, scale_px=8, cutoff=0.62, gain=3.0, band=(0.0, 0.4), speed=0.02, stagger=0.0),
    "mid": dict(depth=0.6, octaves=3, scale_px=14, cutoff=0.58, gain=2.5, band=(0.2, 0.8), speed=0.06, stagger=0.33),
    "near": dict(depth=0.2, octaves=2, scale_px=24, cutoff=0.54, gain=2.0, band=(0.3, 1.0), speed=0.15, stagger=0.66),
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


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _smoothstep(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _envelope(frac: float, lo: float, hi: float, soft: float = 0.08) -> float:
    """Smooth 1 inside [lo, hi], 0 outside, with a `soft`-wide eased edge."""
    if frac < lo - soft or frac > hi + soft:
        return 0.0
    if frac < lo:
        return _smoothstep((frac - (lo - soft)) / soft)
    if frac > hi:
        return _smoothstep((hi + soft - frac) / soft)
    return 1.0


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


class Layer:
    """One depth band's pair of baked, scrolling, morphing raw-fbm textures.

    `tex_a`/`tex_b` hold raw fbm values in [0, 1] — no cutoff, gain, or
    envelope baked in, so the cutoff can breathe at composite time for free.
    Each is baked `2 * width_px` wide so a `width_px`-wide read window,
    starting anywhere `offset` (itself wrapped at `width_px`) can reach,
    never runs past the array — no per-pixel wrap, and no seam, since the
    tex's own far edge (index `2 * width_px - 1`) is never read.
    """

    def __init__(self, band: str, width_px: int, height_px: int, rng: random.Random, stagger: float | None = None) -> None:
        p = BANDS[band]
        self.band = band
        self.depth = p["depth"]
        self.width_px = width_px
        self.height_px = height_px
        self.speed = p["speed"]
        self.offset = 0.0
        self.rng = rng

        self.scale_px = p["scale_px"]
        self.octaves = p["octaves"]
        self.base_cutoff = p["cutoff"]
        self.gain = p["gain"]
        lo, hi = p["band"]
        stagger = p["stagger"] if stagger is None else stagger
        self.blend = stagger
        self.breath_phase = 2.0 * math.pi * stagger
        self._tick = 0

        y_span = max(height_px - 1, 1)
        self.envelope = [_envelope(y / y_span, lo, hi) for y in range(height_px)]

        self.tex_a = self._bake_raw()
        self.tex_b = self._bake_raw()

    def _bake_raw(self) -> list[list[float]]:
        """Bake one fresh raw-fbm texture, tileable across `2 * width_px`."""
        tex_width = self.width_px * 2
        scale_px = self.scale_px
        lattice_w = max(3, round(tex_width / scale_px))
        lattice_h = max(3, round(self.height_px / scale_px) + 2)
        noise = Noise(self.rng, lattice_w, lattice_h)

        tex: list[list[float]] = []
        for y in range(self.height_px):
            if self.envelope[y] <= 0.0:
                # Zero envelope means composite always multiplies this row to
                # 0 regardless of fbm value or cutoff — skip the fbm work.
                tex.append([0.0] * tex_width)
                continue
            ys = y / scale_px
            tex.append([noise.fbm(x / scale_px, ys, self.octaves) for x in range(tex_width)])
        return tex

    def tick(self) -> None:
        self._tick += 1
        self.offset = (self.offset + self.speed) % self.width_px
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
        (breathing) cutoff and gain, clamp, then the row's envelope."""
        env = self.envelope[y]
        if env <= 0.0:
            return [0.0] * self.width_px
        off = int(self.offset)
        w = self.width_px
        row_a = self.tex_a[y][off: off + w]
        row_b = self.tex_b[y][off: off + w]
        blend = self.blend
        cut = self._effective_cutoff()
        gain = self.gain
        return [
            env * (0.0 if (d := (a + (b - a) * blend - cut) * gain) < 0.0 else (1.0 if d > 1.0 else d))
            for a, b in zip(row_a, row_b)
        ]


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


def _braille(pixels: list[list[float]]) -> str:
    bits = 0
    for row in range(PX_Y):
        for col in range(PX_X):
            if pixels[row][col] > BRAILLE_DOT:
                bits |= 1 << _BRAILLE_BIT[(col, row)]
    return chr(0x2800 | bits)


def _edge_stroke(pixels: list[list[float]]) -> str | None:
    left = (pixels[0][0] + pixels[1][0] + pixels[2][0] + pixels[3][0]) / 4.0
    right = (pixels[0][1] + pixels[1][1] + pixels[2][1] + pixels[3][1]) / 4.0
    top = sum(pixels[0]) / 2.0 + sum(pixels[1]) / 2.0
    bottom = sum(pixels[2]) / 2.0 + sum(pixels[3]) / 2.0
    gx = right - left
    gy = (top / 2.0) - (bottom / 2.0)
    if abs(gx) > EDGE_GX and abs(gy) > EDGE_GY:
        return "/" if (gx > 0) == (gy > 0) else "\\"
    return None


def downsample(canvas: Canvas, layers: list[Layer], palette, sky_rows: int) -> list[list[tuple[str, str | None]]]:
    """One `(glyph, colour)` per terminal cell from its `PX_X x PX_Y` block.

    `layers` must be the same front-to-back list `Canvas.composite` used, so
    a block's owning index resolves to the right band's depth and colour.
    """
    cols = canvas.width_px // PX_X
    grid: list[list[tuple[str, str | None]]] = []
    for gy in range(sky_rows):
        y0 = gy * PX_Y
        block_rows = canvas.density[y0: y0 + PX_Y]
        id_rows = canvas.layer_id[y0: y0 + PX_Y]
        row_from_bottom = (sky_rows - 1) - gy
        out_row: list[tuple[str, str | None]] = []
        for gx in range(cols):
            x0 = gx * PX_X
            pixels = [r[x0: x0 + PX_X] for r in block_rows]
            m = sum(v for row in pixels for v in row) / 8.0
            if m < BLANK_MEAN:
                out_row.append((" ", None))
                continue
            owner = _majority_layer(id_rows, x0)
            layer = layers[owner] if owner != -1 else layers[0]
            colour = atmospheric_colour(getattr(palette, f"cloud_{layer.band}"), layer.depth, row_from_bottom, sky_rows, palette)
            if m < BRAILLE_MEAN:
                out_row.append((_braille(pixels), colour))
                continue
            glyph = None
            if m < EDGE_MEAN_HI:
                glyph = _edge_stroke(pixels)
            if glyph is None:
                index = int(m * (len(RAMP) - 1))
                glyph = RAMP[index]
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
