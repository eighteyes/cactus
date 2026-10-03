"""
store.py — SQLite persistence for the cactus question/answer inbox.

Responsibilities:
- Own the database location, schema, and migrations.
- Create, read, answer, and clear questions and their threaded follow-ups.
- Let a human ask for a rewrite (`elaborate_request`/`unelaborate`) and an
  agent address it or fix a row in place (`edit`).
- Expose a change cursor so the TUI and watch feed can poll cheaply.
- Keep every read and write safe for concurrent agent writers via WAL mode.
- Write a decision record (record.py) after every state change, fail-soft.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .scope import project_label

# `D` uses the existing elaborate state rather than a second kind of pending
# row: the owner already receives elaborate events and knows it must act before
# the human can answer. The instruction tells it how to fan a large decision
# out without losing the original row's thread and context.
DECOMPOSE_INSTRUCTION = (
    "Decompose this into several smaller, independently answerable questions. "
    "Post each replacement as a follow-up (`cactus ask ... -p {key} --no-wait --agent ID`), "
    "clear the original row once they are posted, then wait on the batch with one "
    "backgrounded `cactus get KEY... --wait`; its exit is your wake-up."
)

KINDS = ("choice", "multi", "text", "confirm")
# `elaborate` (q212): the human asked for a rewrite; the row stops taking
# answers until `edit` addresses it, then lands back on `open`/`live`.
STATUSES = ("open", "live", "elaborate", "answered", "cleared")

# How sure an agent's recommendation is. Advisory only — a recommend still
# waits for the human, unlike a steer's `chosen`, which proceeds.
CONFIDENCE = ("low", "med", "high")
CONFIDENCE_GLYPH = {"low": "○", "med": "◐", "high": "●"}

# What a human surface shows: a fork still waiting, a persistent row that
# stays answerable, and a row awaiting a rewrite — all are work in front of
# the reader, even though `elaborate` accepts no answer until it is edited.
ACTIONABLE = ("open", "live", "elaborate")

# What the agent is asking for. Orthogonal to KINDS, which is how the answer is
# collected: a `run` act uses a `confirm` shape, a `steer` act may use either
# `choice` or `text`.
ACTS = ("ask", "steer", "run", "notify", "review", "plan", "data")

# Acts whose rows stay answerable. They are created `live`, never transition on
# their own, and `wait_for_answer` watches them for a change instead.
PERSISTENT_ACTS = ("review", "plan", "data")

# Whether a row blocks is the AGENT's call, stored per row in `blocked`, not a
# property of its act. The act only supplies the default the agent gets when it
# says nothing, and the agent overrides it freely. Over-claiming — parking a
# human on a question the agent could have answered — is the failure mode, and
# it is measurable as a blocked rate rather than legislated here.
DEFAULT_BLOCKED = {
    "ask": True,
    "run": True,
    "steer": False,
    "notify": False,
    "review": False,
    "plan": False,
    "data": False,
}

# Shapes each act accepts. `notify` and `plan` collect no answer of their own.
ACT_SHAPES: dict[str, tuple[str, ...]] = {
    "ask":    ("choice", "multi", "text", "confirm"),
    "steer":  ("choice", "text"),
    "run":    ("confirm",),
    "notify": ("text",),
    "review": ("confirm",),
    "plan":   ("text",),
    "data":   ("choice",),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT    NOT NULL,
    num          INTEGER,
    project      TEXT    NOT NULL,
    cwd          TEXT    NOT NULL,
    thread       TEXT,
    parent_id    INTEGER REFERENCES questions(id) ON DELETE CASCADE,
    text         TEXT    NOT NULL,
    kind         TEXT    NOT NULL,
    act          TEXT    NOT NULL DEFAULT 'ask',
    agent        TEXT,
    word         TEXT,
    workspace    TEXT,
    tab          TEXT,
    pane         TEXT,
    session      TEXT,
    title        TEXT,
    chosen       TEXT,
    blocked      INTEGER NOT NULL DEFAULT 1,
    source       TEXT,
    choices      TEXT    NOT NULL DEFAULT '[]',
    allow_free   INTEGER NOT NULL DEFAULT 1,
    recommend    TEXT,
    confidence   TEXT,
    recommend_why TEXT,
    context      TEXT,
    asked_by     TEXT,
    status       TEXT    NOT NULL DEFAULT 'open',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    -- The elaborate request (q212): a hint (nullable, free text from the
    -- human) and when it was made. Cleared by `edit`.
    elaborate    TEXT,
    elaborate_at TEXT,
    -- Which action last moved a row out of `elaborate` (q228): 'withdrawn'
    -- for Store.unelaborate, 'edited' for Store.edit. A pure before/after
    -- diff cannot tell the two apart — both leave the row at the same
    -- status — so the monitor reads this marker instead.
    last_change  TEXT,
    -- Absolute paths a human may preview (`f`) or edit (`F`) from the TUI,
    -- JSON list. Additive, like `run_tail`.
    files        TEXT,
    -- Heard / responded stamps (q404-q406), review and plan rows only: when
    -- the owning agent last read the row (`get --agent`) and last wrote to
    -- it (`plan`/`review`/`edit --agent`). Compared against the latest
    -- verdict's time; never part of the monitor signature.
    heard_at     TEXT,
    responded_at TEXT,
    -- The auto-decider's proposal (advisory, never an answer): the label it
    -- picked, its confidence, a reason, and when. Never part of the monitor
    -- signature. Cleared by `edit` when the text or choices change.
    auto_pick       TEXT,
    auto_confidence REAL,
    auto_reason     TEXT,
    auto_at         TEXT,
    -- Keys number per project (q166). A fresh database starts here; an older
    -- one reaches it through `cactus migrate --yes`.
    UNIQUE(project, key)
);

-- Append-only. A persistent row is verdicted repeatedly, so the current answer
-- is the latest by (created_at, id), not the only row.
CREATE TABLE IF NOT EXISTS answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    selected     TEXT    NOT NULL DEFAULT '[]',
    text         TEXT,
    skipped      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    question_id  INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
    look_at      TEXT,
    run_cmd      TEXT,
    pass_when    TEXT,
    fail_when    TEXT,
    then_do      TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    text         TEXT    NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(question_id, idx)
);

-- Project preferences live beside the inbox rather than in a checkout: a
-- human can ignore one project from the global TUI, and every agent using the
-- shared database sees the same switch immediately.
CREATE TABLE IF NOT EXISTS project_settings (
    project    TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT    NOT NULL
);

"""

# Indexes run after _migrate(), because idx_q_agent names a column that a
# qaui-era database does not have until the migration adds it.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_q_project_status ON questions(project, status);
CREATE INDEX IF NOT EXISTS idx_q_agent          ON questions(agent, status);
CREATE INDEX IF NOT EXISTS idx_answers_q        ON answers(question_id, created_at);
CREATE INDEX IF NOT EXISTS idx_steps_q          ON steps(question_id, idx);
CREATE INDEX IF NOT EXISTS idx_q_parent         ON questions(parent_id);
CREATE INDEX IF NOT EXISTS idx_q_updated        ON questions(updated_at);
"""


def _data_root() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base).expanduser() if base else Path.home() / ".local" / "share"


def legacy_db_path() -> Path:
    """Where a qaui-era inbox sits, if one does."""
    return _data_root() / "qaui" / "qaui.db"


def default_db_path() -> Path:
    """Database location, overridable with CACTUS_DB for tests and alternate inboxes.

    Pure: it resolves a path and prints nothing. Announcing a fallback belongs
    with opening the database, not with computing its name — `build_parser`
    calls this for one line of help text, and a notice here ended up in front
    of every `--agent-help`.
    """
    env = os.environ.get("CACTUS_DB")
    if env is not None and not env.strip():
        # An empty value is a scripting accident — a failed mktemp, an unset
        # variable in a test harness. Falling through would silently target the
        # live inbox, which is exactly what the variable exists to avoid.
        raise ValueError("CACTUS_DB is set but empty; unset it or give it a path")
    if env:
        return Path(env).expanduser()
    new_path = _data_root() / "cactus" / "cactus.db"
    if new_path.exists():
        return new_path
    legacy = legacy_db_path()
    return legacy if legacy.exists() else new_path


def _now() -> str:
    """Timestamp for every write.

    Microsecond resolution is load-bearing: `cursor()` reports the maximum
    `updated_at`, and a second-resolution clock would let two writes inside the
    same second share a token, so pollers would miss the later one.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class Choice:
    label: str
    description: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"label": self.label, "description": self.description}

    @staticmethod
    def parse(raw: Any) -> "Choice":
        if isinstance(raw, str):
            # "label: description" splits on the first colon; bare strings stay bare.
            label, sep, desc = raw.partition(":")
            return Choice(label.strip(), desc.strip() if sep else "")
        if isinstance(raw, dict):
            return Choice(str(raw.get("label", "")), str(raw.get("description", "")))
        raise ValueError(f"unparseable choice: {raw!r}")


