"""
test_sky.py — the value-noise sky renderer: noise, layers, canvas, downsample.

Responsibilities:
- `Noise.sample` wraps horizontally at the lattice width; `Noise.fbm` stays
  in [0, 1] regardless of input.
- A far layer scrolls slower than a near one, in the documented speed ratio.
- A layer's baked texture is anisotropic — longer horizontal autocorrelation
  than vertical — and periodic (`period_px`), so the scroll wraps with no
  seam: the density row at the far end of one cycle and at the start of the
  next differ only by the ordinary one-pixel scroll.
- `Canvas.composite` never lets a farther layer overwrite a nearer one's
  pixel.
- `downsample` picks blank, a fringe speck, an ordered-dither braille pattern,
  or a solid core by block mean, with a monotonic dot count as density rises,
  and colours a block from its owning layer's band.
- A layer's texture pair morphs into a fresh one every `MORPH_TICKS` ticks;
  morph and the breathing cutoff both change density on their own, without
  scrolling.
"""

from __future__ import annotations

import random

import pytest
from rich.cells import cell_len

from cactus.field import MONO_PLUS
from cactus.sky import (
    _SPECK_GLYPHS,
    BANDS,
    CORE_GLYPH,
    MORPH_TICKS,
    Canvas,
    Layer,
    Noise,
    Sky,
    _ordered_dither,
    atmospheric_colour,
    downsample,
)


def test_noise_wraps_at_lattice_width() -> None:
    noise = Noise(random.Random(1), 6, 6)
    for y in (0, 1.5, 4.0):
        assert noise.sample(0, y) == noise.sample(6, y)


def test_fbm_stays_in_unit_range() -> None:
    noise = Noise(random.Random(2), 9, 9)
    rng = random.Random(3)
    for _ in range(1000):
        x, y = rng.uniform(-50, 50), rng.uniform(-50, 50)
        assert 0.0 <= noise.fbm(x, y, 3) <= 1.0


def test_far_layer_scrolls_slower_than_near() -> None:
    sky = Sky(cols=20, sky_rows=8, rng=random.Random(5), palette=MONO_PLUS)
    for _ in range(100):
        sky.tick()
    far_offset = sky.layers["far"].offset
    near_offset = sky.layers["near"].offset
    assert far_offset < near_offset
    ratio = near_offset / far_offset
    documented = BANDS["near"]["speed"] / BANDS["far"]["speed"]
    assert ratio == pytest.approx(documented)


def test_layer_texture_is_anisotropic_longer_in_x_than_y() -> None:
    """A cirrus layer's baked texture should look "long and thin": neighbours
    along x should be more alike (smaller mean absolute difference) than
    neighbours along y, since scale_x is documented far larger than scale_y."""
    layer = Layer("mid", width_px=60, height_px=40, rng=random.Random(21))
    tex = layer.tex_a

    x_diffs = []
    for row in tex:
        for i in range(len(row) - 1):
            x_diffs.append(abs(row[i + 1] - row[i]))
    mean_x_diff = sum(x_diffs) / len(x_diffs)

    y_diffs = []
    for y in range(len(tex) - 1):
        row_a, row_b = tex[y], tex[y + 1]
        for i in range(min(len(row_a), len(row_b))):
            y_diffs.append(abs(row_b[i] - row_a[i]))
    mean_y_diff = sum(y_diffs) / len(y_diffs)

    assert mean_x_diff < mean_y_diff


def test_texture_scroll_wraps_with_no_seam() -> None:
    """The density row read at the tail of one cycle and the head of the next
    should differ only by the ordinary one-pixel scroll, not jump — the
    texture is baked exactly one period wide and read by plain wraparound."""
    layer = Layer("near", width_px=30, height_px=20, rng=random.Random(9))
    layer.blend = 0.0  # isolate the read window from morph blending

    period = layer.period_px
    for y in range(layer.height_px):
        if layer.envelope[y] < 1e-4:
            continue
        layer.offset = period - 0.5
        row_end = layer.density_row(y)
        layer.offset = 0.5
        row_start = layer.density_row(y)
        # Both windows are read at (effectively) the same integer offset one
        # pixel apart around the wrap point — shifting one against the other
        # by that single pixel should leave them nearly identical.
        diffs = [abs(a - b) for a, b in zip(row_end[1:], row_start[:-1])]
        assert max(diffs) < 0.05


