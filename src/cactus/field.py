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
  including the two "reverse pawn" diagonals below it (under dots, anywhere
  within `dot_latch` sub-cells at or below it, then snapped onto the pile by
  `_snap`). Count every drop, so
  the structure can carry age in decisions rather than in time. Under
  `pile_settle == "drop"` a shelf perched on a diagonal settles at most one
  row, and only onto support (`_settle`), and no piece is left floating:
  a component with no 8-connected path to the ground drops rigidly onto
  the pile (`_drop_floating`, `drop_floaters`). A seed feels world wind x
  `seed_wind`, never a deck's `wind_scale` (`seed_wind()`). A fall takes
  `LANDING_SECONDS` (12 s). On top of the wind, each clump carries its own
  random lateral gust (`_advance_gust`): a target jumping to a fresh random
  value in +-`gust_speed` columns/s after a random wait of mean
  `gust_period`, eased toward quickly — pachinko-like knocks, not an
  oscillation.
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
- Charge (hidden rule, no UI text): a falling clump gains +1 charge on each
  clear-sky-to-cloud entry (once per entry, not per frame spent inside one),
  and under `seed_mass == "accrete"` `accrete_count` members grown as a rod
  off its tip (`accrete_shape` `rod`) or on any side/diagonal neighbour,
  outer cells and the tip favoured (`branch`, default), plus an `accrete_spin` kick of random sign; +1 charge per
  distinct bird it shares a terminal
  cell with; landing bursts `charge` single-member clumps only if the clump
  touched at least one bird (`birds_hit`), spawned just above the pile top
  and sent sideways with a small downward `vy`, never up (`bounty=False`,
  so they can never re-collect and cascade). Every frame a clump is inside
  a cloud, each member calls `sky.scatter` once at its sky-pixel position,
  pushing the cloud aside. Cloud sampling reads the cached glyph grid from
  the last `render()` (`World.cloud_at`/`self._sky_cells`), never the sky
  engine directly.
- Perf (v6f): `_seed_splat_canvas`/`_pile_splat_canvas` also return the set of
  terminal cells they actually touched, so `_sample_cell` only ever asks the
  (otherwise empty) splat canvas about a cell in that set — a frame with no
  seeds falling never calls it at all. `World.apply_sky_config` swaps a new
  `SkyConfig` into the running sky, rebuilding it as the other engine class
  when `sky_engine` itself changed (`sky.apply` alone can only retune the
  engine already running). `run_bench()` (`cactus sky --bench`) times 50
  frames of a 100x20, 3-seed world and prints the per-step breakdown.
- Cloud fade (v8, `SkyConfig.cloud_fade`): `_fade_sky` gives each sky cell a
  presence that climbs while lit and sinks once cleared, blending its colour
  from `Palette.fade_from` toward its tone and holding the last glyph while
  it fades out; blank rows pass through, blends are cached in 64 steps.