@dataclass
class Answer:
    selected: list[str] = field(default_factory=list)
    text: str | None = None
    skipped: bool = False
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "text": self.text,
            "skipped": self.skipped,
            "created_at": self.created_at,
        }


@dataclass
class Review:
    """The rearmatter verify block, persisted: look at, run, pass, fail, then."""
    look_at: str | None = None
    run_cmd: str | None = None
    pass_when: str | None = None
    fail_when: str | None = None
    then_do: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "look_at": self.look_at,
            "run_cmd": self.run_cmd,
            "pass_when": self.pass_when,
            "fail_when": self.fail_when,
            "then_do": self.then_do,
        }


@dataclass
class Step:
    idx: int
    text: str
    done: bool = False

    def as_dict(self) -> dict[str, Any]:
        # `idx` stays the store's 0-based position; `n` is the 1-based number
        # the CLI and human surfaces show, so a consumer never has to +1 itself.
        return {"idx": self.idx, "n": self.idx + 1, "text": self.text, "done": self.done}


@dataclass
class Question:
    id: int
    key: str
    project: str
    cwd: str
    thread: str | None
    parent_id: int | None
    parent_key: str | None
    text: str
    kind: str
    act: str
    agent: str | None
    word: str | None
    workspace: str | None
    tab: str | None
    pane: str | None
    session: str | None
    title: str | None
    chosen: str | None
    blocked: bool
    source: str | None
    choices: list[Choice]
    allow_free: bool
    context: str | None
    asked_by: str | None
    status: str
    created_at: str
    updated_at: str
    elaborate: str | None = None
    elaborate_at: str | None = None
    # Which action last moved this row out of `elaborate` (q228): 'withdrawn'
    # or 'edited'. Read only by the monitor's transition classifier — not
    # rendered elsewhere, so it stays off as_dict() like the DB internals it is.
    last_change: str | None = None
    recommend: list[str] = field(default_factory=list)
    confidence: str | None = None
    recommend_why: str | None = None
    answer: Answer | None = None
    answers: list[Answer] = field(default_factory=list)
    review: Review | None = None
    steps: list[Step] = field(default_factory=list)
    depth: int = 0
    run_exit: int | None = None
    run_tail: list[str] = field(default_factory=list)
    run_log: str | None = None
    files: list[str] = field(default_factory=list)
    heard_at: str | None = None
    responded_at: str | None = None
    auto_pick: str | None = None
    auto_confidence: float | None = None
    auto_reason: str | None = None
    auto_at: str | None = None

    @property
    def heard_state(self) -> str | None:
        """`sent`, `heard`, or None (q405). Review and plan rows only.

        Measured from the latest human verdict's time `T`: a response after `T`
        or no verdict at all reads None; a read after `T` reads `heard`; a
        verdict nobody has read yet reads `sent`. A new verdict moves `T`, so
        the row restarts at `sent` with no reset step.
        """
        if self.act not in ("review", "plan") or self.status == "cleared":
            return None
        if self.answer is None:
            return None
        t = self.answer.created_at
        if self.responded_at and self.responded_at > t:
            return None
        if self.heard_at and self.heard_at > t:
            return "heard"
        return "sent"

    @property
    def persistent(self) -> bool:
        return self.act in PERSISTENT_ACTS

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            # "LABEL:qN" (q166) — a stable cross-project reference, alongside
            # the bare "key" every single-project surface already uses.
            "ref": f"{project_label(self.project)}:{self.key}",
            "project": self.project,
            "cwd": self.cwd,
            "thread": self.thread,
            "parent": self.parent_key,
            "text": self.text,
            "kind": self.kind,
            "act": self.act,
            "agent": self.agent,
            "word": self.word,
            "workspace": self.workspace,
            "tab": self.tab,
            "pane": self.pane,
            "session": self.session,
            "title": self.title,
            "chosen": self.chosen,
            "blocked": self.blocked,
            "source": self.source,
            "choices": [c.as_dict() for c in self.choices],
            "allow_free": self.allow_free,
            "recommend": self.recommend or None,
            "confidence": self.confidence,
            "recommend_why": self.recommend_why,
            "context": self.context,
            "asked_by": self.asked_by,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "elaborate": self.elaborate,
            "elaborate_at": self.elaborate_at,
            "answer": self.answer.as_dict() if self.answer else None,
            "answers": [a.as_dict() for a in self.answers],
            "review": self.review.as_dict() if self.review else None,
            "steps": [st.as_dict() for st in self.steps],
            "result": (
                {"exit": self.run_exit, "tail": self.run_tail, "log": self.run_log}
                if self.run_exit is not None else None
            ),
            "files": self.files,
            "auto": (
                {
                    "pick": self.auto_pick, "confidence": self.auto_confidence,
                    "reason": self.auto_reason, "at": self.auto_at,
                }
                if self.auto_pick is not None else None
            ),
        }


class AlreadyAnswered(RuntimeError):
    """A one-shot row that another surface answered first.

    Two surfaces answer the same inbox, so a human can tap a row the board
    already resolved. Silently overwriting would let the second tap decide,
    which is the opposite of what the reader saw. The row is left alone and the
    caller renders a stale cell.
    """


