"""
field.py — the answer strip's background simulation: sky, weather, cacti.

Responsibilities:
- Hold a small world (sky, clouds, wind, birds, a static mountain silhouette,
  and the settled cactus structure) in sub-cell resolution, two sub-cells per
  terminal cell in each axis.
- Advance the world one tick: drift clouds, wander the wind, fly and despawn
  birds, and fall seeds under gravity and wind until they anchor.
- Drop a seed into a column; anchor it to the floor or beside the structure,
  including the two "reverse pawn" diagonals below it.
- Render the world as a styled rich.text.Text, quadrant-sampling each
  terminal cell from its four sub-cells.

Pure Python: no persistence, no store, no Textual import.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from rich.text import Text

SUB_X = 2
SUB_Y = 2
GROUND_ROWS = 2  # terminal rows of flat ground in front of the mountains
GRAVITY = 0.04
QUADRANT = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"


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
    near: bool = False


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
    width: int = field(init=False)
    height: int = field(init=False)
    structure: set[tuple[int, int]] = field(default_factory=set)
    wind: float = 0.0
    seeds: list[Seed] = field(default_factory=list)
    birds: list[Bird] = field(default_factory=list)
    mountains: list[float] = field(default_factory=list, init=False)
    clouds: list[Cloud] = field(default_factory=list, init=False)
    _tick_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.width = self.cols * SUB_X
        self.height = self.rows * SUB_Y
        self.mountains = self._make_mountains(self.width)
        self.clouds = self._make_clouds()

    def reseed(self, seed: int) -> None:
        """Reset the rng and regenerate mountains/clouds from it, deterministically."""
        self.rng = random.Random(seed)
        self.mountains = self._make_mountains(self.width)
        self.clouds = self._make_clouds()

    def resize(self, cols: int, rows: int) -> None:
        """Keep the structure and mountains; re-spawn clouds inside the new bounds."""
        self.cols = cols
        self.rows = rows
        self.width = cols * SUB_X
        self.height = rows * SUB_Y
        self.mountains = self._resize_mountains(self.width)
        self.clouds = self._make_clouds()

    # ---- generation -----------------------------------------------------

    def _ground(self) -> float:
        """Top of the flat ground band, in sub-cells; mountains sit behind it."""
        return GROUND_ROWS * SUB_Y

    def _mountain_bounds(self) -> tuple[float, float]:
        ground = self._ground()
        return ground + 0.1 * self.height, ground + 0.4 * self.height

    def _make_mountains(self, width: int) -> list[float]:
        low, high = self._mountain_bounds()
        val = self.rng.uniform(low, high)
        walk = []
        for _ in range(width):
            val = max(low, min(high, val + self.rng.uniform(-0.5, 0.5)))
            walk.append(val)
        return walk

    def _resize_mountains(self, width: int) -> list[float]:
        low, high = self._mountain_bounds()
        walk = list(self.mountains[:width])
        val = walk[-1] if walk else self.rng.uniform(low, high)
        while len(walk) < width:
            val = max(low, min(high, val + self.rng.uniform(-0.5, 0.5)))
            walk.append(val)
        return walk

    def _make_clouds(self) -> list[Cloud]:
        clouds = []
        for _ in range(self.rng.randint(3, 5)):
            near = self.rng.random() < 0.5
            clouds.append(
                Cloud(
                    x=self.rng.uniform(0, self.width),
                    y=self.rng.uniform(0.6 * self.height, self.height),
                    w=self.rng.uniform(3, 6),
                    speed=0.4 if near else 0.15,
                    near=near,
                )
            )
        return clouds

    # ---- dropping ---------------------------------------------------------

    def drop(self, col: int) -> None:
        """Spawn a seed above column `col`. Several seeds may be in flight at once."""
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
        self.structure.add(cell)  # a duplicate cell just drops the seed, no error
        return True

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
        for i, (dx, dy) in enumerate(offsets):
            cell = (base_x + dx, base_y + dy)
            if cell in self.structure:
                struct_bits |= 1 << i
            if cell in seed_cells:
                seed_bits |= 1 << i
        if seed_bits and struct_bits:
            return QUADRANT[seed_bits | struct_bits], "green"
        if seed_bits:
            return QUADRANT[seed_bits], "bright_green"
        if struct_bits:
            return QUADRANT[struct_bits], "green"

        for bird in self.birds:
            if int(bird.x) // SUB_X == cx and int(bird.y) // SUB_Y == cy:
                return bird_glyph, "grey70"

        centre_x, centre_y = base_x + SUB_X / 2, base_y + SUB_Y / 2
        for cloud in self.clouds:
            dx = min(abs(centre_x - cloud.x), self.width - abs(centre_x - cloud.x))
            if dx <= cloud.w / 2 and abs(centre_y - cloud.y) <= 1.0:
                return ("▒", "grey78") if cloud.near else ("░", "grey62")

        if self.mountains:
            mountain_h = self.mountains[min(base_x, len(self.mountains) - 1)]
            if base_x + 1 < len(self.mountains):
                mountain_h = (mountain_h + self.mountains[base_x + 1]) / 2
            if self._ground() <= centre_y < mountain_h:
                return "▓", "grey30"

        return " ", None