Pure Python: no persistence, no store, no Textual import.
"""

from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field

from rich.text import Text

from .sky import PX_X, PX_Y, PuffSky, Sky, SkyConfig, TextureSky, atmospheric_colour, make_sky, _lerp_hex, _ordered_dither

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
# takes the same time regardless of the field's size or the sampling rate.
# Sped up 5x (60 s -> 12 s); GRAVITY rose 25x with it (acceleration scales
# as 1/T^2), so terminal velocity still arrives within the first ~8% of a fall.
TICK_SECONDS = 0.1
LANDING_SECONDS = 12.0
GRAVITY = 5.0  # sub-cells/s^2: reaches terminal velocity within about a second
# How much wind nudges a falling seed's vx, per second, against
# SEED_DRAG_THETA's decay. `SEED_WIND_COLS_PER_UNIT` is what a full fall
# actually drifts per unit of multiplier; recalibrate it if either changes.
WIND_COUPLING = 0.08
# Columns of mean drift one unit of raw-wind multiplier gives a falling
# seed over a full fall (measured at 120 columns, 30 rows, gusts off, after
# the 12 s fall): turns `SkyConfig.seed_wind`, which is in columns, into a
# multiplier.
SEED_WIND_COLS_PER_UNIT = 0.55
# Random lateral gusts (`SkyConfig.gust_speed`/`gust_period`): each clump's
# own gust target jumps at random moments; its gust velocity eases toward
# the target with this time constant, seconds — quick enough to read as a
# knock, not a hard snap.
GUST_TAU = 0.15
GUST_MIN_LEG = 0.2  # seconds: floor on the random time between two gusts
# `_advance_seeds` sub-steps a frame so no clump moves farther than this,
# sub-cells, per step (the anchor test only looks one sub-cell around), up
# to a cap on the sub-step count.
SEED_MAX_STEP = 1.0
SEED_MAX_SUBSTEPS = 32
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
FLOCK_MAX_ALIVE = 3  # default of `SkyConfig.bird_max` (v8: the config is what `advance` reads)
FLOCK_SPAWN_P = 0.02  # default of `SkyConfig.bird_rate`, per second, while fewer than bird_max are alive
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

# The cells a landing member may rest against: directly below, either side,
# and the two "reverse pawn" diagonals below. Blocks style lands on exactly
# these; dots style also lands within `SkyConfig.dot_latch` and then snaps
# until one of these holds (`World._snap`).
SUPPORT_OFFSETS = ((0, -1), (-1, 0), (1, 0), (-1, -1), (1, -1))
# Safety cap on `World._drop_floating`'s passes: each pass lowers every
# floating piece at least one row, so a real pile settles in a handful.
DROP_PASSES = 64

# Charge (hidden rule): a clump gains +1 charge (and `accrete_count` members,
# cloud mass) on each clear-sky-to-cloud entry, and +1 charge per distinct bird it shares
# a terminal cell with while falling. Landing bursts `charge` single-member
# clumps sideways off the pile top, but only if the clump touched a bird;
# `bounty=False` on those keeps the cascade from ever restarting. Every frame
# a clump spends inside a cloud, each member scatters the sky around it.
EXPLODE_VX_RANGE = (2.0, 5.0)  # sub-cells/s magnitude, random sign
EXPLODE_VY = 0.5  # sub-cells/s, downward (applied as -EXPLODE_VY: seeds fall toward y=0)
EXPLODE_LIFT = 2.0  # sub-cells above the landing clump's top member, so a burst clears the pile
SCATTER_RADIUS = 6.0  # sky pixels a falling member pushes cloud density out by
SCATTER_STRENGTH = 0.6  # share of density within that radius it pushes, per frame
# A multi-member clump turns as one rigid body: every member position is its
# offset rotated by the clump's `angle` (`World._member_offset`). Cloud
# accretion kicks `spin` (`SkyConfig.accrete_spin`); this exponential damping,
# per second and on multi-member clumps only, lets a rod settle into a slow
# turn instead of a blur.
ACCRETE_SPIN_DAMP = 0.3


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
    fade_from: str = "#262a36"  # where a lighting sky cell's colour starts (v8 `cloud_fade`)
    ground_line_near: str = "grey42"
    ground_line_far: str = "grey30"


MONO_PLUS = Palette()


@dataclass
class Member:
    """One seed's place inside its clump's local frame (v6e): a fixed offset
    from the clump's centre and a tumble angle baked in at drop or merge —
    the clump's own `angle` is added to it fresh every frame, so the member
    still tumbles even after its offset is frozen. In a multi-member clump
    the offset itself is also rotated by the clump's `angle` wherever it
    becomes a position (`World._member_offset`)."""

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
    angle: float = 0.0  # radians, added to every member's own baked angle; rotates offsets when >1 member
    spin: float = 0.0  # radians/second, drawn at drop, kicked by accretion; see SEED_SPIN_RANGE, ACCRETE_SPIN_DAMP
    members: list[Member] = field(default_factory=lambda: [Member()])
    # Charge (hidden rule): `charge` counts cloud entries plus distinct birds
    # touched; `in_cloud` tracks the clear-to-cloud edge so a long pass through
    # one cloud counts once; `bounty=False` on an exploded seed (see
    # `World._explode`) means it never collects, so an explosion can't
    # cascade; `birds_hit` is the set of `id(bird)` already credited, and a
    # landing bursts only when it is non-empty.
    charge: int = 0
    in_cloud: bool = False
    bounty: bool = True
    birds_hit: set = field(default_factory=set)
    # Random gust (`World._advance_gust`): `gust_vx` is the share of `vx` the
    # gust owns, easing toward `gust_target`, which jumps to a fresh random
    # value when `gust_left` seconds run out — 0 on a new clump, so the
    # first frame draws its first gust.
    gust_vx: float = 0.0
    gust_target: float = 0.0
    gust_left: float = 0.0


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
    # Charge (hidden rule): the sky's rendered glyph grid, cached each
    # `render()` for `cloud_at` — engine-agnostic, and `None` before the
    # first render (headless `advance()` in that case awards nothing).
    _sky_cells: list[list[tuple[str, str | None]]] | None = field(default=None, init=False)
    # `_fade_sky` state: per sky row `(alphas, glyphs, colours, live)`,
    # `live` true while any alpha in the row is above 0.
    _fade_cells: list[list] | None = field(default=None, init=False)
    _fade_tint: dict[tuple[str, str, int], str] = field(default_factory=dict, init=False)
    _frame_dt: float = field(default=0.0, init=False)
    # The `pile_settle` last applied, so `apply_sky_config` sees a switch to
    # "drop" even when the tuning overlay mutated the live config in place.
    _pile_settle: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.width = self.cols * SUB_X
        self.height = self.rows * SUB_Y
        self.sky = make_sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette, self.sky_config)
        self._pile_settle = self.sky.config.pile_settle
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
        Rebuilding re-bakes the weather from scratch, same as a resize.
        Switching `pile_settle` to "drop" sweeps the pile (`drop_floaters`)."""
        if config.sky_engine != getattr(self.sky, "ENGINE", "fluid"):
            self.sky = make_sky(self.cols, self.rows - GROUND_ROWS, self.rng, self.palette, config)
        else:
            self.sky.apply(config)
        if config.pile_settle == "drop" and self._pile_settle != "drop":
            self.drop_floaters()
        self._pile_settle = config.pile_settle

    def resize(self, cols: int, rows: int) -> None:
        """Keep the structure; rebake the sky to the new bounds."""
        self.cols = cols
        self.rows = rows
        self.width = cols * SUB_X
        self.height = rows * SUB_Y
        self.sky.resize(cols, rows - GROUND_ROWS)
        self._set_terminal_vy()

    # ---- dropping ---------------------------------------------------------

    def seed_wind(self) -> float:
        """The wind a falling seed feels. `SkyConfig.seed_wind` is in
        columns — the mean drift over a full fall at typical wind — so it
        converts through `SEED_WIND_COLS_PER_UNIT`, measured over the 12 s
        fall with gusts off: a multiplier of 1 on the raw world wind drifts
        ~0.55 columns, and drift is linear in it (1.0 / 1.9 / 4.9 / 9.7 /
        19.5 columns at lever 1 / 2 / 5 / 10 / 20). No deck's `wind_scale` applies: the puffs engine ignores
        wind and texture reads only `shear_base`."""
        return self.wind * self.sky.config.seed_wind / SEED_WIND_COLS_PER_UNIT

    def drop(self, col: int) -> None:
        """Spawn a seed above column `col`. Several seeds may be in flight at once."""
        self.drops += 1
        x = (col * SUB_X + SUB_X / 2 + self.rng.uniform(-0.5, 0.5)) % self.width
        spin = self.rng.uniform(*SEED_SPIN_RANGE) * self.rng.choice((-1.0, 1.0))
        angle = self.rng.uniform(0.0, 2 * math.pi)
        self.seeds.append(Clump(x=x, y=float(self.height - 1), vx=self.seed_wind(), vy=0.0, angle=angle, spin=spin))

    # ---- advance ------------------------------------------------------

    def tick(self) -> None:
        """Thin wrapper for tests: one frame of `TICK_SECONDS` wall time."""
        self.advance(TICK_SECONDS)

    def advance(self, dt: float) -> None:
        self._frame_dt += dt
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
        cfg = self.sky.config
        if len(self._flocks) < cfg.bird_max and self.rng.random() < cfg.bird_rate * dt:
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

    def bird_bands(self) -> tuple[str, ...]:
        """The depth bands `SkyConfig.birds` lets a flock spawn in (v8):
        `all` is every band, `none` is empty, a name or a `+`-joined pair
        is exactly those."""
        choice = self.sky.config.birds
        if choice == "all":
            return tuple(DEPTH_BAND)
        if choice == "none":
            return ()
        return tuple(b for b in choice.split("+") if b in DEPTH_BAND)

    def _spawn_flock(self) -> None:
        bands = self.bird_bands()
        if not bands:
            return
        band = self.rng.choice(bands)
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
        """Seed physics for one frame, split into sub-steps short enough
        that no clump moves more than `SEED_MAX_STEP` sub-cells in one: a
        12 s fall on a tall field, a gust, or a low fps would otherwise
        carry a seed past the pile cell it should anchor beside. Charge,
        merge and landing run every sub-step; the cloud scatter runs on the
        last only, so it stays once per frame. A landing's burst joins the
        world once the frame's sub-steps finish, so it first moves next
        frame, as before sub-steps."""
        cfg = self.sky.config
        gust_speed = cfg.gust_speed * SUB_X
        speed = max([abs(self.terminal_vy)] + [max(abs(c.vx) + gust_speed, abs(c.vy)) for c in self.seeds])
        steps = max(1, min(SEED_MAX_SUBSTEPS, math.ceil(speed * dt / SEED_MAX_STEP)))
        h = dt / steps
        exploded: list[Clump] = []
        for i in range(steps):
            exploded.extend(self._step_seeds(h, scatter=i == steps - 1))
        self.seeds.extend(exploded)

    def _step_seeds(self, dt: float, scatter: bool = True) -> list[Clump]:
        """One sub-step of `_advance_seeds`: move, charge, merge, land.
        Returns the bursts of any landing, not yet in `self.seeds`."""
        wind = self.seed_wind()
        cfg = self.sky.config
        gust_speed = cfg.gust_speed * SUB_X
        for clump in self.seeds:
            self._maybe_nudge(clump)
            n = len(clump.members)
            clump.vy -= GRAVITY * dt
            # Wind and drag act on the non-gust share of vx; the gust share
            # eases on its own, so neither washes the other out.
            base = clump.vx - clump.gust_vx
            base += wind * WIND_COUPLING * dt / math.sqrt(n)
            base *= math.exp(-SEED_DRAG_THETA * dt)
            self._advance_gust(clump, dt, gust_speed, cfg.gust_period)
            clump.vx = base + clump.gust_vx
            clump.vy = max(clump.vy, self.terminal_vy)
            if n > 1:
                clump.spin *= math.exp(-ACCRETE_SPIN_DAMP * dt)
            clump.angle += (clump.spin + wind * SEED_WOBBLE_PER_WIND) * dt
            clump.x = (clump.x + clump.vx * dt) % self.width
            clump.y += clump.vy * dt
        self._collect_charge(scatter)
        self._merge_clumps()
        remaining = []
        exploded: list[Clump] = []
        for clump in self.seeds:
            if self._anchor(clump, exploded):
                continue
            remaining.append(clump)
        self.seeds = remaining
        return exploded

    def _advance_gust(self, clump: Clump, dt: float, gust_speed: float, gust_period: float) -> None:
        """Random lateral knocks, pachinko-like: when `gust_left` runs out
        the target jumps to uniform(-1, 1) x `gust_speed` sub-cells/s — no
        forced sign flip, so a seed may be pushed the same way twice,
        reversed, or nearly stilled — and the next jump waits an
        exponential time of mean `gust_period`, at least `GUST_MIN_LEG`.
        `gust_vx` eases toward the target with `GUST_TAU`. `gust_speed` 0
        draws nothing and eases any gust left over back to 0."""
        if gust_speed <= 0.0:
            clump.gust_target = 0.0
        else:
            clump.gust_left -= dt
            if clump.gust_left <= 0.0:
                clump.gust_target = self.rng.uniform(-1.0, 1.0) * gust_speed
                clump.gust_left = max(GUST_MIN_LEG, self.rng.expovariate(1.0 / max(gust_period, 1e-6)))
        ease = math.exp(-dt / GUST_TAU)
        clump.gust_vx = clump.gust_target + (clump.gust_vx - clump.gust_target) * ease

    # ---- charge (hidden rule) ----------------------------------------------

    def _member_offset(self, clump: Clump, member: Member) -> tuple[float, float]:
        """`member`'s offset from the clump centre, rotated by the clump's
        current `angle` — the one place a member becomes a position, so a
        multi-member clump turns as a rigid body everywhere it is read. A
        single-member clump returns its offset unrotated."""
        if len(clump.members) == 1:
            return member.dx, member.dy
        c, s = math.cos(clump.angle), math.sin(clump.angle)
        return member.dx * c - member.dy * s, member.dx * s + member.dy * c

    def _member_cell(self, clump: Clump, member: Member) -> tuple[int, int]:
        """`member`'s terminal `(col, row)`, `row` from the bottom like
        `structure`/`render` — the same SUB_X/SUB_Y conversion `_anchor` and
        `render` use, just one step coarser (sub-cell to terminal cell)."""
        dx, dy = self._member_offset(clump, member)
        x = (clump.x + dx) % self.width
        y = clump.y + dy
        return int(x) // SUB_X, int(y) // SUB_Y

    def cloud_at(self, col: int, row_from_bottom: int) -> bool:
        """True when the cached rendered sky glyph at terminal `(col,
        row_from_bottom)` is not blank — any speck, dither, stroke, or core
        counts as cloud. Reads `self._sky_cells`, the grid `render()` cached
        last frame, not the sky engine directly; before the first render, or
        inside the ground band, always False."""
        if self._sky_cells is None or row_from_bottom < GROUND_ROWS:
            return False
        r = self.rows - 1 - row_from_bottom
        if r < 0 or r >= len(self._sky_cells):
            return False
        cells = self._sky_cells[r]
        col %= self.cols
        if col >= len(cells):
            return False
        glyph, _ = cells[col]
        return glyph != " "

    def _grow_clump(self, clump: Clump) -> None:
        """Cloud mass: `accrete_count` new `Member`s grown in the clump's own
        frame, shaped by `accrete_shape`. `rod`: the tip is the member
        farthest from the centre; each new block goes one step past it along
        the tip's dominant axis away from the centre (a tip at the centre
        picks a random horizontal side), so repeated accretion extends one
        arm rather than a blob. `branch`: `_grow_branch`."""
        if self.sky.config.accrete_shape == "branch":
            self._grow_branch(clump)
            return
        tip = max(clump.members, key=lambda m: m.dx * m.dx + m.dy * m.dy)
        if tip.dx == 0.0 and tip.dy == 0.0:
            step = (self.rng.choice((-1.0, 1.0)), 0.0)
        elif abs(tip.dx) >= abs(tip.dy):
            step = (math.copysign(1.0, tip.dx), 0.0)
        else:
            step = (0.0, math.copysign(1.0, tip.dy))
        x, y = tip.dx, tip.dy
        for _ in range(self.sky.config.accrete_count):
            x, y = x + step[0], y + step[1]
            clump.members.append(Member(dx=x, dy=y, angle=self.rng.uniform(0.0, 2 * math.pi)))

    def _grow_branch(self, clump: Clump) -> None:
        """`accrete_shape == "branch"`: each new block takes a free cell among
        the 8 neighbours (sides and diagonals) of an existing member, in the
        clump's unrotated frame. A candidate weighs 1 + its distance from the
        centre, doubled when offered by the current tip (the member farthest
        from centre), so the shape still reaches outward into an arm. A cell
        offered by several members sums their weights; an occupied offset is
        never picked."""
        for _ in range(self.sky.config.accrete_count):
            taken = {(round(m.dx), round(m.dy)) for m in clump.members}
            tip = max(clump.members, key=lambda m: m.dx * m.dx + m.dy * m.dy)
            weights: dict[tuple[float, float], float] = {}
            for m in clump.members:
                scale = 2.0 if m is tip else 1.0
                for ox in (-1.0, 0.0, 1.0):
                    for oy in (-1.0, 0.0, 1.0):
                        cx, cy = m.dx + ox, m.dy + oy
                        if (round(cx), round(cy)) in taken:
                            continue
                        w = scale * (1.0 + math.hypot(cx, cy))
                        weights[(cx, cy)] = weights.get((cx, cy), 0.0) + w
            cells = list(weights)
            x, y = self.rng.choices(cells, weights=[weights[c] for c in cells])[0]
            clump.members.append(Member(dx=x, dy=y, angle=self.rng.uniform(0.0, 2 * math.pi)))

    def _collect_charge(self, scatter: bool = True) -> None:
        """Right after clumps move, before landing checks: cloud-entry and
        bird-touch charge for every bounty-bearing falling clump. `scatter`
        False skips the cloud push (every sub-step but a frame's last)."""
        for clump in self.seeds:
            if not clump.bounty:
                continue
            entered: Member | None = None
            for m in clump.members:
                col, row = self._member_cell(clump, m)
                if self.cloud_at(col, row):
                    entered = m
                    break
            if entered is not None and not clump.in_cloud:
                clump.charge += 1
                if self.sky.config.seed_mass == "accrete":
                    self._grow_clump(clump)
                    clump.spin += self.sky.config.accrete_spin * self.rng.choice((-1.0, 1.0))
            clump.in_cloud = entered is not None
            if clump.in_cloud and scatter:
                self._scatter_sky(clump)

            for bird in self.birds:
                bid = id(bird)
                if bid in clump.birds_hit:
                    continue
                bird_cell = (int(bird.x) // SUB_X, int(bird.y) // SUB_Y)
                for m in clump.members:
                    if self._member_cell(clump, m) == bird_cell:
                        clump.charge += 1
                        clump.birds_hit.add(bid)
                        break

    def _scatter_sky(self, clump: Clump) -> None:
        """Every frame a clump is inside a cloud: each member pushes the sky
        aside once, at its own position in the sky's top-down pixel space
        (`PX_X` by `PX_Y` per terminal cell, centred in the cell). A member
        below the sky band (in the ground rows) is skipped."""
        sky_rows = self.rows - GROUND_ROWS
        for m in clump.members:
            col, row_from_bottom = self._member_cell(clump, m)
            r = self.rows - 1 - row_from_bottom  # screen row, top-down, same as `cloud_at`
            if r < 0 or r >= sky_rows:
                continue
            px = col * PX_X + 1
            py = r * PX_Y + PX_Y // 2
            self.sky.scatter(px, py, SCATTER_RADIUS, SCATTER_STRENGTH)

    def _explode(self, clump: Clump) -> list[Clump]:
        """Landing: `clump.charge` single-member clumps spawned at the
        landing clump's centre column, `EXPLODE_LIFT` above its top member
        so they clear the pile, and sent sideways — random sign, magnitude
        from `EXPLODE_VX_RANGE` — with `vy` a small downward `-EXPLODE_VY`
        (seeds fall toward y=0), never up. Gravity and drag skid them off
        the pile to land beside it under the ordinary fall code.
        `bounty=False`: an exploded seed never collects charge, so an
        explosion cannot cascade. Each burst seed starts its own fresh gust
        state (the `Clump` defaults), drawing its first gust next frame."""
        top = max(clump.y + self._member_offset(clump, m)[1] for m in clump.members)
        y = top + EXPLODE_LIFT
        seeds = []
        for _ in range(clump.charge):
            vx = self.rng.uniform(*EXPLODE_VX_RANGE) * self.rng.choice((-1.0, 1.0))
            angle = self.rng.uniform(0.0, 2 * math.pi)
            spin = self.rng.uniform(*SEED_SPIN_RANGE) * self.rng.choice((-1.0, 1.0))
            seeds.append(Clump(x=clump.x, y=y, vx=vx, vy=-EXPLODE_VY, angle=angle, spin=spin, bounty=False))
        return seeds

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
        b_pos = [(b.x + dx, b.y + dy) for dx, dy in (self._member_offset(b, mb) for mb in b.members)]
        for ma in a.members:
            adx, ady = self._member_offset(a, ma)
            ax, ay = a.x + adx, a.y + ady
            for bx, by in b_pos:
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
        keep: offsets are baked already rotated, and the new clump starts
        at `angle` 0. The gust state is the larger clump's (`a` on a tie):
        the mass-weighted part of `vx` is the non-gust share only, and the
        kept gust's `gust_vx` rides on top of it. Charge adds, birds hit
        unite, and `bounty` survives only if both had it."""
        na, nb = len(a.members), len(b.members)
        total = na + nb
        big = a if na >= nb else b
        x = (a.x * na + b.x * nb) / total
        y = (a.y * na + b.y * nb) / total
        vx = ((a.vx - a.gust_vx) * na + (b.vx - b.gust_vx) * nb) / total + big.gust_vx
        vy = (a.vy * na + b.vy * nb) / total
        spin = (a.spin + b.spin) / 2.0 / total
        members: list[Member] = []
        for clump in (a, b):
            for m in clump.members:
                mdx, mdy = self._member_offset(clump, m)
                members.append(Member(
                    dx=clump.x + mdx - x,
                    dy=clump.y + mdy - y,
                    angle=clump.angle + m.angle,
                ))
        # Charge state carries through (v8): the charges add, the birds hit
        # unite, and a merge with a burst seed (`bounty=False`) stays a burst
        # seed — otherwise two burst seeds merging could charge again and
        # cascade, the one thing `bounty` exists to block.
        return Clump(
            x=x, y=y, vx=vx, vy=vy, nudged=a.nudged or b.nudged, spin=spin, members=members,
            gust_vx=big.gust_vx, gust_target=big.gust_target, gust_left=big.gust_left,
            charge=a.charge + b.charge, in_cloud=a.in_cloud or b.in_cloud,
            bounty=a.bounty and b.bounty, birds_hit=a.birds_hit | b.birds_hit,
        )

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

    def _anchor(self, clump: Clump, exploded: list[Clump]) -> bool:
        """Land the whole clump when any member's cell floors or sits beside
        the structure, then add every member's own cell to the structure
        (an already-taken cell just re-stamps its age). A landing with
        charge that touched at least one bird (`birds_hit`) appends `charge`
        exploded clumps (see `_explode`) to `exploded`; cloud charge alone
        never bursts.

        Under `pile_style == "dots"` a member also lands when any structure
        cell at its height or below lies within `dot_latch` sub-cells
        (Euclidean, x wrapped) — a dot looks bigger than its sub-cell — and
        the clump is then snapped onto the pile (`_snap`) before `_settle`."""
        offsets = [self._member_offset(clump, m) for m in clump.members]
        dots = self.sky.config.pile_style == "dots"
        reach = self._latch_offsets() if dots else ()
        lands = False
        for dx, dy in offsets:
            cx, cy = int(clump.x + dx) % self.width, int(clump.y + dy)
            if cy <= 0:
                lands = True
                break
            w = self.width
            neighbours = [((cx + nx) % w, cy + ny) for nx, ny in SUPPORT_OFFSETS]
            if any(n in self.structure for n in neighbours):
                lands = True
                break
            if any(((cx + ox) % w, cy + oy) in self.structure for ox, oy in reach):
                lands = True
                break
        if not lands:
            return False
        # Wrap x like every other horizontal read: a clump straddling the
        # seam must not land a cell at cx -1 or cx >= width.
        cells = [(int(clump.x + dx) % self.width, max(int(clump.y + dy), 0)) for dx, dy in offsets]
        if dots:
            cells = self._snap(cells, reach)
        if self.sky.config.pile_settle == "drop":
            cells = self._settle(cells)
        for cell in cells:
            self.structure[cell] = self.drops
        if self.sky.config.pile_settle == "drop":
            self._drop_floating(cells)
        self.landed_since_save += 1
        if clump.bounty and clump.charge and clump.birds_hit:
            exploded.extend(self._explode(clump))
        return True

    def _latch_offsets(self) -> list[tuple[int, int]]:
        """Every integer `(ox, oy)` within `dot_latch` sub-cells of a member,
        at its height or below (`oy <= 0`) — the box of radius
        `ceil(dot_latch)` filtered to the disc, nearest first."""
        r = self.sky.config.dot_latch
        n = math.ceil(r)
        box = [(ox, oy) for ox in range(-n, n + 1) for oy in range(-n, 1) if ox * ox + oy * oy <= r * r]
        return sorted(box, key=lambda o: o[0] * o[0] + o[1] * o[1])

    def _snap(self, cells: list[tuple[int, int]], reach: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Join a dots-style landing to the pile: a clump that latched from
        a distance keeps its shape and shifts by the shortest integer vector
        (Manhattan) that puts one of its cells on the ground or beside/atop
        the structure by the same `SUPPORT_OFFSETS` rule blocks land on —
        never up, never into a taken cell. Ties prefer down, then sideways
        toward the nearest supporting cell. A clump already joined lands
        as hit; one with no free shift (none found) lands as hit too."""
        w = self.width

        def joined(shifted: list[tuple[int, int]]) -> bool:
            return any(
                cy == 0 or any(((cx + nx) % w, cy + ny) in self.structure for nx, ny in SUPPORT_OFFSETS)
                for cx, cy in shifted
            )

        if joined(cells):
            return cells
        # Which way the nearest latched cell lies: `reach` is nearest first.
        toward, best = 0, None
        for cx, cy in cells:
            for ox, oy in reach:
                if ((cx + ox) % w, cy + oy) in self.structure:
                    d = ox * ox + oy * oy
                    if best is None or d < best:
                        toward, best = (ox > 0) - (ox < 0), d
                    break
        n = math.ceil(self.sky.config.dot_latch)
        shifts = sorted(
            ((sx, sy) for sx in range(-n, n + 1) for sy in range(-n, 1) if (sx, sy) != (0, 0)),
            key=lambda s: (abs(s[0]) + abs(s[1]), s[1], s[0] * toward < 0, abs(s[0]), s[0]),
        )
        for sx, sy in shifts:
            shifted = [((cx + sx) % w, cy + sy) for cx, cy in cells]
            if any(c[1] < 0 or c in self.structure for c in shifted):
                continue
            if joined(shifted):
                return shifted
        return cells

    def _fade_sky(self, grid: list[list[tuple[str, str | None]]]) -> list[list[tuple[str, str | None]]]:
        """Smooth the sky between frames (v8, `cloud_fade`): every cell keeps
        a presence `a` in [0, 1] that climbs while the engine lights it and
        sinks after it clears, `cloud_fade` seconds end to end. The drawn
        colour is `fade_from` blended toward the cell's tone by `a`; a cell
        the engine just cleared keeps drawing its last glyph while `a`
        sinks, so nothing pops in or out. `cloud_fade == 0` returns `grid`
        untouched. Uses the wall time `advance` accumulated since the last
        render (`_frame_dt`), then zeroes it.

        Cheap per frame: a row with no presence left and an all-blank source
        passes through as the source row itself, cells untouched; inside a
        row, state is three flat lists and the output row is copied from the
        source only once a cell differs from it. The blend is quantised to
        64 steps (`round(a * 64)`, one step per frame or finer at 30 fps)
        and cached per (`fade_from`, tone, step) in `_fade_tint`, so
        `_lerp_hex` runs at most 65 times per tone."""
        fade = self.sky.config.cloud_fade
        dt, self._frame_dt = self._frame_dt, 0.0
        if fade <= 0.0:
            self._fade_cells = None
            return grid
        rows, cols = len(grid), (len(grid[0]) if grid else 0)
        state = self._fade_cells
        if state is None or len(state) != rows or (rows and len(state[0][0]) != cols):
            state = [[[0.0] * cols, [" "] * cols, [None] * cols, False] for _ in range(rows)]
            self._fade_cells = state
        step = dt / fade
        start = self.palette.fade_from
        tint = self._fade_tint
        if len(tint) > 16384:
            tint.clear()
        blank = (" ", None)
        out: list[list[tuple[str, str | None]]] = []
        for r in range(rows):
            src, st = grid[r], state[r]
            if not st[3] and src.count(blank) == cols:
                out.append(src)
                continue
            alphas, glyphs, colours = st[0], st[1], st[2]
            row: list[tuple[str, str | None]] | None = None
            live = False
            for c in range(cols):
                cell = src[c]
                glyph, colour = cell
                a = alphas[c]
                if glyph != " ":
                    if a < 1.0:
                        a += step
                        if a > 1.0:
                            a = 1.0
                        alphas[c] = a
                    glyphs[c] = glyph
                    colours[c] = colour
                    live = True
                    if a >= 1.0 or colour is None:
                        continue
                elif a > 0.0:
                    a -= step
                    if a < 0.0:
                        a = 0.0
                    alphas[c] = a
                    colour = colours[c]
                    if a <= 0.0 or colour is None:
                        if cell != blank:
                            if row is None:
                                row = list(src)
                            row[c] = blank
                        continue
                    live = True
                    glyph = glyphs[c]
                else:
                    if cell != blank:
                        if row is None:
                            row = list(src)
                        row[c] = blank
                    continue
                q = round(a * 64)
                key = (start, colour, q)
                shade = tint.get(key)
                if shade is None:
                    shade = tint[key] = _lerp_hex(start, colour, q / 64)
                if row is None:
                    row = list(src)
                row[c] = (glyph, shade)
            st[3] = live
            out.append(src if row is None else row)
        return out

    def _settle(self, cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """The arm adjustment (v8, `pile_settle == "drop"`): a landed shelf
        — two or more blocks side by side in the clump's lowest row — that
        rests only on a diagonal (nothing directly under any of its cells)
        drops exactly one row, and only when that row sets at least one
        shelf cell directly on the ground or a block and no target cell is
        taken; otherwise it keeps the landing as hit. `(0,0) (1,0) (2,1)
        (3,1)` becomes a flat `(0,0) (1,0) (2,0) (3,0)`. It never slides a
        shelf down a pile's side: a multi-row drop used to carry overhangs
        toward the ground. A lone block keeps its diagonal perch: the jar
        is the shelf, not the step."""
        low = min(cy for _, cy in cells)
        bottom = sorted(cx for cx, cy in cells if cy == low)
        shelf = any(b - a == 1 for a, b in zip(bottom, bottom[1:]))
        if not shelf or low == 0:
            return cells
        if any((cx, low - 1) in self.structure for cx in bottom):
            return cells
        dropped = [(cx, cy - 1) for cx, cy in cells]
        if any(c in self.structure for c in dropped):
            return cells
        if low - 1 == 0 or any((cx, low - 2) in self.structure for cx in bottom):
            return dropped
        return cells

    def drop_floaters(self) -> None:
        """Sweep the whole structure for floating components and drop each
        onto the pile (`_drop_floating`) — for a garden loaded from disk or
        a switch to `pile_settle == "drop"`, where any cell may float."""
        self._drop_floating(list(self.structure))

    def _drop_floating(self, cells: list[tuple[int, int]]) -> None:
        """The `pile_settle == "drop"` guarantee: no component of the
        structure (8-connected, x wrapped) floats. Every component holding
        one of `cells` that has no cell at `cy <= 0` drops rigidly
        (`_drop_component`) and merges where it rests; lowest first, then
        again over the moved cells, since a piece can land on another
        floater — to a fixed point, capped at `DROP_PASSES`. A landing only
        adds cells, so only the landed cells' own component can newly float."""
        pending = cells
        for _ in range(DROP_PASSES):
            seen: set[tuple[int, int]] = set()
            floating: list[set[tuple[int, int]]] = []
            for cell in pending:
                if cell in seen or cell not in self.structure:
                    continue
                comp, grounded = self._component(cell)
                seen |= comp
                if not grounded:
                    floating.append(comp)
            if not floating:
                return
            floating.sort(key=lambda comp: min(cy for _, cy in comp))
            pending = []
            for comp in floating:
                pending.extend(self._drop_component(comp))

    def _neighbours8(self, cx: int, cy: int) -> list[tuple[int, int]]:
        """The 8 cells around `(cx, cy)`, x wrapped at `width`. A cell kept
        outside the width (a garden from a wider field, `garden.load_into`)
        reads its neighbours unwrapped, and an in-width cell at the seam also
        reaches the unwrapped column past it, so such cells stay attached."""
        w = self.width
        inside = 0 <= cx < w
        out = []
        for nx in (-1, 0, 1):
            x = cx + nx
            xs = (x % w, x) if inside and x % w != x else ((x % w,) if inside else (x,))
            for ny in (-1, 0, 1):
                if nx or ny:
                    out.extend((xx, cy + ny) for xx in xs)
        return out

    def _component(self, start: tuple[int, int]) -> tuple[set[tuple[int, int]], bool]:
        """`start`'s connected component of the structure and whether it is
        grounded (a cell at `cy <= 0`). Best-first, lowest row first, and it
        stops at the first grounded cell — so a grounded component returns
        early with a partial set; a floating one is always returned whole."""
        heap = [(start[1], start)]
        comp = {start}
        while heap:
            cy, cell = heapq.heappop(heap)
            if cy <= 0:
                return comp, True
            for n in self._neighbours8(*cell):
                if n not in comp and n in self.structure:
                    comp.add(n)
                    heapq.heappush(heap, (n[1], n))
        return comp, False

    def _drop_component(self, comp: set[tuple[int, int]]) -> list[tuple[int, int]]:
        """Lower `comp` rigidly, one row at a time, until a cell reaches
        `cy == 0` or sits directly above another component's cell (the next
        row would overlap it). Each cell keeps its age stamp. Returns the
        cells where it came to rest."""
        ages = {cell: self.structure.pop(cell) for cell in comp}
        low = min(cy for _, cy in comp)
        k = 0
        while low - k > 0 and not any((cx, cy - k - 1) in self.structure for cx, cy in comp):
            k += 1
        moved = []
        for (cx, cy), age in ages.items():
            self.structure[(cx, cy - k)] = age
            moved.append((cx, cy - k))
        return moved

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
                dx, dy = self._member_offset(clump, m)
                bx = (clump.x + dx) * (PX_X / SUB_X)
                by = (clump.y + dy) * (PX_Y / SUB_Y)
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
            self._sky_cells = sky_grid
            sky_grid = self._fade_sky(sky_grid)
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
