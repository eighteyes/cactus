"""
field.py — the answer strip's background simulation: sky, weather, cacti.

Responsibilities:
- Hold a small world (a noise-rendered parallax sky, wind, bird flocks, ground
  speckle, and the settled cactus structure) in sub-cell resolution, two
  sub-cells per terminal cell in each axis.
- Advance the world one tick: tick the sky's three cellular-automaton air
  grids (passing this tick's wind for their parallax drift), wander the wind,
  fly and despawn flocks (and lone birds) at one of the sky's three depths,
  and fall seeds under gravity and wind until they anchor.
- Drop a seed into a column; anchor it to the floor or beside the structure,
  including the two "reverse pawn" diagonals below it. Count every drop, so
  the structure can carry age in decisions rather than in time.
- Hold the colour palette (`Palette`, default `MONO_PLUS`): each sky grid's
  dark/light tone-ramp pair, the haze colour clouds fade toward, cactus age
  bands, seed, bird, and sand-speckle colours. No sky background anywhere —
  shade comes only from glyph colour.
- Render the world as a styled rich.text.Text: the structure and falling
  seeds are quadrant-sampled from their four sub-cells (block glyphs), the
  sky is `Sky.render_cells()`'s braille/punctuation/stroke glyphs, and birds
  and ground speckle render as single ASCII glyphs.

Pure Python: no persistence, no store, no Textual import.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from rich.text import Text

from .sky import Sky, atmospheric_colour

SUB_X = 2
SUB_Y = 2
GROUND_ROWS = 2  # terminal rows of flat ground
QUADRANT = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"

# Pacing, not physics (q: "less video gamey, a seed takes 1 min to land"):
# the timer tick length and the fall time a dropped seed should take to cross
# the sky, both in seconds. `World.terminal_vy` derives the fall speed a seed
# settles into from these plus its own sky height, so the drop still takes
# about a minute regardless of the field's size.
TICK_SECONDS = 0.1
LANDING_SECONDS = 60.0
GRAVITY = 0.002  # sub-cells/tick^2: reaches terminal velocity within a couple of seconds
WIND_COUPLING = 0.0003  # how much wind nudges a falling seed's vx per tick

# structure age bands, counted in `World.drops` (decisions), not ticks
CACTUS_NEW_MAX = 34
CACTUS_MID_MAX = 100

# Flocks (q: "needs more birds too, flocks of birds"). Each flock is spawned
# at one of the sky's three depth bands, sharing that band's speed, colour
# shift, and glyph set with the parallax sky itself. A "flock" with zero
# followers is a lone bird.
FLOCK_MAX_ALIVE = 3
FLOCK_SPAWN_P = 0.002  # per tick, while fewer than FLOCK_MAX_ALIVE are alive
LONE_BIRD_P = 0.25  # of spawns, a lone bird instead of a flock
FLOCK_FOLLOWERS = (4, 12)  # inclusive range
GLIDE_P = 0.125  # 1 in 8 birds glides instead of flapping
JITTER_STEP = 0.05  # sub-cells/tick, a follower's wander around its rank slot
JITTER_CLAMP = 0.6
SPACING_Y = (0.4, 0.8)  # sub-cells, vertical rank spacing, every depth
DEPTH_BAND = {"far": 0.9, "mid": 0.6, "near": 0.2}  # matches sky.GRID_DEPTH
DEPTH_SPEED = {"far": 0.08, "mid": 0.15, "near": 0.25}  # sub-cells/tick
DEPTH_SPACING_X = {"far": (1.0, 1.5), "mid": (1.5, 2.5), "near": (2.5, 3.5)}
# (down-beat, up-beat, gliding) glyphs; "near" spans 3 cells, (left, centre, right).
DEPTH_GLYPHS = {
    "far": (".", "'", ","),
    "mid": ("v", "^", "~"),
    "near": ("\\_/", "/^\\", "~~~"),
}


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


@dataclass
class Bird:
    x: float
    y: float
    vx: float
    band: str = "mid"  # "far" / "mid" / "near" — matches sky.GRID_DEPTH's depth, own speed/colour
    depth: float = 0.6
    phase: int = 0  # ticks added before the //4 wing-beat check, ripples the flock
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
    _tick_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.width = self.cols * SUB_X
        self.height = self.rows * SUB_Y
        self.sky = Sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette)
        self._set_terminal_vy()

    def _set_terminal_vy(self) -> None:
        """A falling seed's steady-state vy: the sky's sub-cell height spread
        over the number of ticks `LANDING_SECONDS` at `TICK_SECONDS` each."""
        sky_height = max(self.height - GROUND_ROWS * SUB_Y, 0)
        self.terminal_vy = -sky_height / (LANDING_SECONDS / TICK_SECONDS)

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
        self.seeds.append(Seed(x=x, y=float(self.height - 1), vx=self.wind, vy=0.0))

    # ---- tick ---------------------------------------------------------

    def tick(self) -> None:
        self._tick_count += 1
        self._tick_wind()
        self.sky.tick(self.wind)
        self._tick_birds()
        self._tick_seeds()

    def _tick_wind(self) -> None:
        self.wind += self.rng.gauss(0, 0.02)
        self.wind = max(-0.6, min(0.6, self.wind))
        self.wind *= 0.995

    def _tick_birds(self) -> None:
        if len(self._flocks) < FLOCK_MAX_ALIVE and self.rng.random() < FLOCK_SPAWN_P:
            self._spawn_flock()
        alive_flocks = []
        birds: list[Bird] = []
        for flock in self._flocks:
            leader = flock.leader
            leader.x += leader.vx
            xs = [leader.x]
            for f in flock.followers:
                f.jitter_x = max(-JITTER_CLAMP, min(JITTER_CLAMP, f.jitter_x + self.rng.uniform(-JITTER_STEP, JITTER_STEP)))
                f.jitter_y = max(-JITTER_CLAMP, min(JITTER_CLAMP, f.jitter_y + self.rng.uniform(-JITTER_STEP, JITTER_STEP)))
                f.x = leader.x + f.rank_dx + f.jitter_x
                f.y = leader.y + f.rank_dy + f.jitter_y
                f.vx = leader.vx
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
        leader = Bird(x=x, y=y, vx=vx, band=band, depth=depth, phase=0, glide=self.rng.random() < GLIDE_P)
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
                    phase=i, glide=self.rng.random() < GLIDE_P, rank_dx=dx, rank_dy=dy,
                ))
        self._flocks.append(Flock(band=band, leader=leader, followers=followers))

    def _tick_seeds(self) -> None:
        remaining = []
        for seed in self.seeds:
            self._maybe_nudge(seed)
            seed.vy -= GRAVITY
            seed.vx += self.wind * WIND_COUPLING
            seed.vx *= 0.98
            seed.vy = max(seed.vy, self.terminal_vy)
            seed.x = (seed.x + seed.vx) % self.width
            seed.y += seed.vy
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
                down_beat = ((self._tick_count + bird.phase) // 4) % 2 == 0
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

    # ---- render -----------------------------------------------------------

    def render(self) -> Text:
        """Render `rows` lines of `cols` cells, one style span per run."""
        bird_cells = self._bird_cells()
        seed_cells = {(int(s.x) % self.width, int(s.y)) for s in self.seeds}
        sky_grid = self.sky.render_cells()
        text = Text()
        for r in range(self.rows):
            cy = self.rows - 1 - r
            sky_row = sky_grid[r] if r < len(sky_grid) else None
            runs: list[list[str | None]] = []
            for cx in range(self.cols):
                ch, style = self._sample_cell(cx, cy, seed_cells, bird_cells, sky_row)
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
        seed_cells: set[tuple[int, int]],
        bird_cells: dict[tuple[int, int], tuple[str, str]],
        sky_row: list[tuple[str, str | None]] | None,
    ) -> tuple[str, str | None]:
        base_x, base_y = cx * SUB_X, cy * SUB_Y
        # tl, tr, bl, br — top is the higher y.
        offsets = ((0, 1), (1, 1), (0, 0), (1, 0))
        seed_bits = 0
        struct_bits = 0
        struct_cells: list[tuple[int, int]] = []
        for i, (dx, dy) in enumerate(offsets):
            cell = (base_x + dx, base_y + dy)
            if cell in self.structure:
                struct_bits |= 1 << i
                struct_cells.append(cell)
            if cell in seed_cells:
                seed_bits |= 1 << i
        if seed_bits:
            return QUADRANT[seed_bits | struct_bits], self.palette.seed
        if struct_bits:
            age = max(self._age(cell) for cell in struct_cells)
            return QUADRANT[struct_bits], self._age_colour(age)

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
