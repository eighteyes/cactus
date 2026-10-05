"""
fieldproc.py — where the TUI's field simulation runs: in the TUI's own process, or in a child.

Responsibilities:
- One interface over the field `World` for the TUI: drop, resize, pile_only,
  visible, apply_config, set_fps, reseed, stop, plus the parent's own
  `SkyConfig` copy (`config`) and the pile height (`pile_rows`).
- `InlineField`: an in-process `World`, advanced and rendered by the TUI's
  own timer exactly as before; `.world` stays reachable. The default under
  `App.run_test()` and whenever `CACTUS_FIELD=inline`.
- `ProcessField`: a `multiprocessing` spawn child that owns the `World`,
  paces itself at `1 / fps` on real elapsed time, owns the sky.toml mtime
  reload and the garden save/reload, and ships changed rows only. The
  parent acks each frame; the child holds at most `CREDIT` unacked frames
  and merges changed rows while it waits, so a busy parent never queues
  stale frames.
- `SkyWatch` / `GardenSync`: the sky.toml and garden.json polling both modes
  share, reporting flash messages instead of touching any UI.
- `text_rows`: split a rendered field `Text` into `(plain, spans)` rows.

No Textual import: the child process imports this module.
"""

from __future__ import annotations

import atexit
import multiprocessing as mp
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any

from rich.text import Text

from . import garden
from .field import GROUND_ROWS, World
from .sky import SkyConfig, config_path as sky_config_path

# A stalled or suspended process must never hand `World.advance` a giant
# elapsed time and make the sky or a falling seed jump.
FIELD_MAX_DT = 0.5
# sky.toml and garden.json are polled on one wall-clock cadence.
SKY_RELOAD_SECONDS = 2.0
# Frames the child may send before the parent acks one.
CREDIT = 2

Row = tuple[str, tuple[tuple[int, int, str], ...]]


def text_rows(text: Text) -> list[Row]:
    """`text` split on newlines into `(plain, ((start, end, style), ...))`
    rows, offsets relative to each row and every style a string."""
    return [
        (line.plain, tuple((s.start, s.end, str(s.style)) for s in line.spans))
        for line in text.split("\n", allow_blank=True)
    ]


