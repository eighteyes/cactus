# Cactus field v8: puffs, slots, a shared garden

Three asks from 2026-09-29.

**Puffs engine** (`sky_engine = "puffs"`, `src/cactus/sky.py`)

- No whole-sky scroll. `camera_x` stays 0.
- A population of `_Puff`s per band. Each has its own x speed (either sign,
  band-scaled by `cloud_drift`), its own life (`cloud_life`), two baked
  noise patches it morphs between.
- Unfolding: a cloud's cutoff starts at 1.0 and sinks to the style's
  resting cutoff over `rise` of its life, holds, climbs back over `fall`.
  Cores appear first, fringes grow out of them, then it recedes and a
  newborn takes its slot.
- `cloud_style` picks a `_PUFF_STYLES` table: `drift` (each cloud wanders),
  `bloom` (near-still, larger, longer unfold), `streaks` (long thin bands).
- `cloud_count` scales the population; `apply` grows/trims in place.
- `SKY_ENGINES` maps name to class; each class carries `ENGINE`, which
  `World.apply_sky_config` reads instead of `isinstance`.
- Tests: `tests/test_puffs.py`.

**Slots** on the `T` page

- `sky-slot-N.toml` beside `sky.toml`, sparse dumps.
- Digit recalls (applies live, rewrites `sky.toml`), `S` then digit saves.
- Overlay shows which slots are filled.

**Garden persistence** (supersedes q356 "session")

- `garden.json` beside the DB: `structure`, `drops`. Shared by every TUI;
  written after each landing, reloaded on mtime change.
- `~` toggles the whole field strip. With the field hidden, backtick
  toggles a pile-only view (ground rows plus landed blocks, no sky).
  With the field shown, backtick keeps dropping a seed.
- `cactus garden` prints the path and cell count; `--clear` wipes it.

Rows: q390 (sky-shape), q391 (garden-shape).
