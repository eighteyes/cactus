"""
field.py — the answer strip's background simulation: sky, weather, cacti.

Responsibilities:
- Hold a small world (a noise-rendered parallax sky, wind, bird flocks, ground
  speckle, and the settled cactus structure) in sub-cell resolution, two
  sub-cells per terminal cell in each axis.
- Advance the world by `dt` wall-clock seconds (`World.advance`; `tick()` is a
  thin wrapper for tests, `advance(TICK_SECONDS)`): advance the sky's three
  cellular-automaton air grids (passing this frame's wind for their parallax
  drift), integrate the wind's Ornstein-Uhlenbeck walk, fly and despawn
  flocks (and lone birds) at one of the sky's three depths, and fall seeds
  under gravity and wind until they anchor. Every rate is per second, scaled
  by `dt` at the call site — nothing steps once per tick or once per second.
- Drop a seed into a column; anchor it to the floor or beside the structure,
  including the two "reverse pawn" diagonals below it. Count every drop, so
  the structure can carry age in decisions rather than in time.
- Hold the colour palette (`Palette`, default `MONO_PLUS`): each sky grid's
  dark/light tone-ramp pair, the haze colour clouds fade toward, cactus age
  bands, seed, bird, and sand-speckle colours. No sky background anywhere —
  shade comes only from glyph colour.
- Render the world as a styled rich.text.Text: the settled structure is, by
  default (`SkyConfig.pile_style == "blocks"`), quadrant-sampled from its
  four sub-cells (block glyphs); under `pile_style == "dots"` (v6d) each
  landed sub-cell is instead splatted as a small round Gaussian into the
  same per-frame braille-pixel canvas mechanism a falling seed's footprint
  uses, then dithered — a soft dotted heap in the same age colours. A
  falling seed is always splatted as a tiny tumbling Gaussian footprint into
  its own per-frame canvas and dithered through the same Bayer pattern as
  the sky, so its silhouette antialiases and changes as it spins, and always
  wins over sky and structure. The sky is `Sky.render_cells()`'s braille/
  punctuation/stroke glyphs; birds and ground speckle render as single ASCII
  glyphs.

Pure Python: no persistence, no store, no Textual import.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from rich.text import Text

from .sky import PX_X, PX_Y, Sky, atmospheric_colour, _ordered_dither

SUB_X = 2
SUB_Y = 2
GROUND_ROWS = 2  # terminal rows of flat ground
QUADRANT = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"

# Pacing, not physics (q: "less video gamey, a seed takes 1 min to land"):
# `TICK_SECONDS` is only the sampling period `tick()` stands in for in tests
# and the TUI's default timer interval — every rate below is per second of
# wall-clock time, integrated by `World.advance(dt)` for whatever `dt` the
# caller passes. `World.terminal_vy` derives the fall speed a seed settles
# into from `LANDING_SECONDS` plus its own sky height, so the drop still
# takes about a minute regardless of the field's size or the sampling rate.
TICK_SECONDS = 0.1
LANDING_SECONDS = 60.0
GRAVITY = 0.2  # sub-cells/s^2: reaches terminal velocity within a couple of seconds
WIND_COUPLING = 0.003  # how much wind nudges a falling seed's vx, per second
SEED_DRAG_THETA = -math.log(0.98) / TICK_SECONDS  # per second: seed vx's exponential decay rate
# Wind's Ornstein-Uhlenbeck process: THETA is the mean-reversion rate and
# SIGMA the noise scale, chosen so `advance(TICK_SECONDS)` reproduces v6's
# tuned per-tick feel (an innovation of gauss(0, 0.02) then a 0.995 decay)
# exactly, while `advance(dt)` at any other `dt` stays low-passed and never
# jumps: `wind += SIGMA * sqrt(dt) * gauss(0, 1)`, clamped, `*= exp(-THETA*dt)`.
WIND_SIGMA = 0.02 / math.sqrt(TICK_SECONDS)  # per sqrt(second)
WIND_THETA = -math.log(0.995) / TICK_SECONDS  # per second
WIND_BOUND = 0.6

# structure age bands, counted in `World.drops` (decisions), not ticks
CACTUS_NEW_MAX = 34
CACTUS_MID_MAX = 100

# Flocks (q: "needs more birds too, flocks of birds"). Each flock is spawned
# at one of the sky's three depth bands, sharing that band's speed, colour
# shift, and glyph set with the parallax sky itself. A "flock" with zero
# followers is a lone bird. Every rate below is per second; `advance(dt)`
# scales a probability as `p_per_second * dt` and a distance as `rate * dt`.
FLOCK_MAX_ALIVE = 3
FLOCK_SPAWN_P = 0.02  # per second, while fewer than FLOCK_MAX_ALIVE are alive
LONE_BIRD_P = 0.25  # of spawns, a lone bird instead of a flock
FLOCK_FOLLOWERS = (4, 12)  # inclusive range
GLIDE_P = 0.125  # 1 in 8 birds glides instead of flapping
JITTER_STEP = 0.5  # sub-cells/s, a follower's wander around its rank slot
JITTER_CLAMP = 0.6
SPACING_Y = (0.4, 0.8)  # sub-cells, vertical rank spacing, every depth
DEPTH_BAND = {"far": 0.9, "mid": 0.6, "near": 0.2}  # matches sky.GRID_DEPTH
DEPTH_SPEED = {"far": 0.8, "mid": 1.5, "near": 2.5}  # sub-cells/s
DEPTH_SPACING_X = {"far": (1.0, 1.5), "mid": (1.5, 2.5), "near": (2.5, 3.5)}
# Wing-beat: a bird's `phase` is a float in seconds, advanced by dt every
# frame — never a per-tick counter. A half beat (down to up, or back) takes
# `WING_HALF_CYCLE_SECONDS`; the glyph comes from `floor(phase / half_cycle)`,
# so it reads straight off the continuous phase, not a modulo'd counter.
WING_HALF_CYCLE_SECONDS = 0.4

# (down-beat, up-beat, gliding) glyphs; "near" spans 3 cells, (left, centre, right).
DEPTH_GLYPHS = {
    "far": (".", "'", ","),
    "mid": ("v", "^", "~"),
    "near": ("\\_/", "/^\\", "~~~"),
}

# The falling seed's tumble: `angle` advances by `spin` (radians/second, a
# random 1-3 magnitude and sign, drawn once at drop) plus a slow wobble tied
# to the current wind, so two seeds never tumble in lockstep and the wind's
# own gusts show up in how they spin.
SEED_SPIN_RANGE = (1.0, 3.0)  # rad/s magnitude
SEED_WOBBLE_PER_WIND = 0.5  # rad/s added per unit of wind
# The seed's antialiased footprint: an ellipse (long axis `SEED_SIGMA_A`,
# short `SEED_SIGMA_B` pixels) splatted into a per-frame braille-pixel canvas
# and dithered exactly like a cloud cell. `SEED_SPLAT_RADIUS_PX` bounds how
# far from centre a splat is even considered; `SEED_SPLAT_FLOOR` is the
# density below which a pixel is not worth adding to the canvas.
SEED_SIGMA_A = 1.6
SEED_SIGMA_B = 1.0
SEED_SPLAT_RADIUS_PX = 5
SEED_SPLAT_FLOOR = 0.02

# A landed pile cell's splat under `pile_style == "dots"` (v6d): round (no
# tumble, so a single sigma for both axes) and smaller than a falling seed's.
PILE_SPLAT_SIGMA = 1.2
PILE_SPLAT_RADIUS_PX = 3


@dataclass(frozen=True)
class Palette:
    """Colours for the field. `MONO_PLUS`: mono-plus — no backgrounds, only
    depth-shaded clouds and age-shaded cacti."""

    cloud_far_dark: str = "#4e5668"
    cloud_far_light: str = "#aab0c0"
    cloud_mid_dark: str = "#5c6478"
    cloud_mid_light: str = "#d0ccc0"
    cloud_near_dark: str = "#6a6e7c"
    cloud_near_light: str = "#f0ebdc"
    haze: str = "#3a4256"
    bird: str = "#d0d4de"
    seed: str = "#b8ff9a"
    cactus_new: str = "#7ee07e"
    cactus_mid: str = "#3fae3f"
    cactus_old: str = "#2a7a2a"
    sand_dot: str = "grey42"


MONO_PLUS = Palette()


@dataclass
class Seed:
    x: float
    y: float
    vx: float
    vy: float
    nudged: bool = False
    angle: float = 0.0  # radians, the tumble a Gaussian splat is rotated by
    spin: float = 0.0  # radians/second, drawn once at drop; see SEED_SPIN_RANGE


@dataclass
class Bird:
    x: float
    y: float
    vx: float
    band: str = "mid"  # "far" / "mid" / "near" — matches sky.GRID_DEPTH's depth, own speed/colour
    depth: float = 0.6
    phase: float = 0.0  # seconds, advanced by dt; the wing-beat glyph reads straight off it
    glide: bool = False
    rank_dx: float = 0.0  # fixed offset from the leader (0 for the leader itself)
    rank_dy: float = 0.0
    jitter_x: float = 0.0  # a follower's small wander around its rank slot
    jitter_y: float = 0.0


@dataclass
class Flock:
    band: str
    leader: Bird
    followers: list[Bird]


@dataclass
class World:
    cols: int
    rows: int
    rng: random.Random = field(default_factory=random.Random)
    palette: Palette = MONO_PLUS
    width: int = field(init=False)
    height: int = field(init=False)
    structure: dict[tuple[int, int], int] = field(default_factory=dict)
    drops: int = 0
    wind: float = 0.0
    seeds: list[Seed] = field(default_factory=list)
    birds: list[Bird] = field(default_factory=list)  # flat render/nudge surface; see `_flocks`
    _flocks: list[Flock] = field(default_factory=list, init=False)
    sky: Sky = field(init=False)
    terminal_vy: float = field(init=False)

    def __post_init__(self) -> None:
        self.width = self.cols * SUB_X
        self.height = self.rows * SUB_Y
        self.sky = Sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette)
        self._set_terminal_vy()

    def _set_terminal_vy(self) -> None:
        """A falling seed's steady-state vy, sub-cells/s: the sky's sub-cell
        height spread over `LANDING_SECONDS` of real time."""
        sky_height = max(self.height - GROUND_ROWS * SUB_Y, 0)
        self.terminal_vy = -sky_height / LANDING_SECONDS

    def reseed(self, seed: int) -> None:
        """Reset the rng and re-bake the sky from it, deterministically."""
        self.rng = random.Random(seed)
        self.sky = Sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette)

    def resize(self, cols: int, rows: int) -> None:
        """Keep the structure; rebake the sky to the new bounds."""
        self.cols = cols
        self.rows = rows
        self.width = cols * SUB_X
        self.height = rows * SUB_Y
        self.sky.resize(cols, rows - GROUND_ROWS)
        self._set_terminal_vy()

    # ---- dropping ---------------------------------------------------------

    def drop(self, col: int) -> None:
        """Spawn a seed above column `col`. Several seeds may be in flight at once."""
        self.drops += 1
        x = (col * SUB_X + SUB_X / 2 + self.rng.uniform(-0.5, 0.5)) % self.width
        spin = self.rng.uniform(*SEED_SPIN_RANGE) * self.rng.choice((-1.0, 1.0))
        angle = self.rng.uniform(0.0, 2 * math.pi)
        self.seeds.append(Seed(x=x, y=float(self.height - 1), vx=self.wind, vy=0.0, angle=angle, spin=spin))

    # ---- advance ------------------------------------------------------

    def tick(self) -> None:
        """Thin wrapper for tests: one frame of `TICK_SECONDS` wall time."""
        self.advance(TICK_SECONDS)

    def advance(self, dt: float) -> None:
        self._advance_wind(dt)
        self.sky.advance(dt, self.wind)
        self._advance_birds(dt)
        self._advance_seeds(dt)

    def _advance_wind(self, dt: float) -> None:
        """An Ornstein-Uhlenbeck step: low-passed, integrated with `dt`, so a
        stalled or fast-forwarded frame never makes the wind jump."""
        raw = self.wind + WIND_SIGMA * math.sqrt(dt) * self.rng.gauss(0, 1)
        raw = max(-WIND_BOUND, min(WIND_BOUND, raw))
        self.wind = raw * math.exp(-WIND_THETA * dt)

    def _advance_birds(self, dt: float) -> None:
        if len(self._flocks) < FLOCK_MAX_ALIVE and self.rng.random() < FLOCK_SPAWN_P * dt:
            self._spawn_flock()
        alive_flocks = []
        birds: list[Bird] = []
        jitter_step = JITTER_STEP * dt
        for flock in self._flocks:
            leader = flock.leader
            leader.x += leader.vx * dt
            leader.phase += dt
            xs = [leader.x]
            for f in flock.followers:
                f.jitter_x = max(-JITTER_CLAMP, min(JITTER_CLAMP, f.jitter_x + self.rng.uniform(-jitter_step, jitter_step)))
                f.jitter_y = max(-JITTER_CLAMP, min(JITTER_CLAMP, f.jitter_y + self.rng.uniform(-jitter_step, jitter_step)))
                f.x = leader.x + f.rank_dx + f.jitter_x
                f.y = leader.y + f.rank_dy + f.jitter_y
                f.vx = leader.vx
                f.phase += dt
                xs.append(f.x)
            gone = min(xs) > self.width + 3 if leader.vx > 0 else max(xs) < -3
            if not gone:
                alive_flocks.append(flock)
                birds.append(leader)
                birds.extend(flock.followers)
        self._flocks = alive_flocks
        self.birds = birds

    def _spawn_flock(self) -> None:
        band = self.rng.choice(tuple(DEPTH_BAND))
        depth = DEPTH_BAND[band]
        speed = DEPTH_SPEED[band]
        from_left = self.rng.random() < 0.5
        vx = speed if from_left else -speed
        sky_floor = GROUND_ROWS * SUB_Y
        sky_span = max(self.height - sky_floor, 0)
        y = self.rng.uniform(sky_floor + 0.25 * sky_span, sky_floor + 0.75 * sky_span)
        x = 0.0 if from_left else float(self.width)
        leader = Bird(x=x, y=y, vx=vx, band=band, depth=depth, phase=0.0, glide=self.rng.random() < GLIDE_P)
        followers: list[Bird] = []
        if self.rng.random() >= LONE_BIRD_P:
            lo_x, hi_x = DEPTH_SPACING_X[band]
            spacing_x = self.rng.uniform(lo_x, hi_x)
            spacing_y = self.rng.uniform(*SPACING_Y)
            direction = 1.0 if vx > 0 else -1.0
            for i in range(self.rng.randint(*FLOCK_FOLLOWERS)):
                side = 1.0 if i % 2 == 0 else -1.0
                rank = i // 2 + 1
                dx = -rank * spacing_x * direction
                dy = side * rank * spacing_y
                followers.append(Bird(
                    x=leader.x + dx, y=leader.y + dy, vx=vx, band=band, depth=depth,
                    phase=i * TICK_SECONDS, glide=self.rng.random() < GLIDE_P, rank_dx=dx, rank_dy=dy,
                ))
        self._flocks.append(Flock(band=band, leader=leader, followers=followers))

    def _advance_seeds(self, dt: float) -> None:
        remaining = []
        for seed in self.seeds:
            self._maybe_nudge(seed)
            seed.vy -= GRAVITY * dt
            seed.vx += self.wind * WIND_COUPLING * dt
            seed.vx *= math.exp(-SEED_DRAG_THETA * dt)
            seed.vy = max(seed.vy, self.terminal_vy)
            seed.angle += (seed.spin + self.wind * SEED_WOBBLE_PER_WIND) * dt
            seed.x = (seed.x + seed.vx * dt) % self.width
            seed.y += seed.vy * dt
            if not self._anchor(seed):
                remaining.append(seed)
        self.seeds = remaining

    def _maybe_nudge(self, seed: Seed) -> None:
        if seed.nudged:
            return
        for bird in self.birds:
            dx = min(abs(bird.x - seed.x), self.width - abs(bird.x - seed.x))
            dy = bird.y - seed.y
            if (dx * dx + dy * dy) ** 0.5 <= 1.5:
                seed.vx += self.rng.choice((-0.05, 0.05))
                seed.vy += 0.02
                seed.nudged = True
                return

    def _anchor(self, seed: Seed) -> bool:
        """Add the seed's cell to the structure, floor or beside it, and drop the seed."""
        cx, cy = int(seed.x), int(seed.y)
        if cy <= 0:
            cell = (cx, 0)
        else:
            neighbours = ((cx, cy - 1), (cx - 1, cy), (cx + 1, cy), (cx - 1, cy - 1), (cx + 1, cy - 1))
            if not any(n in self.structure for n in neighbours):
                return False
            cell = (cx, cy)
        self.structure[cell] = self.drops  # a duplicate cell just re-stamps its age
        return True

    # ---- age / colour -----------------------------------------------------

    def _age(self, cell: tuple[int, int]) -> int:
        return self.drops - self.structure[cell]

    def _age_colour(self, age: int) -> str:
        if age < CACTUS_NEW_MAX:
            return self.palette.cactus_new
        if age < CACTUS_MID_MAX:
            return self.palette.cactus_mid
        return self.palette.cactus_old

    def _bird_colour(self, cy: int, depth: float) -> str:
        """A bird's colour, atmospheric-shifted by its own flock's depth,
        the same way a sky cell's is."""
        sky_rows = self.sky.sky_rows
        row_from_bottom = max(0, min(sky_rows - 1, cy - GROUND_ROWS)) if sky_rows > 0 else 0
        return atmospheric_colour(self.palette.bird, depth, row_from_bottom, max(sky_rows, 1), self.palette)

    def _bird_cells(self) -> dict[tuple[int, int], tuple[str, str]]:
        """This tick's `(cx, cy) -> (glyph, colour)` for every bird cell.

        A "near" bird spans the three cells centred on its own, so a later
        bird's cell can still win over an earlier one's edge — birds don't
        stack-order against each other, only against seed/structure cells,
        which `_sample_cell` checks first regardless.
        """
        cells: dict[tuple[int, int], tuple[str, str]] = {}
        for bird in self.birds:
            cx = int(bird.x) // SUB_X
            cy = int(bird.y) // SUB_Y
            colour = self._bird_colour(cy, bird.depth)
            down, up, glide = DEPTH_GLYPHS[bird.band]
            if bird.glide:
                glyph = glide
            else:
                # `phase` is seconds, advanced continuously — the glyph reads
                # straight off it, never off a per-tick counter.
                down_beat = int(bird.phase / WING_HALF_CYCLE_SECONDS) % 2 == 0
                glyph = down if down_beat else up
            if bird.band == "near":
                for i, ch in enumerate(glyph):
                    cells[(cx - 1 + i, cy)] = (ch, colour)
            else:
                cells[(cx, cy)] = (glyph, colour)
        return cells

    def _ground_speckle(self, cx: int, cy: int) -> str | None:
        """A sand speckle in the bottom `GROUND_ROWS` rows, or `None` for bare sand."""
        if cy >= GROUND_ROWS:
            return None
        h = cx * 7919 + cy * 104729
        if h % 7 == 0:
            return "."
        if h % 11 == 0:
            return ","
        return None

    # ---- falling-seed splat -------------------------------------------------

    def _splat_gaussian(
        self,
        canvas: dict[tuple[int, int], float],
        bx: float,
        by: float,
        sigma_a: float,
        sigma_b: float,
        angle: float,
        radius_px: float,
        floor: float,
        width_px: int,
        height_px: int,
    ) -> None:
        """Add one antialiased Gaussian footprint, centred at `(bx, by)` in
        braille-pixel space, into `canvas` — an ellipse rotated by `angle`
        (a falling seed's tumble) or, at `sigma_a == sigma_b` and `angle=0`
        (a landed pile dot, v6d), a plain round splat. A pixel keeps only its
        brightest contributor, so overlapping splats never double up."""
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        x0 = int(math.floor(bx - radius_px))
        x1 = int(math.ceil(bx + radius_px))
        y0 = max(0, int(math.floor(by - radius_px)))
        y1 = min(height_px - 1, int(math.ceil(by + radius_px)))
        for py in range(y0, y1 + 1):
            dy = py + 0.5 - by
            for px in range(x0, x1 + 1):
                dx = px + 0.5 - bx
                ra = dx * cos_a + dy * sin_a
                rb = -dx * sin_a + dy * cos_a
                density = math.exp(-0.5 * ((ra / sigma_a) ** 2 + (rb / sigma_b) ** 2))
                if density < floor:
                    continue
                key = (px % width_px, py)
                if density > canvas.get(key, 0.0):
                    canvas[key] = density

    def _seed_splat_canvas(self) -> dict[tuple[int, int], float]:
        """This frame's `(px, py) -> density` in braille-pixel space (`PX_X`
        by `PX_Y` per cell) for every airborne seed's tumbling, antialiased
        footprint — an ellipse rotated by `seed.angle`. A landed seed is a
        `structure` cell and never reaches here (see v6d)."""
        canvas: dict[tuple[int, int], float] = {}
        if not self.seeds:
            return canvas
        width_px = self.cols * PX_X
        height_px = self.rows * PX_Y
        for seed in self.seeds:
            bx = seed.x * (PX_X / SUB_X)
            by = seed.y * (PX_Y / SUB_Y)
            self._splat_gaussian(
                canvas, bx, by, SEED_SIGMA_A, SEED_SIGMA_B, seed.angle,
                SEED_SPLAT_RADIUS_PX, SEED_SPLAT_FLOOR, width_px, height_px,
            )
        return canvas

    def _pile_splat_canvas(self) -> dict[tuple[int, int], float]:
        """This frame's `(px, py) -> density` for every landed `structure`
        cell's small round splat, built with the same `_splat_gaussian`
        mechanism a falling seed's footprint uses — no tumble, no rotation.
        Only called under `pile_style == "dots"` (v6d); `render` skips it
        entirely for the default "blocks" style."""
        canvas: dict[tuple[int, int], float] = {}
        if not self.structure:
            return canvas
        width_px = self.cols * PX_X
        height_px = self.rows * PX_Y
        for cx, cy in self.structure:
            bx = (cx + 0.5) * (PX_X / SUB_X)
            by = (cy + 0.5) * (PX_Y / SUB_Y)
            self._splat_gaussian(
                canvas, bx, by, PILE_SPLAT_SIGMA, PILE_SPLAT_SIGMA, 0.0,
                PILE_SPLAT_RADIUS_PX, SEED_SPLAT_FLOOR, width_px, height_px,
            )
        return canvas

    def _seed_pixel_block(
        self, cx: int, cy: int, canvas: dict[tuple[int, int], float]
    ) -> list[list[float]] | None:
        """The `(cx, cy)` cell's `PX_Y` by `PX_X` block from `canvas`, top row
        first as `_ordered_dither` expects, or `None` if no pixel in it has
        any seed density at all."""
        block = [[0.0] * PX_X for _ in range(PX_Y)]
        any_density = False
        width_px = self.cols * PX_X
        for r in range(PX_Y):
            wy = cy * PX_Y + (PX_Y - 1 - r)
            for c in range(PX_X):
                wx = (cx * PX_X + c) % width_px
                v = canvas.get((wx, wy), 0.0)
                if v:
                    any_density = True
                block[r][c] = v
        return block if any_density else None

    # ---- render -----------------------------------------------------------

    def render(self) -> Text:
        """Render `rows` lines of `cols` cells, one style span per run."""
        bird_cells = self._bird_cells()
        seed_canvas = self._seed_splat_canvas()
        pile_canvas = self._pile_splat_canvas() if self.sky.config.pile_style == "dots" else {}
        sky_grid = self.sky.render_cells()
        text = Text()
        for r in range(self.rows):
            cy = self.rows - 1 - r
            sky_row = sky_grid[r] if r < len(sky_grid) else None
            runs: list[list[str | None]] = []
            for cx in range(self.cols):
                ch, style = self._sample_cell(cx, cy, seed_canvas, bird_cells, sky_row, pile_canvas)
                if runs and runs[-1][1] == style:
                    runs[-1][0] += ch  # type: ignore[operator]
                else:
                    runs.append([ch, style])
            for chars, style in runs:
                if style:
                    text.append(chars, style=style)
                else:
                    text.append(chars)
            if r < self.rows - 1:
                text.append("\n")
        return text

    def _sample_cell(
        self,
        cx: int,
        cy: int,
        seed_canvas: dict[tuple[int, int], float],
        bird_cells: dict[tuple[int, int], tuple[str, str]],
        sky_row: list[tuple[str, str | None]] | None,
        pile_canvas: dict[tuple[int, int], float] | None = None,
    ) -> tuple[str, str | None]:
        if seed_canvas:
            block = self._seed_pixel_block(cx, cy, seed_canvas)
            if block is not None:
                return _ordered_dither(block), self.palette.seed

        base_x, base_y = cx * SUB_X, cy * SUB_Y
        # tl, tr, bl, br — top is the higher y.
        offsets = ((0, 1), (1, 1), (0, 0), (1, 0))
        struct_bits = 0
        struct_cells: list[tuple[int, int]] = []
        for i, (dx, dy) in enumerate(offsets):
            cell = (base_x + dx, base_y + dy)
            if cell in self.structure:
                struct_bits |= 1 << i
                struct_cells.append(cell)
        if struct_bits:
            age = max(self._age(cell) for cell in struct_cells)
            colour = self._age_colour(age)
            if pile_canvas:
                block = self._seed_pixel_block(cx, cy, pile_canvas)
                if block is not None:
                    return _ordered_dither(block), colour
            return QUADRANT[struct_bits], colour

        bird_cell = bird_cells.get((cx, cy))
        if bird_cell is not None:
            return bird_cell

        if sky_row is not None:
            glyph, colour = sky_row[cx]
            if glyph != " ":
                return glyph, colour

        speckle = self._ground_speckle(cx, cy)
        if speckle is not None:
            return speckle, self.palette.sand_dot

        return " ", None
