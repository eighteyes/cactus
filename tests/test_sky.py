"""
test_sky.py — the value-noise sky renderer: noise, layers, canvas, downsample.

Responsibilities:
- `Noise.sample` wraps horizontally at the lattice width; `Noise.fbm` stays
  in [0, 1] regardless of input.
- A far layer scrolls slower than a near one, in the documented speed ratio.
- `Canvas.composite` never lets a farther layer overwrite a nearer one's
  pixel.
- `downsample` picks blank, braille (with the documented bit order), or the
  punctuation ramp by block mean, and colours a block from its owning
  layer's band.
- A layer's texture pair morphs into a fresh one every `MORPH_TICKS` ticks;
  morph and the breathing cutoff both change density on their own, without
  scrolling.
"""

from __future__ import annotations

import random

import pytest

from cactus.field import MONO_PLUS
from cactus.sky import (
    BANDS,
    MORPH_TICKS,
    Canvas,
    Layer,
    Noise,
    Sky,
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


def test_composite_never_lets_a_farther_layer_overwrite_a_nearer_pixel() -> None:
    width_px, height_px = 4, 4
    near = Layer("near", width_px, height_px, random.Random(7))
    mid = Layer("mid", width_px, height_px, random.Random(8))
    # Force both textures dense everywhere so ownership is decided purely by
    # front-to-back order, not by which happens to clear the density floor.
    for layer in (near, mid):
        layer.tex_a = [[1.0] * (width_px * 2) for _ in range(height_px)]
        layer.tex_b = [[1.0] * (width_px * 2) for _ in range(height_px)]
        layer.envelope = [1.0] * height_px
        layer.base_cutoff = 0.0
    canvas = Canvas(width_px, height_px)
    canvas.composite([near, mid])
    assert all(v == 0 for row in canvas.layer_id for v in row)


def test_downsample_blank_braille_and_full_ramp() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]

    blank = Canvas(2, 4)  # freshly constructed: density is all-zero already
    assert downsample(blank, layers, MONO_PLUS, sky_rows=1)[0][0] == (" ", None)

    faint = Canvas(2, 4)
    faint.density = [[0.1, 0.1], [0.1, 0.1], [0.1, 0.1], [0.1, 0.1]]
    faint.layer_id = [[0, 0], [0, 0], [0, 0], [0, 0]]
    glyph, _ = downsample(faint, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph == chr(0x2800)  # 0.1 < 0.12 dot threshold: blank braille

    full = Canvas(2, 4)
    full.density = [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
    full.layer_id = [[0, 0], [0, 0], [0, 0], [0, 0]]
    glyph, _ = downsample(full, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph == "@"


def test_braille_bit_order() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]

    # One lit pixel at 0.5: block mean 0.0625 (braille range) and 0.5 > the
    # 0.12 per-pixel dot threshold, so exactly one dot lights.
    top_left = Canvas(2, 4)
    top_left.density = [[0.5, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    top_left.layer_id = [[0, -1], [-1, -1], [-1, -1], [-1, -1]]
    glyph, _ = downsample(top_left, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph == "⠁"

    bottom_right = Canvas(2, 4)
    bottom_right.density = [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.5]]
    bottom_right.layer_id = [[-1, -1], [-1, -1], [-1, -1], [-1, 0]]
    glyph, _ = downsample(bottom_right, layers, MONO_PLUS, sky_rows=1)[0][0]
    assert glyph == "⢀"


def test_colour_follows_the_owning_layers_band() -> None:
    layers = [Layer(name, 2, 4, random.Random(i)) for i, name in enumerate(("near", "mid", "far"))]
    canvas = Canvas(2, 4)
    canvas.density = [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
    canvas.layer_id = [[2, 2], [2, 2], [2, 2], [2, 2]]  # index 2: "far" in LAYER_ORDER
    _, colour = downsample(canvas, layers, MONO_PLUS, sky_rows=1)[0][0]
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