class SkyWatch:
    """sky.toml's last-seen mtime; `poll` loads the file when it moved."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self.mtime: float | None = None

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else sky_config_path()

    def poll(self, *, initial: bool = False) -> tuple[SkyConfig | None, str | None]:
        """`(config, flash)`. Best-effort: a missing file is the defaults, an
        unchanged mtime is `(None, None)`, a bad file keeps the running
        config and reports why."""
        path = self.path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if not initial and mtime == self.mtime:
            return None, None
        self.mtime = mtime
        try:
            config = SkyConfig.load(path)
        except ValueError as exc:
            return None, f"sky config: {exc}"
        return config, None if initial else "sky config reloaded"


PENDING_SEED_CAP = 20  # seeds claimed per poll; the rest stay queued


class GardenSync:
    """garden.json beside the database: load, save, reload when another
    process wrote a newer one. Every method fails soft."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.mtime: float | None = None

    def load(self, world: World) -> str | None:
        """A missing file leaves the world's pile as-is; a malformed one
        returns a flash and is otherwise ignored."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        try:
            data = garden.read(self.path)
            if data is None:
                return None
            garden.load_into(world, data)
        except ValueError:
            return "garden.json unreadable"
        self.mtime = mtime
        return None

    def save(self, world: World) -> None:
        """Flush landings since the last save; a write error leaves the
        counter alone so the next tick retries."""
        try:
            self.mtime = garden.save(world, self.path)
        except OSError:
            return
        world.landed_since_save = 0

    def drop_pending(self, world: World) -> int:
        """Claim queued seeds (answers made outside a TUI key) and drop them
        at random columns. Fails soft; returns how many fell."""
        try:
            n = garden.claim_pending(self.path, PENDING_SEED_CAP)
        except OSError:
            return 0
        for _ in range(n):
            world.drop(world.rng.randrange(world.cols))
        return n

    def reload_if_changed(self, world: World) -> str | None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        if mtime == self.mtime:
            return None
        flash = self.load(world)
        if flash is not None:
            return flash
        return "garden updated" if self.mtime == mtime else None


class InlineField:
    """The `World` in the TUI's own process. The TUI's timer advances it and
    `_render_field` renders it; every setter here is immediate."""

    inline = True

    def __init__(self, world: World) -> None:
        self.world = world

    @property
    def config(self) -> SkyConfig:
        return self.world.sky.config

    @property
    def cols(self) -> int:
        return self.world.cols

    def pile_rows(self) -> int:
        return self.world.pile_rows()

    def random_column(self) -> int:
        return self.world.rng.randrange(self.world.cols)

    def drop(self, col: int) -> None:
        self.world.drop(col)

    def resize(self, cols: int, rows: int) -> None:
        if cols != self.world.cols or rows != self.world.rows:
            self.world.resize(cols, rows)

    def apply_config(self, config: SkyConfig, *, mtime: float | None = None) -> None:
        self.world.apply_sky_config(config)

    def reseed(self, seed: int) -> None:
        self.world.reseed(seed)

    # The inline World is rendered on demand and paced by the TUI's timer;
    # these only matter to a child that renders on its own.
    def set_pile_only(self, pile_only: bool) -> None:
        pass

    def set_visible(self, visible: bool) -> None:
        pass

    def set_fps(self, fps: int) -> None:
        pass

    def stop(self) -> None:
        pass


class FieldUpdate:
    """Everything `ProcessField.drain` read in one go, merged: the newest
    row count and pile height, every changed row (later frames win), and
    any flashes, config, or error the child sent."""

    __slots__ = ("frames", "n_rows", "pile_rows", "rows", "flashes", "config", "error", "closed")

    def __init__(self) -> None:
        self.frames = 0
        self.n_rows: int | None = None
        self.pile_rows: int | None = None
        self.rows: dict[int, Row] = {}
        self.flashes: list[str] = []
        self.config: SkyConfig | None = None
        self.error: str | None = None
        self.closed = False


class ProcessField:
    """The `World` in a spawned child. The parent keeps its own `SkyConfig`
    copy (`config`) for the tuning overlay and pushes changes with
    `apply_config`; the child pushes frames, flashes, and reloaded configs
    back. Setters remember their value and send only on change; before
    `start` they only remember, and `start` hands the child the lot."""

    inline = False
    world = None

    def __init__(self, *, garden_path: Path, sky_path: Path | None = None,
                 config: SkyConfig | None = None, cols: int = 1, rows: int = 10,
                 seed: int | None = None) -> None:
        self.garden_path = garden_path
        self.sky_path = sky_path
        self.config = config if config is not None else SkyConfig()
        self.cols = cols
        self.rows = rows
        self.seed = seed
        self.sky_mtime: float | None = None
        self._pile_rows = GROUND_ROWS + 1  # an empty pile, until a frame says otherwise
        self._pile_only = False
        self._visible = True
        self._fps = self.config.fps
        self._conn: Any = None
        self._proc: Any = None

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Spawn the child. Call before Textual swaps the std streams where
        possible (`run_tui`): spawn needs the resource tracker already up."""
        if self._proc is not None:
            return
        from multiprocessing import resource_tracker

        resource_tracker.ensure_running()
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe()
        state = {
            "cols": self.cols, "rows": self.rows, "config": self.config,
            "sky_path": str(self.sky_path or sky_config_path()), "sky_mtime": self.sky_mtime,
            "garden_path": str(self.garden_path), "pile_only": self._pile_only,
            "visible": self._visible, "fps": self._fps, "seed": self.seed,
        }
        self._proc = ctx.Process(target=_child_main, args=(child, state), name="cactus-field", daemon=True)
        self._proc.start()
        child.close()
        atexit.register(self._kill)

    def fileno(self) -> int:
        return self._conn.fileno()

    @property
    def started(self) -> bool:
        return self._proc is not None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def stop(self, timeout: float = 1.0) -> None:
        """Ask the child to stop, then make sure it has: join, terminate, kill."""
        if self._proc is None:
            return
        self._send(("stop",))
        self._kill(timeout)
        atexit.unregister(self._kill)

    def _kill(self, timeout: float = 0.5) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.join(timeout)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout)
        try:
            self._conn.close()
        except OSError:
            pass

    def _send(self, msg: tuple) -> None:
        if self._conn is None:
            return
        try:
            self._conn.send(msg)
        except (BrokenPipeError, EOFError, OSError):
            pass

    # ---- commands -------------------------------------------------------

    def pile_rows(self) -> int:
        return self._pile_rows

    def random_column(self) -> int:
        return random.randrange(max(self.cols, 1))

    def drop(self, col: int) -> None:
        self._send(("drop", col))

    def resize(self, cols: int, rows: int) -> None:
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        self._send(("resize", cols, rows))

    def set_pile_only(self, pile_only: bool) -> None:
        if pile_only != self._pile_only:
            self._pile_only = pile_only
            self._send(("pile_only", pile_only))

    def set_visible(self, visible: bool) -> None:
        if visible != self._visible:
            self._visible = visible
            self._send(("visible", visible))

    def set_fps(self, fps: int) -> None:
        if fps != self._fps:
            self._fps = fps
            self._send(("fps", fps))

    def apply_config(self, config: SkyConfig, *, mtime: float | None = None) -> None:
        """Adopt `config` as the parent copy and push it. `mtime` is the
        dump's own file mtime, so the child's reload poll skips that write."""
        self.config = config
        self._fps = config.fps
        if mtime is not None:
            self.sky_mtime = mtime
        self._send(("config", config, mtime))

    def reseed(self, seed: int) -> None:
        self._send(("reseed", seed))

    # ---- frames ---------------------------------------------------------

    def drain(self) -> FieldUpdate:
        """Read every message ready now, acking each frame, and merge them
        so the caller paints only the newest state."""
        upd = FieldUpdate()
        conn = self._conn
        if conn is None:
            upd.closed = True
            return upd
        try:
            while conn.poll():
                msg = conn.recv()
                kind = msg[0]
                if kind == "frame":
                    _, _seq, n_rows, pile_rows, rows = msg
                    conn.send(("ack",))
                    upd.frames += 1
                    if n_rows != upd.n_rows:
                        upd.rows = {y: r for y, r in upd.rows.items() if y < n_rows}
                    upd.n_rows = n_rows
                    upd.pile_rows = pile_rows
                    self._pile_rows = pile_rows
                    upd.rows.update(rows)
                elif kind == "flash":
                    upd.flashes.append(msg[1])
                elif kind == "config":
                    self.config = msg[1]
                    self._fps = msg[1].fps
                    upd.config = msg[1]
                elif kind == "error":
                    upd.error = msg[1]
        except (EOFError, OSError):
            upd.closed = True
        return upd


