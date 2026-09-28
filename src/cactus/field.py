"""
field.py — the answer strip's background simulation: sky, weather, cacti.

Responsibilities:
- Hold a small world (clouds at parallax depth, wind, birds, ground speckle,
  and the settled cactus structure) in sub-cell resolution, two sub-cells per
  terminal cell in each axis.
- Advance the world one tick: drift clouds, wander the wind, fly and despawn
  birds, and fall seeds under gravity and wind until they anchor.
- Drop a seed into a column; anchor it to the floor or beside the structure,
  including the two "reverse pawn" diagonals below it. Count every drop, so
  the structure can carry age in decisions rather than in time.
- Hold the colour palette (`Palette`, default `MONO_PLUS`): cloud depth
  bands, cactus age bands, seed, bird, and sand-speckle colours. No sky
  background anywhere — shade comes only from glyph colour.
- Render the world as a styled rich.text.Text: the structure and falling
  seeds are quadrant-sampled from their four sub-cells (block glyphs), while
  clouds, birds, and ground speckle render as single ASCII glyphs.

Pure Python: no persistence, no store, no Textual import.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from rich.text import Text

SUB_X = 2
SUB_Y = 2
GROUND_ROWS = 2  # terminal rows of flat ground
GRAVITY = 0.04
QUADRANT = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"

# structure age bands, counted in `World.drops` (decisions), not ticks
CACTUS_NEW_MAX = 34
CACTUS_MID_MAX = 100


@dataclass(frozen=True)
class Palette:
    """Colours for the field. `MONO_PLUS`: mono-plus — no backgrounds, only
    depth-shaded clouds and age-shaded cacti."""

    cloud_far: str = "grey35"
    cloud_mid: str = "grey58"
    cloud_near: str = "grey82"
    bird: str = "grey85"
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
class Cloud:
    x: float
    y: float
    w: float
    speed: float
    depth: float


@dataclass
class Bird:
    x: float
    y: float
    vx: float


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
    birds: list[Bird] = field(default_factory=list)
    clouds: list[Cloud] = field(default_factory=list, init=False)
    _tick_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.width = self.cols * SUB_X
        self.height = self.rows * SUB_Y
        self.clouds = self._make_clouds()

    def reseed(self, seed: int) -> None:
        """Reset the rng and regenerate the clouds from it, deterministically."""
        self.rng = random.Random(seed)
        self.clouds = self._make_clouds()

    def resize(self, cols: int, rows: int) -> None:
        """Keep the structure; re-spawn clouds inside the new bounds."""
        self.cols = cols
        self.rows = rows
        self.width = cols * SUB_X
        self.height = rows * SUB_Y
        self.clouds = self._make_clouds()

    # ---- generation -----------------------------------------------------

    def _sky_floor(self) -> float:
        """Bottom of the sky, in sub-cells; the ground band sits below it."""
        return GROUND_ROWS * SUB_Y

    def _cloud_depth(self, y: float) -> float:
        """Distance cue in [0, 1] from a cloud's height. High is far."""
        sky_floor = self._sky_floor()
        span = self.height - sky_floor
        if span <= 0:
            return 1.0
        return max(0.0, min(1.0, (y - sky_floor) / span))

    def _make_cloud(self, y: float) -> Cloud:
        depth = self._cloud_depth(y)
        return Cloud(
            x=self.rng.uniform(0, self.width),
            y=y,
            w=3 + 5 * (1 - depth),
            speed=0.08 + 0.45 * (1 - depth),
            depth=depth,
        )

    def _make_clouds(self) -> list[Cloud]:
        sky_floor = self._sky_floor()
        return [
            self._make_cloud(self.rng.uniform(sky_floor, self.height))
            for _ in range(self.rng.randint(4, 6))
        ]

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
        self._tick_clouds()
        self._tick_birds()
        self._tick_seeds()

    def _tick_wind(self) -> None:
        self.wind += self.rng.gauss(0, 0.02)
        self.wind = max(-0.6, min(0.6, self.wind))
        self.wind *= 0.995

    def _tick_clouds(self) -> None:
        for cloud in self.clouds:
            cloud.x = (cloud.x + cloud.speed) % self.width

    def _tick_birds(self) -> None:
        if len(self.birds) < 2 and self.rng.random() < 0.005:
            self._spawn_bird()
        alive = []
        for bird in self.birds:
            bird.x += bird.vx
            if -2 <= bird.x <= self.width + 2:
                alive.append(bird)
        self.birds = alive

    def _spawn_bird(self) -> None:
        from_left = self.rng.random() < 0.5
        speed = self.rng.uniform(0.6, 1.0)
        y = self.rng.uniform(0.3 * self.height, 0.7 * self.height)
        if from_left:
            self.birds.append(Bird(x=0.0, y=y, vx=speed))
        else:
            self.birds.append(Bird(x=float(self.width), y=y, vx=-speed))

    def _tick_seeds(self) -> None:
        remaining = []
        for seed in self.seeds:
            self._maybe_nudge(seed)
            seed.vy -= GRAVITY
            seed.vx += self.wind * 0.05
            seed.vx *= 0.98
            seed.vy = max(seed.vy, -0.5)
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
                seed.vx += self.rng.choice((-0.8, 0.8))
                seed.vy += 0.3
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

    def _cloud_colour(self, depth: float) -> str:
        if depth > 0.66:
            return self.palette.cloud_far
        if depth > 0.33:
            return self.palette.cloud_mid
        return self.palette.cloud_near

    def _cloud_glyph(self, depth: float) -> str:
        if depth > 0.66:
            return "."
        if depth > 0.33:
            return "~"
        return "o"

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
        bird_glyph = "v" if (self._tick_count // 4) % 2 == 0 else "^"
        seed_cells = {(int(s.x) % self.width, int(s.y)) for s in self.seeds}
        text = Text()
        for r in range(self.rows):
            cy = self.rows - 1 - r
            runs: list[list[str | None]] = []
            for cx in range(self.cols):
                ch, style = self._sample_cell(cx, cy, seed_cells, bird_glyph)
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
        self, cx: int, cy: int, seed_cells: set[tuple[int, int]], bird_glyph: str
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

        for bird in self.birds:
            if int(bird.x) // SUB_X == cx and int(bird.y) // SUB_Y == cy:
                return bird_glyph, self.palette.bird

        centre_x, centre_y = base_x + SUB_X / 2, base_y + SUB_Y / 2
        for cloud in self.clouds:
            dx = min(abs(centre_x - cloud.x), self.width - abs(centre_x - cloud.x))
            if dx <= cloud.w / 2 and abs(centre_y - cloud.y) <= 1.0:
                return self._cloud_glyph(cloud.depth), self._cloud_colour(cloud.depth)

        speckle = self._ground_speckle(cx, cy)
        if speckle is not None:
            return speckle, self.palette.sand_dot

        return " ", None