def test_composite_never_lets_a_farther_layer_overwrite_a_nearer_pixel() -> None:
    width_px, height_px = 4, 4
    near = Layer("near", width_px, height_px, random.Random(7))
    mid = Layer("mid", width_px, height_px, random.Random(8))
    # Force both textures dense everywhere so ownership is decided purely by
    # front-to-back order, not by which happens to clear the density floor.
    for layer in (near, mid):
        layer.tex_a = [[1.0] * layer.period_px for _ in range(height_px)]
        layer.tex_b = [[1.0] * layer.period_px for _ in range(height_px)]
        layer.envelope = [1.0] * height_px
        layer.base_cutoff = 0.0
    canvas = Canvas(width_px, height_px)
    canvas.composite([near, mid])
    assert all(v == 0 for row in canvas.layer_id for v in row)


def test_downsample_blank_dither_and_core() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]

    blank = Canvas(2, 4)  # freshly constructed: density is all-zero already
    assert downsample(blank, layers, MONO_PLUS, sky_rows=1)[0][0] == (" ", None)

    faint = Canvas(2, 4)
    faint.density = [[0.1, 0.1], [0.1, 0.1], [0.1, 0.1], [0.1, 0.1]]
    faint.layer_id = [[0, 0], [0, 0], [0, 0], [0, 0]]
    glyph, _ = downsample(faint, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph not in (" ", CORE_GLYPH)  # a dim dithered cell, not blank or full

    full = Canvas(2, 4)
    full.density = [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
    full.layer_id = [[0, 0], [0, 0], [0, 0], [0, 0]]
    glyph, _ = downsample(full, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph == CORE_GLYPH


def test_downsample_mid_density_cell_is_neither_blank_nor_full() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]
    mid = Canvas(2, 4)
    mid.density = [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5], [0.5, 0.5]]
    mid.layer_id = [[0, 0], [0, 0], [0, 0], [0, 0]]
    glyph, _ = downsample(mid, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph not in (" ", CORE_GLYPH)


def test_downsample_fringe_cell_renders_a_speck() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]
    canvas = Canvas(2, 4)
    # One pixel just above the fringe threshold; block mean stays well below
    # BLANK_MEAN.
    canvas.density = [[0.03, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    canvas.layer_id = [[0, -1], [-1, -1], [-1, -1], [-1, -1]]
    glyph, _ = downsample(canvas, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph in _SPECK_GLYPHS


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



def test_colour_follows_the_owning_layers_band() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]
    canvas = Canvas(2, 4)
    canvas.density = [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
    canvas.layer_id = [[2, 2], [2, 2], [2, 2], [2, 2]]  # index 2: "far" in LAYER_ORDER
    _, colour = downsample(canvas, layers, MONO_PLUS, sky_rows=1)[0][0]
    # m = 1.0: the tone-mix-toward-haze term is zero, so full density reads
    # as the plain atmospheric colour.
    expected = atmospheric_colour(MONO_PLUS.cloud_far, layers[2].depth, 0, 1, MONO_PLUS)
    assert colour == expected


def test_layer_morphs_tex_a_into_the_former_tex_b() -> None:
    layer = Layer("near", 4, 4, random.Random(11), stagger=0.0)
    former_b = layer.tex_b
    for _ in range(int(MORPH_TICKS)):
        layer.tick()
    assert layer.tex_a == former_b


def test_morph_and_breath_change_density_without_scrolling() -> None:
    layer = Layer("mid", 8, 4, random.Random(13), stagger=0.0)
    layer.speed = 0.0  # isolate morph/breath from scrolling
    # A cutoff mid-range of the raw fbm's spread guarantees the blend and the
    # breathing cutoff both cross it somewhere over the run below, rather
    # than depending on this seed's fbm values happening to reach the
    # (otherwise untouched) band cutoff.
    layer.base_cutoff = 0.3
    before = layer.density_row(2)
    changed = False
    for _ in range(300):
        layer.tick()
        if layer.density_row(2) != before:
            changed = True
            break
    assert changed


def test_alphabet_glyphs_are_all_single_cell_width() -> None:
    """Every glyph the sky can draw must be one terminal cell wide in a
    monospace font — a double-width character would desync the field's
    column grid from the canvas it was downsampled from."""
    alphabet = list(" .·˙:∘•-~") + [CORE_GLYPH]
    alphabet += [chr(0x2800 | bits) for bits in range(256)]
    for glyph in alphabet:
        assert cell_len(glyph) == 1, repr(glyph)