# ---- child ----------------------------------------------------------------


def _child_main(conn: Any, state: dict[str, Any]) -> None:
    """Spawn target. Never writes to the terminal the TUI owns: std streams
    go to /dev/null, SIGINT is ignored, and a crash goes back as a message."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    devnull = open(os.devnull, "w")
    sys.stdout = sys.stderr = devnull
    try:
        _child_loop(conn, state)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    except Exception as exc:  # noqa: BLE001 — report, never print
        try:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except OSError:
            pass
    finally:
        conn.close()


def _child_loop(conn: Any, state: dict[str, Any]) -> None:
    rng = random.Random(state["seed"]) if state["seed"] is not None else random.Random()
    world = World(state["cols"], state["rows"], rng=rng, sky_config=state["config"])
    sky = SkyWatch(Path(state["sky_path"]))
    sky.mtime = state["sky_mtime"]
    garden_sync = GardenSync(Path(state["garden_path"]))
    flash = garden_sync.load(world)
    if flash is not None:
        conn.send(("flash", flash))
    pile_only = state["pile_only"]
    visible = state["visible"]
    interval = 1.0 / max(state["fps"], 1)
    credit = CREDIT
    seq = 0
    prev: list[Row] | None = None
    pending: dict[int, Row] = {}
    pile_sent: int | None = None
    last = time.monotonic()
    next_t = last
    reload_last = last
    while True:
        while conn.poll(0):
            cmd = conn.recv()
            kind = cmd[0]
            if kind == "ack":
                credit = min(credit + 1, CREDIT)
            elif kind == "drop":
                world.drop(cmd[1])
                next_t = min(next_t, time.monotonic())
            elif kind == "resize":
                world.resize(cmd[1], cmd[2])
                prev = None
                next_t = min(next_t, time.monotonic())
            elif kind == "pile_only":
                pile_only = cmd[1]
                next_t = min(next_t, time.monotonic())
            elif kind == "visible":
                visible = cmd[1]
                if visible:
                    prev = None  # the parent's rows may be stale; resend them all
                    next_t = min(next_t, time.monotonic())
            elif kind == "fps":
                interval = 1.0 / max(cmd[1], 1)
            elif kind == "config":
                world.apply_sky_config(cmd[1])
                interval = 1.0 / max(cmd[1].fps, 1)
                if cmd[2] is not None:
                    sky.mtime = cmd[2]
            elif kind == "reseed":
                world.reseed(cmd[1])
            elif kind == "stop":
                if world.landed_since_save > 0:
                    garden_sync.save(world)
                return
        now = time.monotonic()
        if now < next_t:
            conn.poll(next_t - now)  # sleep until a command or the next frame
            continue
        next_t = max(next_t + interval, now)
        world.advance(min(max(now - last, 0.0), FIELD_MAX_DT))
        last = now
        if world.landed_since_save > 0:
            garden_sync.save(world)
        if now - reload_last >= SKY_RELOAD_SECONDS:
            reload_last = now
            config, flash = sky.poll()
            if config is not None:
                world.apply_sky_config(config)
                interval = 1.0 / max(config.fps, 1)
                conn.send(("config", config))
            if flash is not None:
                conn.send(("flash", flash))
            flash = garden_sync.reload_if_changed(world)
            if flash is not None:
                conn.send(("flash", flash))
            garden_sync.drop_pending(world)
        if visible:
            cur = text_rows(world.render(pile_only=pile_only))
            if prev is None or len(prev) != len(cur):
                pending = dict(enumerate(cur))
            else:
                for y, (a, b) in enumerate(zip(cur, prev)):
                    if a != b:
                        pending[y] = a
            prev = cur
        pile = world.pile_rows()
        if credit > 0 and (pending or pile != pile_sent):
            seq += 1
            conn.send(("frame", seq, world.rows, pile, pending))
            pending = {}
            pile_sent = pile
            credit -= 1