class Store:
    """Thin SQLite gateway. One instance per process; safe across processes via WAL."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is not None and not str(path).strip():
            # --db "" is a scripting accident, exactly like an empty CACTUS_DB —
            # falling through to the default would silently target the live
            # inbox, which is the one thing this is meant to prevent.
            raise ValueError("--db is set but empty; drop it or give it a path")
        self.path = Path(path) if path else default_db_path()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"cannot create {self.path.parent}: {exc}") from exc
        self.conn = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self._announce_legacy()
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES)
        # Set by a human surface (the TUI) that has somewhere better than
        # stderr to put a record-write failure — its flash/status line.
        # Unset, a failure goes to stderr, which is the correct default for
        # every other caller (the CLI, a script).
        self.record_warning: Callable[[str], None] | None = None

    def _migrate(self) -> None:
        """Bring a qaui-era database up to the current schema.

        Idempotent: every step checks the live schema first, so opening an
        already-current database costs three cheap pragmas and nothing else.
        """
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(questions)")}
        if "act" not in cols:
            self.conn.execute(
                "ALTER TABLE questions ADD COLUMN act TEXT NOT NULL DEFAULT 'ask'"
            )
        if "agent" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN agent TEXT")
        if "word" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN word TEXT")
        if "chosen" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN chosen TEXT")
        if "blocked" not in cols:
            self.conn.execute(
                "ALTER TABLE questions ADD COLUMN blocked INTEGER NOT NULL DEFAULT 1"
            )
        if "source" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN source TEXT")
        if "recommend" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN recommend TEXT")
        if "confidence" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN confidence TEXT")
        if "recommend_why" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN recommend_why TEXT")
        # Scope stamps for projectors and for re-homing a row whose agent no
        # longer exists (a session token rotates on `claude --resume`). `pane`
        # and `session` are stamped together: herdr only resolves a pane to an
        # identity in the context of the session that owns it.
        if "workspace" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN workspace TEXT")
        if "tab" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN tab TEXT")
        if "pane" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN pane TEXT")
        if "session" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN session TEXT")
        if "title" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN title TEXT")
        # A run row's captured result (q193-195): exit code, a short tail, and
        # the path of the full-output spill file. Additive, like every other
        # column here — a run row is answered like any confirm, this is just
        # where the outcome that produced the answer lives.
        if "run_exit" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN run_exit INTEGER")
        if "run_tail" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN run_tail TEXT")
        if "run_log" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN run_log TEXT")
        # Per-project key numbering (q166): `num` is the integer a project's
        # keys count from — additive and safe to backfill on open, unlike the
        # UNIQUE(key) rebuild below. Backfilled once from the numeric suffix
        # of each row's existing key, so a pre-existing q37 keeps meaning q37.
        if "num" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN num INTEGER")
            self.conn.execute(
                "UPDATE questions SET num = CAST(substr(key, 2) AS INTEGER) "
                "WHERE num IS NULL"
            )
        # The elaborate request (q212): a hint (nullable) and when it was
        # made. `status` takes the new value 'elaborate' with no schema
        # change of its own — it is plain TEXT with no CHECK constraint, so
        # this is additive like every other column here.
        if "elaborate" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN elaborate TEXT")
        if "elaborate_at" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN elaborate_at TEXT")
        # Which action last moved a row out of `elaborate` (q228). See the
        # column comment in SCHEMA for why the monitor needs it.
        if "last_change" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN last_change TEXT")
        # A row's attached file paths (q-files): JSON list, additive like
        # `run_tail` above.
        if "files" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN files TEXT")
        # Heard / responded stamps (q404-q406): additive like `files`.
        if "heard_at" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN heard_at TEXT")
        if "responded_at" not in cols:
            self.conn.execute("ALTER TABLE questions ADD COLUMN responded_at TEXT")
        # The auto-decider's proposal: additive like `heard_at`.
        for col, typ in (
            ("auto_pick", "TEXT"), ("auto_confidence", "REAL"),
            ("auto_reason", "TEXT"), ("auto_at", "TEXT"),
        ):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE questions ADD COLUMN {col} {typ}")
        # `seen` renamed to `notify`: a data fixup, not a schema change, so it
        # runs unconditionally on every open like the checks above — idempotent,
        # since a second pass finds no `seen` rows left to touch.
        self.conn.execute("UPDATE questions SET act='notify' WHERE act='seen'")

        # NOT called here. Rebuilding `answers` — and, for the same reason,
        # `questions` to drop the global UNIQUE(key) that per-project numbering
        # cannot use — is destructive-shaped and changes the schema under any
        # process that already imported the old module — which is exactly what
        # happened to a long-running agent when `cactus where` migrated the
        # live inbox out from under it. Additive column adds are safe to do on
        # open; a table rebuild is not, so it needs `cactus migrate` or
        # CACTUS_MIGRATE=1.
        if os.environ.get("CACTUS_MIGRATE") == "1":
            self._drop_answer_uniqueness()
            self._drop_key_uniqueness()

    def needs_rebuild(self) -> bool:
        """Whether `answers` still carries the constraint an append log cannot."""
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='answers'"
        ).fetchone()
        return bool(row and "UNIQUE" in (row["sql"] or ""))

    def _drop_answer_uniqueness(self) -> None:
        """Rebuild `answers` without UNIQUE(question_id), once.

        A persistent row takes a verdict more than once, so answers became an
        append-only log. SQLite cannot drop a constraint in place, and the
        rebuild has to outlive a crash mid-way, so it runs inside one explicit
        transaction with foreign keys off — dropping the old table with them on
        would cascade the questions' answers away.
        """
        if not self.needs_rebuild():
            return

        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            # Individual execute() calls, not executescript(): executescript
            # issues an implicit COMMIT before it runs, which would discard the
            # transaction guarding this rebuild.
            self.conn.execute("BEGIN IMMEDIATE")
            for stmt in (
                """CREATE TABLE answers_new (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    selected     TEXT    NOT NULL DEFAULT '[]',
                    text         TEXT,
                    skipped      INTEGER NOT NULL DEFAULT 0,
                    created_at   TEXT    NOT NULL
                )""",
                """INSERT INTO answers_new (id, question_id, selected, text, skipped, created_at)
                   SELECT id, question_id, selected, text, skipped, created_at FROM answers""",
                "DROP TABLE answers",
                "ALTER TABLE answers_new RENAME TO answers",
            ):
                self.conn.execute(stmt)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    def needs_key_rebuild(self) -> bool:
        """Whether `questions.key` still carries the global UNIQUE that
        per-project numbering (q166) cannot use — two projects each minting
        their own q1 collide on it."""
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='questions'"
        ).fetchone()
        sql = row["sql"] or "" if row else ""
        return "key" in sql and "UNIQUE" in sql and "UNIQUE(project, key)" not in sql

    def _drop_key_uniqueness(self) -> None:
        """Rebuild `questions` with UNIQUE(project, key) instead of UNIQUE(key), once.

        Keys number per project from here on, so the same text ("q1") is
        expected to recur across projects — global uniqueness on `key` alone
        would refuse the second project's first row. `id` stays the untouched
        AUTOINCREMENT primary key every foreign key already points at, so this
        rebuild only changes what `key` is allowed to collide on.
        """
        if not self.needs_key_rebuild():
            return

        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            for stmt in (
                """CREATE TABLE questions_new (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    key          TEXT    NOT NULL,
                    num          INTEGER,
                    project      TEXT    NOT NULL,
                    cwd          TEXT    NOT NULL,
                    thread       TEXT,
                    parent_id    INTEGER REFERENCES questions(id) ON DELETE CASCADE,
                    text         TEXT    NOT NULL,
                    kind         TEXT    NOT NULL,
                    act          TEXT    NOT NULL DEFAULT 'ask',
                    agent        TEXT,
                    word         TEXT,
                    workspace    TEXT,
                    tab          TEXT,
                    pane         TEXT,
                    session      TEXT,
                    title        TEXT,
                    chosen       TEXT,
                    blocked      INTEGER NOT NULL DEFAULT 1,
                    choices      TEXT    NOT NULL DEFAULT '[]',
                    allow_free   INTEGER NOT NULL DEFAULT 1,
                    recommend    TEXT,
                    confidence   TEXT,
                    recommend_why TEXT,
                    context      TEXT,
                    asked_by     TEXT,
                    status       TEXT    NOT NULL DEFAULT 'open',
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL,
                    run_exit     INTEGER,
                    run_tail     TEXT,
                    run_log      TEXT,
                    elaborate    TEXT,
                    elaborate_at TEXT,
                    last_change  TEXT,
                    files        TEXT,
                    heard_at     TEXT,
                    responded_at TEXT,
                    auto_pick       TEXT,
                    auto_confidence REAL,
                    auto_reason     TEXT,
                    auto_at         TEXT,
                    UNIQUE(project, key)
                )""",
                """INSERT INTO questions_new
                   SELECT id, key, num, project, cwd, thread, parent_id, text, kind,
                          act, agent, word, workspace, tab, pane, session, title,
                          chosen, blocked, choices, allow_free, recommend,
                          confidence, recommend_why, context, asked_by, status,
                          created_at, updated_at, run_exit, run_tail, run_log,
                          elaborate, elaborate_at, last_change, files,
                          heard_at, responded_at,
                          auto_pick, auto_confidence, auto_reason, auto_at
                   FROM questions""",
                "DROP TABLE questions",
                "ALTER TABLE questions_new RENAME TO questions",
            ):
                self.conn.execute(stmt)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    _legacy_announced = False

    def _announce_legacy(self) -> None:
        """Say once, on stderr, that a qaui-era inbox is being read in place.

        The old file is never relocated automatically: copying it silently
        would leave two inboxes diverging under a tool whose whole contract is
        that agents and humans see the same rows.
        """
        if Store._legacy_announced or os.environ.get("CACTUS_DB"):
            return
        legacy = legacy_db_path()
        if self.path != legacy:
            return
        Store._legacy_announced = True
        target = _data_root() / "cactus" / "cactus.db"
        print(
            f"cactus: using the qaui inbox at {legacy}\n"
            f"cactus: adopt it with  mkdir -p {target.parent} && "
            f"sqlite3 {legacy} \"VACUUM INTO '{target}'\"",
            file=sys.stderr,
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- writes -----------------------------------------------------------

    def ask(
        self,
        text: str,
        *,
        project: str,
        cwd: str,
        kind: str = "text",
        act: str = "ask",
        agent: str | None = None,
        word: str | None = None,
        workspace: str | None = None,
        tab: str | None = None,
        pane: str | None = None,
        session: str | None = None,
        title: str | None = None,
        chosen: str | None = None,
        blocked: bool | None = None,
        source: str | None = None,
        choices: Sequence[Choice] | None = None,
        allow_free: bool = True,
        recommend: Sequence[str] | None = None,
        confidence: str | None = None,
        recommend_why: str | None = None,
        thread: str | None = None,
        parent_key: str | None = None,
        parent_project: str | None = None,
        context: str | None = None,
        asked_by: str | None = None,
        files: Sequence[str] | None = None,
    ) -> Question:
        """Insert one question and return it, with its assigned key.

        `parent_project` scopes `parent_key` when it names a row in a
        different project than this one — a qualified `LABEL:qN` follow-up
        (q166). Defaults to this question's own `project`.
        """
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        if act not in ACTS:
            raise ValueError(f"act must be one of {ACTS}, got {act!r}")
        if kind not in ACT_SHAPES[act]:
            raise ValueError(
                f"act={act!r} accepts kind {ACT_SHAPES[act]}, got {kind!r}"
            )
        if word is not None and len(word) > 16:
            raise ValueError(
                "--word is at most 16 characters: a board walks its letters "
                "for collision fallback"
            )
        if title is not None and len(title) > 60:
            raise ValueError("--title is at most 60 characters")
        choices = list(choices or [])
        if kind in ("choice", "multi") and not choices:
            raise ValueError(f"kind={kind!r} requires at least one choice")
        if kind == "confirm" and not choices:
            # The act names the verdict: a review passes or fails, a command is
            # approved or denied, and neither reads as yes/no on a board key.
            defaults = {"review": ("pass", "fail"), "run": ("approve", "deny")}
            a, b = defaults.get(act, ("yes", "no"))
            choices = [Choice(a), Choice(b)]
        if chosen is not None and choices:
            labels = [c.label for c in choices]
            if chosen not in labels:
                raise ValueError(f"chosen must be one of {labels}, got {chosen!r}")
        if act == "steer" and chosen is None:
            raise ValueError(
                "act='steer' needs a chosen option: a steer states what "
                "happens anyway, and one that states nothing is an ask"
            )
        recommend = list(recommend or [])
        if recommend:
            # A recommendation is advisory and still waits for the human,
            # unlike `chosen`, which proceeds — so it only makes sense on a
            # row that offers something to pick, filled in with the confirm
            # defaults above so review/run/confirm rows can recommend too.
            if not choices:
                raise ValueError("recommend requires choices")
            labels = [c.label for c in choices]
            bad = [r for r in recommend if r not in labels]
            if bad:
                raise ValueError(f"recommend must name options from {labels}, got {bad!r}")
            if len(recommend) > 1 and kind != "multi":
                raise ValueError(
                    "recommend names more than one option only when kind='multi'"
                )
            if confidence is None:
                raise ValueError(f"recommend needs --confidence, one of {CONFIDENCE}")
            if confidence not in CONFIDENCE:
                raise ValueError(f"confidence must be one of {CONFIDENCE}, got {confidence!r}")
        elif confidence is not None or recommend_why is not None:
            raise ValueError("confidence or recommend_why given without recommend")
        if blocked is None:
            blocked = DEFAULT_BLOCKED[act]
        if blocked and act in PERSISTENT_ACTS:
            raise ValueError(
                f"act={act!r} is persistent and cannot block: it is answered "
                f"again whenever the work is re-checked"
            )

        parent_id = None
        if parent_key:
            parent = self.get(parent_key, project=parent_project or project)
            if parent is None:
                raise KeyError(f"no such question: {parent_key}")
            parent_id = parent.id
            # A follow-up inherits its parent's thread unless told otherwise.
            if thread is None:
                thread = parent.thread

        now = _now()
        # A persistent row is born `live`: it is answerable straight away and
        # stays answerable, so it never occupies `open` and never blocks a
        # waiting agent.
        status = "live" if act in PERSISTENT_ACTS else "open"
        # Race-free numbering across processes (q166): both the read of the
        # current max and the insert that claims the next number happen
        # inside one BEGIN IMMEDIATE, which takes SQLite's write lock up
        # front rather than at the first write, so two processes asking in
        # the same project at once serialize on it instead of both reading
        # the same max and colliding.
        per_project = not self.needs_key_rebuild()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if per_project:
                row = self.conn.execute(
                    "SELECT COALESCE(MAX(num), 0) AS n FROM questions WHERE project = ?",
                    (project,),
                ).fetchone()
                num = int(row["n"]) + 1
            else:
                # Pre-migration: `key` is still globally UNIQUE, so keys stay
                # numbered off the row id exactly as before.
                num = None
            cur = self.conn.execute(
                """
                INSERT INTO questions
                    (key, num, project, cwd, thread, parent_id, text, kind, act, agent,
                     word, workspace, tab, pane, session, title, chosen, blocked, source,
                     choices, allow_free, recommend, confidence, recommend_why,
                     context, asked_by, status, created_at, updated_at, files)
                VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    num, project, cwd, thread, parent_id, text, kind, act, agent, word,
                    workspace, tab, pane, session, title,
                    chosen, 1 if blocked else 0, source,
                    json.dumps([c.as_dict() for c in choices]),
                    1 if allow_free else 0,
                    json.dumps(recommend) if recommend else None,
                    confidence, recommend_why,
                    context, asked_by, status, now, now,
                    json.dumps(list(files)) if files else None,
                ),
            )
            rowid = int(cur.lastrowid)
            if num is None:
                num = rowid
            key = f"q{num}"
            self.conn.execute(
                "UPDATE questions SET key = ?, num = ? WHERE id = ?", (key, num, rowid)
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        result = self._get_by_id(rowid)
        assert result is not None
        return result

    def answer(
        self,
        key: str,
        *,
        project: str | None = None,
        selected: Sequence[str] | None = None,
        text: str | None = None,
        skipped: bool = False,
    ) -> Question:
        """Append an answer.

        A one-shot question flips to `answered`. A persistent one stays `live`
        and keeps its earlier verdicts: the append-only log is what lets a
        review row be passed today and failed tomorrow, and what makes the
        monitor stream an event feed rather than a status poll.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if self.needs_rebuild():
            raise RuntimeError(
                "this database still has UNIQUE(question_id) on answers, which "
                "an append-only log cannot use — run `cactus migrate` once, "
                "and restart anything holding an older cactus module"
            )
        if q.status == "cleared":
            raise ValueError(
                f"{key} is cleared; cactus reopen {key} --agent ID first"
            )
        if q.status == "elaborate":
            raise ValueError(
                f"{key} is awaiting elaboration; cactus edit {key} --agent ID first"
            )
        if not q.persistent and q.status == "answered":
            raise AlreadyAnswered(
                f"{key} was already answered "
                f"{'with ' + ', '.join(q.answer.selected) if q.answer and q.answer.selected else ''}"
                f" — undo it first if that verdict should change".replace("  ", " ")
            )
        selected = list(selected or [])
        if selected and not q.choices:
            raise ValueError(f"{key} has no choices; answer with text")
        if q.choices and selected:
            valid = [c.label for c in q.choices]
            for label in selected:
                if label not in valid:
                    raise ValueError(
                        f"{key} has no choice '{label}'; choices are {', '.join(valid)}"
                    )
        if not q.allow_free and text and text.strip():
            valid = [c.label for c in q.choices]
            raise ValueError(f"{key} takes no free text; pick from {', '.join(valid)}")
        if not skipped and not selected and not (text and text.strip()):
            raise ValueError(
                f"{key}: nothing chosen and nothing typed; pick a label, give "
                f"text, or --skip"
            )
        now = _now()
        status = "live" if q.persistent else "answered"
        # One explicit transaction, not two autocommitted statements: in
        # autocommit mode (isolation_level=None) each execute() commits on
        # its own, so a poller — the monitor, another TUI tick — can land
        # between the INSERT and the UPDATE and see an answer attached to a
        # question whose status has not moved yet. That mid-flight read and
        # the settled one differ, so the monitor emitted `answered` twice for
        # one answer. Wrapping both writes in one transaction makes them a
        # single state change from any other reader's point of view.
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                """
                INSERT INTO answers (question_id, selected, text, skipped, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (q.id, json.dumps(list(selected or [])), text, 1 if skipped else 0, now),
            )
            self.conn.execute(
                "UPDATE questions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, q.id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        result = self._get_by_id(q.id)
        assert result is not None
        self._record(result, event="answer")
        return result

    def clear(
        self,
        *,
        keys: Sequence[str] | None = None,
        project: str | None = None,
        thread: str | None = None,
        all_projects: bool = False,
        include_answered: bool = True,
        agent: str | None = None,
        record: bool = True,
    ) -> int:
        """Mark questions cleared. Returns the number of rows affected.

        Clearing is a status change, not a delete — the transcript survives so a
        thread can still be read back after the agent has moved on.

        `agent`, when given, restricts the update to rows owned by it — a
        NULL-owned row never matches `agent = ?`, so an unowned row is left
        alone without a separate check. The refusal policy for who may pass
        which `agent` lives in cli.py; this is mechanism only.

        `record`, when False, skips the decision-record write entirely rather
        than writing `declined`/`retired` — the CLI's agent-initiated `clear`
        passes this, because a record documents a human decision and an agent
        clearing its own row is bookkeeping, not a verdict. The TUI's human
        `c` keeps the default and writes the record as before.
        """
        where, params = self._scope_where(
            keys=keys, project=project, thread=thread, all_projects=all_projects
        )
        if agent is not None:
            where.append("agent = ?")
            params.append(agent)
        if not include_answered:
            where.append("status = 'open'")
        else:
            where.append("status != 'cleared'")
        clause = " AND ".join(where)
        # Keys first, so the record for each row can be written after the
        # UPDATE commits — a bulk clear can touch many rows in one statement,
        # and the record is per-row.
        affected = [
            int(r["id"]) for r in self.conn.execute(
                "SELECT id FROM questions WHERE " + clause, params
            )
        ]
        sql = "UPDATE questions SET status = 'cleared', updated_at = ? WHERE " + clause
        cur = self.conn.execute(sql, [_now(), *params])
        if record:
            for qid in affected:
                row = self._get_by_id(qid)
                if row is not None:
                    self._record(row, event="clear")
        return cur.rowcount

    def reopen(self, key: str, *, project: str | None = None) -> Question:
        """Withdraw the latest answer, or restore a cleared row.

        Undo for the human surfaces. On an answered or live row it cannot
        recall an answer an agent has already read — `--wait` returns the
        moment the status leaves `open` — so the question simply becomes
        askable again.

        On a *cleared* row there is nothing to withdraw: `clear` only ever
        flips `status`, so the answers log, review, and steps are exactly as
        they were. Restoring just moves status back — to `live` for a
        persistent row (review, plan), keeping every verdict; to `answered`
        for a one-shot row that already had one, else `open`. Undoing a
        `clear` this way is what recovers a cleared review/plan row, which
        the answer-withdrawing path below cannot do without deleting the
        latest verdict it was never meant to touch.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        now = _now()
        if q.status == "cleared":
            withdrawn_answer = None
            if q.persistent:
                status = "live"
            else:
                status = "answered" if q.answer is not None else "open"
            event = "restore"
        else:
            withdrawn_answer = q.answer
            # Only the latest verdict is withdrawn. On a persistent row that
            # uncovers the previous one rather than returning the row to unanswered.
            self.conn.execute(
                "DELETE FROM answers WHERE id = ("
                " SELECT id FROM answers WHERE question_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT 1)",
                (q.id,),
            )
            remaining = self.conn.execute(
                "SELECT COUNT(*) AS n FROM answers WHERE question_id = ?", (q.id,)
            ).fetchone()["n"]
            if q.persistent:
                status = "live"
            else:
                status = "answered" if remaining else "open"
            event = "reopen"
        self.conn.execute(
            "UPDATE questions SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, q.id),
        )
        result = self._get_by_id(q.id)
        assert result is not None
        self._record(result, event=event, withdrawn_answer=withdrawn_answer)
        return result

    def purge(
        self,
        *,
        keys: Sequence[str] | None = None,
        project: str | None = None,
        thread: str | None = None,
        all_projects: bool = False,
        agent: str | None = None,
    ) -> int:
        """Delete rows outright. Follow-ups cascade with their parent.

        `agent` restricts the delete the same way it restricts `clear`.
        """
        where, params = self._scope_where(
            keys=keys, project=project, thread=thread, all_projects=all_projects
        )
        if agent is not None:
            where.append("agent = ?")
            params.append(agent)
        sql = "DELETE FROM questions WHERE " + " AND ".join(where)
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def set_review(
        self,
        key: str,
        *,
        project: str | None = None,
        look_at: str | None = None,
        run_cmd: str | None = None,
        pass_when: str | None = None,
        fail_when: str | None = None,
        then_do: str | None = None,
    ) -> Question:
        """Attach or merge the verify block on a `review` row.

        Each call updates only the fields it passes; an omitted field (`None`)
        keeps its stored value rather than being wiped. Passing an empty
        string clears a field explicitly — `None` and `""` are different
        callers' intents, and argparse already tells them apart: a flag left
        off a command line is `None`, a flag given as `--run ""` is `""`.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        # `run` rows carry a command too, and it belongs in the same place as a
        # review's: both are rows where something is going to be executed and
        # the human decides whether it should be.
        if q.act not in ("review", "run"):
            raise ValueError(f"{key} is act={q.act!r}, not 'review' or 'run'")
        if q.status == "cleared":
            raise ValueError(
                f"{key} is cleared; cactus reopen {key} --agent ID first"
            )
        existing = q.review or Review()
        merged = Review(
            look_at=existing.look_at if look_at is None else look_at,
            run_cmd=existing.run_cmd if run_cmd is None else run_cmd,
            pass_when=existing.pass_when if pass_when is None else pass_when,
            fail_when=existing.fail_when if fail_when is None else fail_when,
            then_do=existing.then_do if then_do is None else then_do,
        )
        self.conn.execute(
            """
            INSERT INTO reviews (question_id, look_at, run_cmd, pass_when, fail_when, then_do)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                look_at   = excluded.look_at,
                run_cmd   = excluded.run_cmd,
                pass_when = excluded.pass_when,
                fail_when = excluded.fail_when,
                then_do   = excluded.then_do
            """,
            (q.id, merged.look_at, merged.run_cmd, merged.pass_when,
             merged.fail_when, merged.then_do),
        )
        return self._touch(q.id)

    def set_run_result(
        self, key: str, *, project: str | None = None, exit_code: int, tail: Sequence[str], log: str
    ) -> Question:
        """Attach the captured outcome of running a row's command.

        Written once the command finishes (or is killed, or fails to start).
        On a `run` row this happens alongside the `answer()` call that records
        approve/deny — this is the durable place `get --json`, `feed`, and the
        monitor read the result from, since the answer alone only says
        approve/deny, not what happened. On a `review` row (q20) the human's
        `R` still only runs it, never answers it — the pass/fail verdict
        stays theirs — but the result is written the same way so the asking
        agent can read it back too.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.act not in ("run", "review"):
            raise ValueError(f"{key} is act={q.act!r}, not 'run' or 'review'")
        self.conn.execute(
            "UPDATE questions SET run_exit = ?, run_tail = ?, run_log = ? WHERE id = ?",
            (exit_code, json.dumps(list(tail)), log, q.id),
        )
        return self._touch(q.id)

    def set_steps(
        self, key: str, steps: Sequence[str], *, project: str | None = None, reset: bool = False
    ) -> Question:
        """Add steps to a `plan` row, or replace them outright.

        Default appends `steps` after whatever is already there, keeping the
        existing steps and their done flags — a plan is built up call by call,
        and each `--step` used to wipe the previous ones out from under it.
        `reset=True` (`--reset-steps`) replaces the list with this call's
        steps and clears all done flags, for when the plan itself changed.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.act != "plan":
            raise ValueError(f"{key} is act={q.act!r}, not 'plan'")
        if q.status == "cleared":
            raise ValueError(
                f"{key} is cleared; cactus reopen {key} --agent ID first"
            )
        for t in steps:
            if not t or not t.strip():
                raise ValueError("a step's text cannot be empty or whitespace-only")
        if reset:
            self.conn.execute("DELETE FROM steps WHERE question_id = ?", (q.id,))
            self.conn.executemany(
                "INSERT INTO steps (question_id, idx, text, done) VALUES (?, ?, ?, ?)",
                [(q.id, i, t, 0) for i, t in enumerate(steps)],
            )
        else:
            start = len(q.steps)
            self.conn.executemany(
                "INSERT INTO steps (question_id, idx, text, done) VALUES (?, ?, ?, ?)",
                [(q.id, start + i, t, 0) for i, t in enumerate(steps)],
            )
        return self._touch(q.id)

    def set_step_done(
        self, key: str, idx: int, done: bool = True, *, project: str | None = None
    ) -> Question:
        """Tick or untick one step.

        Both the human surfaces and the agent write this, which is why steps are
        rows rather than a JSON blob on the question: a blob would make every
        toggle a read-modify-write race between the two writers.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.status == "cleared":
            raise ValueError(
                f"{key} is cleared; cactus reopen {key} --agent ID first"
            )
        cur = self.conn.execute(
            "UPDATE steps SET done = ? WHERE question_id = ? AND idx = ?",
            (1 if done else 0, q.id, idx),
        )
        if cur.rowcount == 0:
            raise KeyError(f"{key} has no step {idx}")
        return self._touch(q.id)

    def set_auto(
        self,
        key_or_id: str | int,
        pick: str | None,
        confidence: float | None,
        reason: str | None,
        *,
        project: str | None = None,
    ) -> Question:
        """Record the auto-decider's proposal on an open row.

        `pick=None` records a HELD row: ranked and not proposed on, `reason`
        says why. `auto_at` is stamped either way, so the row is classified
        once and never re-ranked until an edit clears `auto_*`.

        Advisory only: it never answers, and it stays out of the monitor
        signature so the asking agent is not woken by it. `updated_at` is
        bumped so the TUI poll sees the new proposal.
        """
        q = self._resolve_auto(key_or_id, project)
        if q.status != "open":
            raise ValueError(f"{q.key} is {q.status}; a proposal needs an open row")
        labels = [c.label for c in q.choices]
        if pick is not None and pick not in labels:
            raise ValueError(f"{pick!r} is not one of {q.key}'s choices: {labels}")
        now = _now()
        self.conn.execute(
            "UPDATE questions SET auto_pick = ?, auto_confidence = ?, "
            "auto_reason = ?, auto_at = ?, updated_at = ? WHERE id = ?",
            (pick, None if pick is None else confidence, reason, now, now, q.id),
        )
        result = self._get_by_id(q.id)
        assert result is not None
        return result

    def clear_auto(
        self, key_or_id: str | int, *, project: str | None = None
    ) -> Question:
        """Drop a row's proposal (all four `auto_*` fields)."""
        q = self._resolve_auto(key_or_id, project)
        self.conn.execute(
            "UPDATE questions SET auto_pick = NULL, auto_confidence = NULL, "
            "auto_reason = NULL, auto_at = NULL, updated_at = ? WHERE id = ?",
            (_now(), q.id),
        )
        result = self._get_by_id(q.id)
        assert result is not None
        return result

    def _resolve_auto(self, key_or_id: str | int, project: str | None) -> Question:
        q = (
            self._get_by_id(key_or_id) if isinstance(key_or_id, int)
            else self.get(key_or_id, project=project)
        )
        if q is None:
            raise KeyError(f"no such question: {key_or_id}")
        return q

    def mark_heard(self, qid: int) -> Question | None:
        """Stamp `heard_at` when the owner reads a review/plan row (q406).

        Moves only forward past the latest verdict: a row with no verdict, or
        one already stamped after it, is left alone (no `updated_at` bump, so a
        polling `get --agent` never churns the TUI). Ownership is the CLI's job.
        """
        q = self._get_by_id(qid)
        if q is None or q.act not in ("review", "plan") or q.answer is None:
            return q
        if q.heard_at and q.heard_at > q.answer.created_at:
            return q
        now = _now()
        self.conn.execute(
            "UPDATE questions SET heard_at = ?, updated_at = ? WHERE id = ?",
            (now, now, qid),
        )
        return self._get_by_id(qid)

    def mark_responded(self, qid: int) -> Question | None:
        """Stamp `responded_at` after the owner writes to a row (q406).

        The stamp lives here, the call site in `cli.py` behind the ownership
        check, so a TUI write through the same store methods never stamps it.
        """
        now = _now()
        self.conn.execute(
            "UPDATE questions SET responded_at = ?, updated_at = ? WHERE id = ?",
            (now, now, qid),
        )
        return self._get_by_id(qid)

    def elaborate_request(
        self, key: str, *, hint: str | None = None, project: str | None = None
    ) -> Question:
        """Ask the owning agent to rewrite a row (q212).

        Only an `open` or `live` row can be asked — the same rows a human can
        already reach from the TUI's `e`. The row stops taking answers (see
        `answer`'s refusal) until `edit` addresses it and moves it back.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.status not in ("open", "live"):
            raise ValueError(
                f"{key} is {q.status}; elaborate only applies to an open or live row"
            )
        now = _now()
        self.conn.execute(
            "UPDATE questions SET status = 'elaborate', elaborate = ?, "
            "elaborate_at = ?, last_change = NULL, updated_at = ? WHERE id = ?",
            (hint, now, now, q.id),
        )
        result = self._get_by_id(q.id)
        assert result is not None
        self._record(result, event="elaborate")
        return result

    def unelaborate(self, key: str, *, project: str | None = None) -> Question:
        """Withdraw an elaborate request before the agent has addressed it.

        The TUI's `u` after `e`. Refused once the row has left `elaborate` —
        the agent may already have read and edited it, and this cannot
        un-ring that bell (the same limit `reopen` has on a read answer).

        Stamps `last_change = 'withdrawn'` (q228) so the monitor can tell this
        apart from `edit` clearing the same status — both leave the row at
        the same `open`/`live` status, an identical before/after diff.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.status != "elaborate":
            raise ValueError(f"{key} is not awaiting elaboration")
        new_status = "live" if q.persistent else "open"
        now = _now()
        self.conn.execute(
            "UPDATE questions SET status = ?, elaborate = NULL, elaborate_at = NULL, "
            "last_change = 'withdrawn', updated_at = ? WHERE id = ?",
            (new_status, now, q.id),
        )
        result = self._get_by_id(q.id)
        assert result is not None
        # A one-line note on an existing record only — never conjures one.
        # `elaborate_request` already wrote the record this row has, if any;
        # a withdrawal a human changed their mind about is bookkeeping on
        # that record, not a fresh verdict of its own.
        self._record_if_exists(result, event="unelaborate")
        return result

    def edit(
        self,
        key: str,
        *,
        agent: str,
        project: str | None = None,
        text: str | None = None,
        context: str | None = None,
        choices: Sequence[Choice] | None = None,
        files: Sequence[str] | None = None,
    ) -> Question:
        """Replace the given fields on an open/live/elaborate row, in place.

        On a row in `elaborate` status this doubles as the agent's answer to
        the request: it clears the hint and moves status back to `open` (or
        `live` for a persistent act) whether or not any field actually
        changed. On any other open/live row it is a plain fix — a typo, a
        fact the agent adds unprompted — and status is untouched.

        `agent` names the caller for the record only; ownership refusal is
        the CLI's job, the same split `clear`/`reopen` already use.
        `-c` (`choices`, when not None) replaces the whole list; a
        recommendation naming a label that falls off it is cleared along
        with its confidence and rationale, since it would otherwise point at
        nothing real.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.status not in ("open", "live", "elaborate"):
            raise ValueError(
                f"{key} is {q.status}; edit only applies to an open, live, "
                f"or elaborate row"
            )

        new_text = q.text if text is None else text
        if not new_text or not new_text.strip():
            raise ValueError("edit would leave the question text empty")
        new_context = q.context if context is None else context
        new_files = q.files if files is None else list(files)

        if choices is not None:
            if q.kind in ("choice", "multi", "confirm") and not choices:
                raise ValueError(f"kind={q.kind!r} requires at least one choice")
            labels = [c.label for c in choices]
            if len(labels) != len(set(labels)):
                raise ValueError(f"duplicate choice labels: {labels}")
            new_choices = choices
            new_recommend = [r for r in q.recommend if r in labels]
        else:
            new_choices = q.choices
            new_recommend = list(q.recommend)

        if new_recommend:
            new_confidence = q.confidence
            new_recommend_why = q.recommend_why
        else:
            new_confidence = None
            new_recommend_why = None

        was_elaborate = q.status == "elaborate"
        new_status = ("live" if q.persistent else "open") if was_elaborate else q.status
        # Stamped only on the transition out of `elaborate` (q228) — the same
        # marker `unelaborate` sets to 'withdrawn', read by the monitor to
        # tell the two apart. A plain edit outside `elaborate` leaves it as
        # it was; that path is already told apart by its text/choices/
        # context/recommend diff, not by this column.
        new_last_change = "edited" if was_elaborate else q.last_change

        # A proposal was made against the old wording; once the text or the
        # choices move it is stale, so it goes.
        stale_auto = (
            new_text != q.text
            or [c.as_dict() for c in new_choices] != [c.as_dict() for c in q.choices]
        )

        now = _now()
        self.conn.execute(
            """
            UPDATE questions
            SET text = ?, context = ?, choices = ?, recommend = ?, confidence = ?,
                recommend_why = ?, status = ?, elaborate = NULL, elaborate_at = NULL,
                last_change = ?, updated_at = ?, files = ?
            WHERE id = ?
            """,
            (
                new_text, new_context,
                json.dumps([c.as_dict() for c in new_choices]),
                json.dumps(new_recommend) if new_recommend else None,
                new_confidence, new_recommend_why,
                new_status, new_last_change, now,
                json.dumps(new_files) if new_files else None,
                q.id,
            ),
        )
        if stale_auto:
            self.conn.execute(
                "UPDATE questions SET auto_pick = NULL, auto_confidence = NULL, "
                "auto_reason = NULL, auto_at = NULL WHERE id = ?",
                (q.id,),
            )
        result = self._get_by_id(q.id)
        assert result is not None
        self._record_if_exists(
            result, event="edit",
            prior={
                "text": q.text, "context": q.context, "choices": q.choices,
                "files": q.files,
            },
        )
        return result

    def set_files(
        self, key: str, files: Sequence[str], *, project: str | None = None
    ) -> Question:
        """Replace a row's attached file list outright (empty clears it).

        The `-f`/`--file` primitive behind `cactus review`/`cactus plan`,
        which have no other path to `edit`'s field set. No partial merge —
        same whole-list-replace semantics `edit`'s `-c` already has for
        choices.
        """
        q = self.get(key, project=project)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.status == "cleared":
            raise ValueError(
                f"{key} is cleared; cactus reopen {key} --agent ID first"
            )
        self.conn.execute(
            "UPDATE questions SET files = ? WHERE id = ?",
            (json.dumps(list(files)) if files else None, q.id),
        )
        return self._touch(q.id)

    def _record(
        self, row: Question, *, event: str, withdrawn_answer: Answer | None = None
    ) -> None:
        """Write a decision record for a state change. Never raises.

        CACTUS_RECORDS=0 disables writing outright (tests, and anyone who opts
        out). Any other failure — an unwritable .ai/cactus, a project root that
        no longer exists — is a warning, not an error: the DB write it follows
        already committed, and a record is a courtesy copy of it, not the
        source of truth.
        """
        if os.environ.get("CACTUS_RECORDS") == "0":
            return
        from . import record as _record_mod

        try:
            _record_mod.write_record(row, event=event, withdrawn_answer=withdrawn_answer)
        except Exception as exc:
            msg = f"cactus: record for {row.key} not written: {exc}"
            if self.record_warning is not None:
                self.record_warning(msg)
            else:
                print(msg, file=sys.stderr)

    def _record_if_exists(
        self, row: Question, *, event: str, prior: dict[str, Any] | None = None
    ) -> None:
        """Update a row's decision record only if one already exists.

        `edit` is an agent action — bookkeeping like the CLI's own agent-
        initiated `clear`, not a human verdict (records only write on
        human-originated events and answers, 4659beb) — so it must not
        conjure a record for a row that never had one. If the row was
        already recorded (answered, cleared, or elaborated on), the rewrite
        keeps that record in sync, with `prior` showing what it replaced.
        """
        if os.environ.get("CACTUS_RECORDS") == "0":
            return
        from . import record as _record_mod

        try:
            path = _record_mod.record_path(row)
            if not path.exists():
                return
            _record_mod.write_record(row, event=event, prior=prior)
        except Exception as exc:
            msg = f"cactus: record for {row.key} not written: {exc}"
            if self.record_warning is not None:
                self.record_warning(msg)
            else:
                print(msg, file=sys.stderr)

    def _touch(self, qid: int) -> Question:
        """Bump `updated_at` so a sidecar-only write still moves the cursor."""
        self.conn.execute(
            "UPDATE questions SET updated_at = ? WHERE id = ?", (_now(), qid)
        )
        result = self._get_by_id(qid)
        assert result is not None
        return result

    # ---- reads ------------------------------------------------------------

    def get(self, key: str, project: str | None = None) -> Question | None:
        """Look up a bare key.

        `project` disambiguates it: post-migration (q166) `key` is only unique
        within a project, so two projects can each hold a "q1". Without
        `project` this falls back to a bare match across every project —
        correct on a pre-migration database, where `key` is still globally
        unique, and a best-effort for internal callers that have not been
        updated to pass scope.
        """
        if project is not None:
            row = self.conn.execute(
                "SELECT * FROM questions WHERE project = ? AND key = ?", (project, key)
            ).fetchone()
        else:
            rows = self.conn.execute(
                "SELECT * FROM questions WHERE key = ? ORDER BY id ASC LIMIT 2", (key,)
            ).fetchall()
            # A bare key held by two projects must not resolve to either: the
            # oldest-row fallback wrote TUI answers into another project's row.
            if len(rows) > 1:
                raise ValueError(f"{key} exists in more than one project; pass project")
            row = rows[0] if rows else None
        return self._hydrate(row) if row else None

    def _get_by_id(self, qid: int) -> Question | None:
        """Reload a row already resolved once in this call, by its stable id.

        Used after a mutation to re-fetch the updated row without repeating a
        key lookup that — post-migration — needs a project to stay
        unambiguous. `id` never collides, so this sidesteps that entirely.
        """
        row = self.conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        return self._hydrate(row) if row else None

    class AmbiguousLabel(ValueError):
        """A project label (q166's `LABEL:qN`) matches more than one project root."""

        def __init__(self, label: str, paths: Sequence[str]) -> None:
            self.label = label
            self.paths = list(paths)
            super().__init__(
                f"'{label}' matches multiple projects: {', '.join(self.paths)}"
            )

    _REF_RE = re.compile(r"^(.*):([Qq]\d+)$")

    def resolve_ref(self, raw: str, default_project: str) -> tuple[str, str]:
        """Split a possibly-qualified key into (project, bare key) (q166).

        Accepts a bare `qN` (resolved in `default_project`), `LABEL:qN` —
        matched against every known project's basename — or `/abs/path:qN`.
        A label matching more than one project raises AmbiguousLabel rather
        than guessing; a label matching none is left unresolved, so the
        caller's own "no such question" path reports it as a miss.
        """
        m = self._REF_RE.match(raw)
        if not m:
            return default_project, raw
        qualifier, bare = m.group(1), m.group(2)
        if not qualifier:
            return default_project, bare
        if qualifier.startswith("/"):
            # Resolved the same way `resolve_project` resolves a cwd, so a
            # symlinked tmp dir (macOS's /var -> /private/var) still matches
            # the project root a row was actually stored under.
            try:
                return str(Path(qualifier).expanduser().resolve()), bare
            except OSError:
                return qualifier, bare
        known = {r["project"] for r in self.conn.execute("SELECT DISTINCT project FROM questions")}
        matches = sorted(p for p in known if project_label(p) == qualifier)
        if len(matches) > 1:
            raise Store.AmbiguousLabel(qualifier, matches)
        if len(matches) == 1:
            return matches[0], bare
        return default_project, raw

    def list(
        self,
        *,
        project: str | None = None,
        thread: str | None = None,
        status: str | Sequence[str] | None = "open",
        all_projects: bool = False,
        keys: Sequence[str] | None = None,
        acts: Sequence[str] | None = None,
        agent: str | None = None,
        workspace: str | None = None,
        tab: str | None = None,
        pane: str | None = None,
        limit: int | None = None,
    ) -> list[Question]:
        where, params = self._scope_where(
            keys=keys, project=project, thread=thread, all_projects=all_projects
        )
        if acts:
            where.append("act IN (%s)" % ",".join("?" * len(acts)))
            params.extend(acts)
        if agent is not None:
            where.append("agent = ?")
            params.append(agent)
        if workspace is not None:
            where.append("workspace = ?")
            params.append(workspace)
        if tab is not None:
            where.append("tab = ?")
            params.append(tab)
        if pane is not None:
            where.append("pane = ?")
            params.append(pane)
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            where.append("status IN (%s)" % ",".join("?" * len(statuses)))
            params.extend(statuses)
        # Ordered by rowid, always. A projector assigns board letters from feed
        # order, so an unstable order re-letters a menu under a hand holding it.
        sql = "SELECT * FROM questions WHERE " + " AND ".join(where) + " ORDER BY id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._hydrate(r) for r in rows]

    def projects(self) -> list[dict[str, Any]]:
        """Projects with live questions, counted by status, ranked by rows due.

        Cleared questions are excluded outright — a project whose whole inbox has
        been retired should not keep a row in the rail. `due_count` is
        `open + elaborate` (q351) — `live` is re-answerable but never blocks
        anyone, so it stays out of what "due" means; the projects page and the
        projects pane both rank by it.
        """
        rows = self.conn.execute(
            """
            WITH known_projects AS (
                SELECT project FROM questions
                UNION
                SELECT project FROM project_settings
            )
            SELECT known_projects.project,
                   COALESCE(project_settings.enabled, 1) AS enabled,
                   SUM(CASE WHEN questions.status = 'open' THEN 1 ELSE 0 END) AS open_count,
                   SUM(CASE WHEN questions.status = 'live' THEN 1 ELSE 0 END) AS live_count,
                   SUM(CASE WHEN questions.status = 'elaborate' THEN 1 ELSE 0 END) AS elaborate_count,
                   SUM(CASE WHEN questions.status = 'answered' THEN 1 ELSE 0 END) AS answered_count,
                   COUNT(questions.id) AS total,
                   MAX(questions.updated_at) AS last_activity,
                   MAX(CASE WHEN questions.status IN ('open', 'live', 'elaborate')
                            THEN questions.created_at END) AS newest_open,
                   SUM(CASE WHEN questions.status IN ('open', 'elaborate') THEN 1 ELSE 0 END) AS due_count
            FROM known_projects
            LEFT JOIN project_settings ON project_settings.project = known_projects.project
            LEFT JOIN questions ON questions.project = known_projects.project
                              AND questions.status != 'cleared'
            GROUP BY known_projects.project
            ORDER BY due_count DESC, last_activity DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def project_panes(self, project: str) -> dict[str, Any]:
        """The herdr panes a project-wide poke can reach.

        Distinct non-null `pane` stamps over the project's `open`/`live`/
        `elaborate` rows, each with the `agent` of that pane's newest row,
        plus `skipped`: how many of those rows carry no pane and so cannot
        be prompted. A pane id names a pane inside one herdr session, so
        panes are distinct per `(session, pane)`. Returns
        `{"panes": [{"pane", "session", "agent"}], "skipped": N}`.
        """
        rows = self.conn.execute(
            """
            SELECT pane, session, agent FROM questions
            WHERE project = ? AND status IN ('open', 'live', 'elaborate')
            ORDER BY id
            """,
            (project,),
        ).fetchall()
        latest: dict[tuple[str, str | None], str | None] = {}
        skipped = 0
        for r in rows:
            if r["pane"]:
                latest[(r["pane"], r["session"])] = r["agent"]
            else:
                skipped += 1
        return {
            "panes": [{"pane": p, "session": s, "agent": a} for (p, s), a in latest.items()],
            "skipped": skipped,
        }

    def history(self, project: str, limit: int = 200) -> list[Question]:
        """Answered and cleared rows that carry at least one verdict (q347).

        The answers view's backing query: newest-verdict-first, where "newest"
        is the latest answer's own timestamp, not the row's `updated_at` — a
        persistent row's most recent verdict is what should sort it, not the
        last time anything else touched the row. A cleared or answered row with
        no answer at all (dismissed, purely skipped-and-cleared) is history of
        nothing and stays out.
        """
        rows = self.conn.execute(
            """
            SELECT q.*, MAX(a.created_at) AS latest_answer_at
            FROM questions q
            JOIN answers a ON a.question_id = q.id
            WHERE q.project = ? AND q.status IN ('answered', 'cleared')
            GROUP BY q.id
            ORDER BY latest_answer_at DESC
            LIMIT ?
            """,
            (project, int(limit)),
        ).fetchall()
        return [self._hydrate(r) for r in rows]

    def project_enabled(self, project: str) -> bool:
        """Whether Cactus hooks are active for this project (default: active)."""
        row = self.conn.execute(
            "SELECT enabled FROM project_settings WHERE project = ?", (project,)
        ).fetchone()
        return row is None or bool(row["enabled"])

    def set_project_enabled(self, project: str, enabled: bool) -> None:
        """Persist a project hook switch, visible to every process sharing this DB."""
        self.conn.execute(
            """
            INSERT INTO project_settings(project, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(project) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (project, int(enabled), _now()),
        )
        self.conn.commit()

    def threads(self, *, project: str | None = None, all_projects: bool = False) -> list[dict[str, Any]]:
        where, params = self._scope_where(project=project, all_projects=all_projects)
        where.append("status != 'cleared'")
        rows = self.conn.execute(
            "SELECT thread, project, COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('open', 'live', 'elaborate') THEN 1 ELSE 0 END) "
            "AS open_count, "
            "MAX(updated_at) AS last_activity "
            "FROM questions WHERE " + " AND ".join(where) +
            " GROUP BY project, thread ORDER BY last_activity DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def tree(
        self,
        *,
        project: str | None = None,
        thread: str | None = None,
        status: str | Sequence[str] | None = None,
        all_projects: bool = False,
        acts: Sequence[str] | None = None,
        agent: str | None = None,
        workspace: str | None = None,
        tab: str | None = None,
        pane: str | None = None,
    ) -> list[Question]:
        """Questions in parent-before-child order, each carrying its `depth`.

        A follow-up is only reachable through its parent, so a child whose parent
        is out of scope is promoted to depth 0 rather than being dropped.
        """
        items = self.list(
            project=project, thread=thread, status=status,
            all_projects=all_projects, acts=acts, agent=agent,
            workspace=workspace, tab=tab, pane=pane,
        )
        by_id = {q.id: q for q in items}
        children: dict[int | None, list[Question]] = {}
        for q in items:
            anchor = q.parent_id if q.parent_id in by_id else None
            children.setdefault(anchor, []).append(q)

        ordered: list[Question] = []

        def walk(anchor: int | None, depth: int) -> None:
            for q in children.get(anchor, []):
                q.depth = depth
                ordered.append(q)
                walk(q.id, depth + 1)

        walk(None, 0)
        return ordered

    def cursor(self) -> tuple[int, str, int]:
        """Cheap change token: (max question id, max updated_at, row count).

        Pollers compare it for equality and only re-read rows when it moves.
        The count is load-bearing: purging a row that is not the newest leaves
        both maxima untouched, so a deletion would otherwise be invisible.
        """
        row = self.conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS mid, COALESCE(MAX(updated_at), '') AS mts, "
            "COUNT(*) AS n FROM questions"
        ).fetchone()
        return (int(row["mid"]), str(row["mts"]), int(row["n"]))

    def wait_for_answer(
        self,
        key: str,
        *,
        project: str | None = None,
        timeout: float | None = None,
        poll: float = 0.4,
    ) -> Question | None:
        """Block until `key` settles. Returns None on timeout.

        A blocking row settles when its status leaves `open`/`elaborate`. A
        non-blocking row (steer, notify, `--no-block`, and the persistent
        review/plan/data rows) never leaves `open`/`live` on its own, so it
        settles when its (status, answer count) differs from the snapshot
        taken as the wait starts: a new verdict, a tap, a clear.

        A cleared question returns too — the agent asked, the human declined to
        answer, and that is an outcome rather than a hang.
        """
        first = self.get(key, project=project)
        if first is None:
            raise KeyError(f"no such question: {key}")
        # The row's own flag decides, because the agent that wrote it decided.
        watch = not first.blocked
        snap = (first.status, len(first.answers))
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            q = self._get_by_id(first.id)
            if q is None:
                raise KeyError(f"no such question: {key}")
            if watch:
                if (q.status, len(q.answers)) != snap:
                    return q
            # `elaborate` is a detour, not an exit: the row is still waiting
            # on this same agent, just for a rewrite before it can be
            # answered, so a blocking ask keeps parking here through it.
            elif q.status not in ("open", "elaborate"):
                return q
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(poll)

    def rehome(
        self, *, project: str, new_agent: str, pane: str, session: str
    ) -> list[str]:
        """Reassign every row stamped with (pane, session) to `new_agent` (q208).

        After a `/clear` an agent's identity changes and its own rows fall
        off its `--agent` filters. `pane` and `session` are the herdr scope
        stamped on each row at ask time (da2aff8) — the trail that still ties
        a row back to the same conversation once the identity that asked it
        no longer exists. Scoped to `project`, and to `open`/`live`/`answered`
        rows: a cleared row is retired and rehoming it would resurrect it
        under an owner that never asked it.

        Bumps `updated_at` so pollers see the move, in one transaction so a
        poller never reads half the batch reassigned.
        """
        now = _now()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            rows = self.conn.execute(
                "SELECT id, key FROM questions WHERE project = ? AND pane = ? "
                "AND session = ? AND status IN ('open', 'live', 'answered') "
                "AND (agent IS NULL OR agent != ?)",
                (project, pane, session, new_agent),
            ).fetchall()
            ids = [int(r["id"]) for r in rows]
            keys = [r["key"] for r in rows]
            if ids:
                self.conn.executemany(
                    "UPDATE questions SET agent = ?, updated_at = ? WHERE id = ?",
                    [(new_agent, now, qid) for qid in ids],
                )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return keys


    # ---- internals --------------------------------------------------------

    def _scope_where(
        self,
        *,
        keys: Sequence[str] | None = None,
        project: str | None = None,
        thread: str | None = None,
        all_projects: bool = False,
    ) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        if keys:
            where.append("key IN (%s)" % ",".join("?" * len(keys)))
            params.extend(keys)
        if not all_projects and project:
            where.append("project = ?")
            params.append(project)
        if thread is not None:
            where.append("thread = ?")
            params.append(thread)
        if not where:
            where.append("1=1")
        return where, params

    def _hydrate(self, row: sqlite3.Row) -> Question:
        parent_key = None
        if row["parent_id"] is not None:
            prow = self.conn.execute(
                "SELECT key FROM questions WHERE id = ?", (row["parent_id"],)
            ).fetchone()
            parent_key = prow["key"] if prow else None

        # Oldest first; `answer` is the latest, which is what every existing
        # caller means by "the answer".
        arows = self.conn.execute(
            "SELECT * FROM answers WHERE question_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (row["id"],),
        ).fetchall()
        answers = [
            Answer(
                selected=json.loads(a["selected"] or "[]"),
                text=a["text"],
                skipped=bool(a["skipped"]),
                created_at=a["created_at"],
            )
            for a in arows
        ]
        answer = answers[-1] if answers else None

        review = None
        if row["act"] in ("review", "run"):
            rrow = self.conn.execute(
                "SELECT * FROM reviews WHERE question_id = ?", (row["id"],)
            ).fetchone()
            if rrow:
                review = Review(
                    look_at=rrow["look_at"],
                    run_cmd=rrow["run_cmd"],
                    pass_when=rrow["pass_when"],
                    fail_when=rrow["fail_when"],
                    then_do=rrow["then_do"],
                )

        steps: list[Step] = []
        if row["act"] == "plan":
            steps = [
                Step(idx=int(st["idx"]), text=st["text"], done=bool(st["done"]))
                for st in self.conn.execute(
                    "SELECT * FROM steps WHERE question_id = ? ORDER BY idx ASC",
                    (row["id"],),
                )
            ]

        return Question(
            id=int(row["id"]),
            key=row["key"],
            project=row["project"],
            cwd=row["cwd"],
            thread=row["thread"],
            parent_id=row["parent_id"],
            parent_key=parent_key,
            text=row["text"],
            kind=row["kind"],
            act=row["act"],
            agent=row["agent"],
            word=row["word"],
            workspace=row["workspace"],
            tab=row["tab"],
            pane=row["pane"],
            session=row["session"],
            title=row["title"],
            chosen=row["chosen"],
            blocked=bool(row["blocked"]),
            source=row["source"],
            choices=[Choice.parse(c) for c in json.loads(row["choices"] or "[]")],
            allow_free=bool(row["allow_free"]),
            recommend=json.loads(row["recommend"]) if row["recommend"] else [],
            confidence=row["confidence"],
            recommend_why=row["recommend_why"],
            context=row["context"],
            asked_by=row["asked_by"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            elaborate=row["elaborate"],
            elaborate_at=row["elaborate_at"],
            last_change=row["last_change"],
            answer=answer,
            answers=answers,
            review=review,
            steps=steps,
            run_exit=row["run_exit"],
            run_tail=json.loads(row["run_tail"]) if row["run_tail"] else [],
            run_log=row["run_log"],
            files=json.loads(row["files"]) if row["files"] else [],
            heard_at=row["heard_at"],
            responded_at=row["responded_at"],
            auto_pick=row["auto_pick"],
            auto_confidence=row["auto_confidence"],
            auto_reason=row["auto_reason"],
            auto_at=row["auto_at"],
        )
