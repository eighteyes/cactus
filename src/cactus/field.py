"""
field.py — the answer strip's background simulation: sky, weather, cacti.

Responsibilities:
- Hold a small world (a noise-rendered parallax sky, wind, bird flocks, ground
  speckle, faint perspective ground lines, and the settled cactus structure)
  in sub-cell resolution, two sub-cells per terminal cell in each axis.
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
- Merge seeds that touch during the fall into a rigid `Clump` (v6e): every
  frame, after motion, any two clumps with a member pair within
  `stick_distance` (a shared `SkyConfig` lever) combine into one — mass-
  weighted centre and velocity, averaged and mass-damped spin, member
  offsets re-expressed around the new centre with each member's current
  tumble angle baked in. `World.seeds` stays the flat list render and nudge
  iterate; a lone seed is a clump of one member.
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
- Ground lines (v7): `ground_lines` faint dotted lines cross the ground band,
  converging on the sky's own vanishing point (`centre, horizon_row`, the
  same shared `SkyConfig` levers the cloud deck projects through); their
  bottom endpoints drift sideways with `Sky.camera_x`. They sit under the
  sand speckle and under every cactus cell — the lowest-priority layer,
  drawn only where nothing else claims the cell.
- Perf (v6f): `_seed_splat_canvas`/`_pile_splat_canvas` also return the set of
  terminal cells they actually touched, so `_sample_cell` only ever asks the
  (otherwise empty) splat canvas about a cell in that set — a frame with no
  seeds falling never calls it at all. `World.apply_sky_config` swaps a new
  `SkyConfig` into the running sky, rebuilding it as the other engine class
  when `sky_engine` itself changed (`sky.apply` alone can only retune the
  engine already running). `run_bench()` (`cactus sky --bench`) times 50
  frames of a 100x20, 3-seed world and prints the per-step breakdown.

Pure Python: no persistence, no store, no Textual import.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from rich.text import Text

from .sky import PX_X, PX_Y, PuffSky, Sky, SkyConfig, TextureSky, atmospheric_colour, make_sky, _ordered_dither

SUB_X = 2
SUB_Y = 2
GROUND_ROWS = 2  # terminal rows of flat ground
QUADRANT = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
# `_sample_cell`'s structure-bit offsets, precomputed once (perf, v6f) — tl,
# tr, bl, br, top is the higher y.
_STRUCT_OFFSETS = tuple(enumerate(((0, 1), (1, 1), (0, 0), (1, 0))))

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
    ground_line_near: str = "grey42"
    ground_line_far: str = "grey30"


MONO_PLUS = Palette()


@dataclass
class Member:
    """One seed's place inside its clump's local frame (v6e): a fixed offset
    from the clump's centre and a tumble angle baked in at drop or merge —
    the clump's own `angle` is added to it fresh every frame, so the member
    still tumbles even after its offset is frozen."""

    dx: float = 0.0
    dy: float = 0.0
    angle: float = 0.0


@dataclass
class Clump:
    """A rigid group of one or more seeds (v6e): one centre, one velocity,
    one spin, falling and landing as a unit. A freshly dropped seed is a
    clump of one, its single `Member` at offset `(0, 0)` — so `x`/`y`/`vx`/
    `vy`/`angle`/`spin`/`nudged` read exactly as a lone falling seed did
    before clumps (v6e)."""

    x: float
    y: float
    vx: float
    vy: float
    nudged: bool = False
    angle: float = 0.0  # radians, added to every member's own baked angle
    spin: float = 0.0  # radians/second, drawn once at drop; see SEED_SPIN_RANGE
    members: list[Member] = field(default_factory=lambda: [Member()])


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
    # Landings since the garden was last saved (garden.py); the TUI resets
    # this to 0 after each save. The world stays file-agnostic — it only
    # counts, it never reads or writes garden.json itself.
    landed_since_save: int = 0
    wind: float = 0.0
    seeds: list[Clump] = field(default_factory=list)
    birds: list[Bird] = field(default_factory=list)  # flat render/nudge surface; see `_flocks`
    _flocks: list[Flock] = field(default_factory=list, init=False)
    sky_config: SkyConfig | None = None
    sky: Sky | TextureSky | PuffSky = field(init=False)
    terminal_vy: float = field(init=False)

    def __post_init__(self) -> None:
        self.width = self.cols * SUB_X
        self.height = self.rows * SUB_Y
        self.sky = make_sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette, self.sky_config)
        self._set_terminal_vy()

    def _set_terminal_vy(self) -> None:
        """A falling seed's steady-state vy, sub-cells/s: the sky's sub-cell
        height spread over `LANDING_SECONDS` of real time."""
        sky_height = max(self.height - GROUND_ROWS * SUB_Y, 0)
        self.terminal_vy = -sky_height / LANDING_SECONDS

    def reseed(self, seed: int) -> None:
        """Reset the rng and re-bake the sky from it, deterministically."""
        self.rng = random.Random(seed)
        self.sky = make_sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette, self.sky.config)

    def apply_sky_config(self, config: SkyConfig) -> None:
        """Swap `config` into the running sky (`Sky.apply`/`TextureSky.apply`)
        — or, when `sky_engine` itself changed, rebuild `self.sky` as the
        other engine (v6f): `apply` alone can only retune the engine that is
        already running, never turn a `Sky` into a `TextureSky` or back.
        Rebuilding re-bakes the weather from scratch, same as a resize."""
        if config.sky_engine != getattr(self.sky, "ENGINE", "fluid"):
            self.sky = make_sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette, config)
        else:
            self.sky.apply(config)

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
        self.seeds.append(Clump(x=x, y=float(self.height - 1), vx=self.wind, vy=0.0, angle=angle, spin=spin))

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
        for clump in self.seeds:
            self._maybe_nudge(clump)
            n = len(clump.members)
            clump.vy -= GRAVITY * dt
            clump.vx += self.wind * WIND_COUPLING * dt / math.sqrt(n)
            clump.vx *= math.exp(-SEED_DRAG_THETA * dt)
            clump.vy = max(clump.vy, self.terminal_vy)
            clump.angle += (clump.spin + self.wind * SEED_WOBBLE_PER_WIND) * dt
            clump.x = (clump.x + clump.vx * dt) % self.width
            clump.y += clump.vy * dt
        self._merge_clumps()
        remaining = []
        for clump in self.seeds:
            if not self._anchor(clump):
                remaining.append(clump)
        self.seeds = remaining

    def _maybe_nudge(self, clump: Clump) -> None:
        if clump.nudged:
            return
        for bird in self.birds:
            dx = min(abs(bird.x - clump.x), self.width - abs(bird.x - clump.x))
            dy = bird.y - clump.y
            if (dx * dx + dy * dy) ** 0.5 <= 1.5:
                clump.vx += self.rng.choice((-0.05, 0.05))
                clump.vy += 0.02
                clump.nudged = True
                return

    def _member_dx(self, ax: float, bx: float) -> float:
        """Horizontal distance between two x positions, shortest way around
        the world's wraparound — matches `_maybe_nudge`'s bird distance."""
        raw = abs(ax - bx)
        return min(raw, self.width - raw)

    def _touching(self, a: Clump, b: Clump, stick_distance: float) -> bool:
        """Any member of `a` within `stick_distance` of any member of `b`."""
        thresh2 = stick_distance * stick_distance
        for ma in a.members:
            ax, ay = a.x + ma.dx, a.y + ma.dy
            for mb in b.members:
                bx, by = b.x + mb.dx, b.y + mb.dy
                dx = self._member_dx(ax, bx)
                dy = ay - by
                if dx * dx + dy * dy <= thresh2:
                    return True
        return False

    def _merge(self, a: Clump, b: Clump) -> Clump:
        """Combine two touching clumps: mass-weighted centre and velocity
        (mass is member count), spin averaged then damped by 1/n, and every
        member re-expressed around the new centre with its current absolute
        tumble angle baked in — the shape they touched in is the shape they
        keep."""
        na, nb = len(a.members), len(b.members)
        total = na + nb
        x = (a.x * na + b.x * nb) / total
        y = (a.y * na + b.y * nb) / total
        vx = (a.vx * na + b.vx * nb) / total
        vy = (a.vy * na + b.vy * nb) / total
        spin = (a.spin + b.spin) / 2.0 / total
        members: list[Member] = []
        for clump in (a, b):
            for m in clump.members:
                members.append(Member(
                    dx=clump.x + m.dx - x,
                    dy=clump.y + m.dy - y,
                    angle=clump.angle + m.angle,
                ))
        return Clump(x=x, y=y, vx=vx, vy=vy, nudged=a.nudged or b.nudged, spin=spin, members=members)

    def _merge_clumps(self) -> None:
        """Every frame, after motion: merge any pair of clumps touching at
        `stick_distance`, at most once per pair per frame — a clump may go
        on to merge again with another later in the same pass."""
        stick_distance = self.sky.config.stick_distance
        merged = True
        while merged:
            merged = False
            for i in range(len(self.seeds)):
                for j in range(i + 1, len(self.seeds)):
                    if self._touching(self.seeds[i], self.seeds[j], stick_distance):
                        new_clump = self._merge(self.seeds[i], self.seeds[j])
                        self.seeds = [c for k, c in enumerate(self.seeds) if k not in (i, j)]
                        self.seeds.append(new_clump)
                        merged = True
                        break
                if merged:
                    break

    def _anchor(self, clump: Clump) -> bool:
        """Land the whole clump when any member's cell floors or sits beside
        the structure, then add every member's own cell to the structure
        (an already-taken cell just re-stamps its age)."""
        lands = False
        for m in clump.members:
            cx, cy = int(clump.x + m.dx), int(clump.y + m.dy)
            if cy <= 0:
                lands = True
                break
            neighbours = ((cx, cy - 1), (cx - 1, cy), (cx + 1, cy), (cx - 1, cy - 1), (cx + 1, cy - 1))
            if any(n in self.structure for n in neighbours):
                lands = True
                break
        if not lands:
            return False
        for m in clump.members:
            cx, cy = int(clump.x + m.dx), int(clump.y + m.dy)
            cell = (cx, 0) if cy <= 0 else (cx, cy)
            self.structure[cell] = self.drops
        self.landed_since_save += 1
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

    def _ground_line_x(self, i: int, n: int, screen_row: int) -> float:
        """Line `i` of `n`'s column at `screen_row` (screen-row units, 0 at
        the top): a straight interpolation from the sky's vanishing point
        `(centre, horizon_row)` at `screen_row == horizon_row` out to this
        line's own drifting point on the bottom edge at `screen_row == rows -
        1`. The wind's low-passed drift (`Sky.camera_x`, converted from
        pixels to columns) slides every line's bottom endpoint sideways in
        lock-step, never the vanishing point itself."""
        vp_col = self.cols / 2.0
        vp_row = self.sky.sky_rows * self.sky.config.horizon
        bottom_row = self.rows - 1
        span = bottom_row - vp_row
        t = 1.0 if span <= 0 else max(0.0, min(1.0, (screen_row - vp_row) / span))
        drift = self.sky.camera_x / PX_X
        base_x = (i + 0.5) / n * self.cols
        bottom_x = (base_x + drift) % self.cols
        return vp_col + t * (bottom_x - vp_col)

    def _ground_line_cells(self) -> dict[tuple[int, int], tuple[str, str]]:
        """This frame's `(cx, cy) -> (glyph, colour)` for every ground-line
        hit, built once per `render()` (not once per cell) — `n` lines across
        `GROUND_ROWS` rows is a handful of points, not a `cols`-wide scan."""
        n = self.sky.config.ground_lines
        cells: dict[tuple[int, int], tuple[str, str]] = {}
        if n <= 0:
            return cells
        for cy in range(GROUND_ROWS):
            screen_row = self.rows - 1 - cy
            colour = self.palette.ground_line_near if cy == 0 else self.palette.ground_line_far
            for i in range(n):
                if ((i * 1000003 + cy * 97) & 0xFF) % 3 == 0:
                    continue  # dotted: leave a gap rather than a solid run
                x = self._ground_line_x(i, n, screen_row)
                cx = int(round(x)) % self.cols
                cells[(cx, cy)] = (".", colour)
        return cells

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

    @staticmethod
    def _splat_touched_cells(canvas: dict[tuple[int, int], float]) -> set[tuple[int, int]]:
        """The terminal cells a splat canvas actually put density into
        (v6f, perf): a canvas pixel `(px, py)` lands in cell `(px // PX_X,
        py // PX_Y)`, the same mapping `_seed_pixel_block` reads it back
        through. `_sample_cell` consults `_seed_pixel_block` only for a cell
        in this set, so a frame with seeds far from most of the field never
        even asks the (empty) canvas about a cell nowhere near one."""
        return {(px // PX_X, py // PX_Y) for px, py in canvas}

    def _seed_splat_canvas(self) -> tuple[dict[tuple[int, int], float], set[tuple[int, int]]]:
        """This frame's `(px, py) -> density` in braille-pixel space (`PX_X`
        by `PX_Y` per cell) for every airborne clump member's tumbling,
        antialiased footprint — an ellipse rotated by the clump's own
        `angle` plus the member's baked-in angle (v6e), so a multi-member
        clump reads as a lumpy mass. A landed seed is a `structure` cell and
        never reaches here (see v6d). The second element is the set of
        terminal cells the canvas touched (v6f)."""
        canvas: dict[tuple[int, int], float] = {}
        if not self.seeds:
            return canvas, set()
        width_px = self.cols * PX_X
        height_px = self.rows * PX_Y
        for clump in self.seeds:
            for m in clump.members:
                bx = (clump.x + m.dx) * (PX_X / SUB_X)
                by = (clump.y + m.dy) * (PX_Y / SUB_Y)
                self._splat_gaussian(
                    canvas, bx, by, SEED_SIGMA_A, SEED_SIGMA_B, clump.angle + m.angle,
                    SEED_SPLAT_RADIUS_PX, SEED_SPLAT_FLOOR, width_px, height_px,
                )
        return canvas, self._splat_touched_cells(canvas)

    def _pile_splat_canvas(self) -> tuple[dict[tuple[int, int], float], set[tuple[int, int]]]:
        """This frame's `(px, py) -> density` for every landed `structure`
        cell's small round splat, built with the same `_splat_gaussian`
        mechanism a falling seed's footprint uses — no tumble, no rotation.
        Only called under `pile_style == "dots"` (v6d); `render` skips it
        entirely for the default "blocks" style. The second element is the
        set of terminal cells the canvas touched (v6f)."""
        canvas: dict[tuple[int, int], float] = {}
        if not self.structure:
            return canvas, set()
        width_px = self.cols * PX_X
        height_px = self.rows * PX_Y
        for cx, cy in self.structure:
            bx = (cx + 0.5) * (PX_X / SUB_X)
            by = (cy + 0.5) * (PX_Y / SUB_Y)
            self._splat_gaussian(
                canvas, bx, by, PILE_SPLAT_SIGMA, PILE_SPLAT_SIGMA, 0.0,
                PILE_SPLAT_RADIUS_PX, SEED_SPLAT_FLOOR, width_px, height_px,
            )
        return canvas, self._splat_touched_cells(canvas)

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

    def pile_rows(self) -> int:
        """Terminal rows tall enough to show the whole landed pile: the
        ground band plus every row the structure currently occupies, plus
        one row of headroom. Used by the TUI to size the field strip in
        pile-only mode."""
        if not self.structure:
            return GROUND_ROWS + 1
        tallest_cy = max(cy for _cx, cy in self.structure)
        return GROUND_ROWS + tallest_cy // SUB_Y + 1

    def render(self, pile_only: bool = False) -> Text:
        """Render `rows` lines of `cols` cells, one style span per run.

        `pile_only` (the `` ` `` toggle with the field strip hidden) skips
        the sky, birds, falling seeds, ground speckle, and ground lines —
        every cell not part of the landed structure renders blank.
        """
        if pile_only:
            bird_cells: dict[tuple[int, int], tuple[str, str]] = {}
            seed_canvas, seed_cells = {}, set()
            pile_canvas, pile_cells = {}, set()
            ground_line_cells: dict[tuple[int, int], tuple[str, str]] = {}
            sky_grid: list[list[tuple[str, str | None]]] = []
        else:
            bird_cells = self._bird_cells()
            seed_canvas, seed_cells = self._seed_splat_canvas()
            pile_canvas, pile_cells = (
                self._pile_splat_canvas() if self.sky.config.pile_style == "dots" else ({}, set())
            )
            ground_line_cells = self._ground_line_cells()
            sky_grid = self.sky.render_cells()
        text = Text()
        for r in range(self.rows):
            cy = self.rows - 1 - r
            sky_row = sky_grid[r] if r < len(sky_grid) else None
            runs: list[list[str | None]] = []
            for cx in range(self.cols):
                ch, style = self._sample_cell(
                    cx, cy, seed_canvas, seed_cells, bird_cells, sky_row, pile_canvas, pile_cells, ground_line_cells,
                    pile_only=pile_only,
                )
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
        seed_cells: set[tuple[int, int]],
        bird_cells: dict[tuple[int, int], tuple[str, str]],
        sky_row: list[tuple[str, str | None]] | None,
        pile_canvas: dict[tuple[int, int], float] | None = None,
        pile_cells: set[tuple[int, int]] | None = None,
        ground_line_cells: dict[tuple[int, int], tuple[str, str]] | None = None,
        pile_only: bool = False,
    ) -> tuple[str, str | None]:
        if (cx, cy) in seed_cells:
            block = self._seed_pixel_block(cx, cy, seed_canvas)
            if block is not None:
                return _ordered_dither(block), self.palette.seed

        struct_bits = 0
        struct_cells: list[tuple[int, int]] = []
        if self.structure:
            base_x, base_y = cx * SUB_X, cy * SUB_Y
            # tl, tr, bl, br — top is the higher y.
            for i, (dx, dy) in _STRUCT_OFFSETS:
                cell = (base_x + dx, base_y + dy)
                if cell in self.structure:
                    struct_bits |= 1 << i
                    struct_cells.append(cell)
        if struct_bits:
            age = max(self._age(cell) for cell in struct_cells)
            colour = self._age_colour(age)
            if pile_canvas and pile_cells and (cx, cy) in pile_cells:
                block = self._seed_pixel_block(cx, cy, pile_canvas)
                if block is not None:
                    return _ordered_dither(block), colour
            return QUADRANT[struct_bits], colour

        if pile_only:
            return " ", None

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

        if ground_line_cells:
            line = ground_line_cells.get((cx, cy))
            if line is not None:
                return line

        return " ", None


# ---- perf bench (v6f, `cactus sky --bench`) --------------------------------


BENCH_COLS = 100
BENCH_ROWS = 20
BENCH_SEEDS = 3
BENCH_FRAMES = 50


def run_bench(frames: int = BENCH_FRAMES) -> list[tuple[str, float]]:
    """`frames` frames of a `BENCH_COLS` by `BENCH_ROWS` world with
    `BENCH_SEEDS` seeds falling, one `tick()` + `render()` each — the same
    shape as the frame-time tests. Returns `(label, mean_ms)` rows, the
    overall mean first, so `cli.cmd_sky --bench` can print one line per row.

    A second, short pass re-measures `advance()`'s and `render()`'s own
    sub-steps individually for the rest of the breakdown; it re-renders a few
    extra frames to do this and is not counted in the headline mean.
    """
    world = World(cols=BENCH_COLS, rows=BENCH_ROWS, rng=random.Random(7))
    for _ in range(30):
        world.tick()
    for i in range(BENCH_SEEDS):
        world.drop((i * BENCH_COLS) // BENCH_SEEDS)
    for _ in range(5):
        world.tick()

    t_advance = t_render = 0.0
    for _ in range(frames):
        t0 = time.perf_counter()
        world.tick()
        t1 = time.perf_counter()
        world.render()
        t2 = time.perf_counter()
        t_advance += t1 - t0
        t_render += t2 - t1
    n = frames
    rows = [
        ("mean frame (advance + render)", (t_advance + t_render) / n * 1000),
        ("advance", t_advance / n * 1000),
        ("render", t_render / n * 1000),
    ]

    breakdown_frames = 20
    t_sky_advance = t_birds = t_seeds = 0.0
    t_seed_splat = t_sky_render = t_sample = 0.0
    for _ in range(breakdown_frames):
        t0 = time.perf_counter()
        world._advance_wind(TICK_SECONDS)
        t1 = time.perf_counter()
        world.sky.advance(TICK_SECONDS, world.wind)
        t2 = time.perf_counter()
        world._advance_birds(TICK_SECONDS)
        t3 = time.perf_counter()
        world._advance_seeds(TICK_SECONDS)
        t4 = time.perf_counter()
        t_sky_advance += t2 - t1
        t_birds += t3 - t2
        t_seeds += t4 - t3

        t5 = time.perf_counter()
        seed_canvas, seed_cells = world._seed_splat_canvas()
        pile_canvas, pile_cells = (
            world._pile_splat_canvas() if world.sky.config.pile_style == "dots" else ({}, set())
        )
        bird_cells = world._bird_cells()
        ground_line_cells = world._ground_line_cells()
        t6 = time.perf_counter()
        sky_grid = world.sky.render_cells()
        t7 = time.perf_counter()
        for r in range(world.rows):
            cy = world.rows - 1 - r
            sky_row = sky_grid[r] if r < len(sky_grid) else None
            for cx in range(world.cols):
                world._sample_cell(
                    cx, cy, seed_canvas, seed_cells, bird_cells, sky_row, pile_canvas, pile_cells, ground_line_cells,
                )
        t8 = time.perf_counter()
        t_seed_splat += t6 - t5
        t_sky_render += t7 - t6
        t_sample += t8 - t7

    bn = breakdown_frames
    rows.extend([
        ("  sky.advance", t_sky_advance / bn * 1000),
        ("  birds", t_birds / bn * 1000),
        ("  seeds", t_seeds / bn * 1000),
        ("  seed/pile/bird/ground canvases", t_seed_splat / bn * 1000),
        ("  sky.render_cells", t_sky_render / bn * 1000),
        ("  per-cell sample", t_sample / bn * 1000),
    ])
    return rows
