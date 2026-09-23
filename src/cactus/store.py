"""
store.py — SQLite persistence for the cactus question/answer inbox.

Responsibilities:
- Own the database location, schema, and migrations.
- Create, read, answer, and clear questions and their threaded follow-ups.
- Expose a change cursor so the TUI and watch feed can poll cheaply.
- Keep every read and write safe for concurrent agent writers via WAL mode.
- Write a decision record (record.py) after every state change, fail-soft.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

KINDS = ("choice", "multi", "text", "confirm")
STATUSES = ("open", "live", "answered", "cleared")

# How sure an agent's recommendation is. Advisory only — a recommend still
# waits for the human, unlike a steer's `chosen`, which proceeds.
CONFIDENCE = ("low", "med", "high")
CONFIDENCE_GLYPH = {"low": "○", "med": "◐", "high": "●"}

# What a human surface shows: a fork still waiting, and a persistent row that
# stays answerable. Both are work in front of the reader.
ACTIONABLE = ("open", "live")

# What the agent is asking for. Orthogonal to KINDS, which is how the answer is
# collected: a `run` act uses a `confirm` shape, a `steer` act may use either
# `choice` or `text`.
ACTS = ("ask", "steer", "run", "seen", "review", "plan")

# Acts whose rows stay answerable. They are created `live`, never transition on
# their own, and `wait_for_answer` refuses them.
PERSISTENT_ACTS = ("review", "plan")

# Whether a row blocks is the AGENT's call, stored per row in `blocked`, not a
# property of its act. The act only supplies the default the agent gets when it
# says nothing, and the agent overrides it freely. Over-claiming — parking a
# human on a question the agent could have answered — is the failure mode, and
# it is measurable as a blocked rate rather than legislated here.
DEFAULT_BLOCKED = {
    "ask": True,
    "run": True,
    "steer": False,
    "seen": False,
    "review": False,
    "plan": False,
}

# Shapes each act accepts. `seen` and `plan` collect no answer of their own.
ACT_SHAPES: dict[str, tuple[str, ...]] = {
    "ask":    ("choice", "multi", "text", "confirm"),
    "steer":  ("choice", "text"),
    "run":    ("confirm",),
    "seen":   ("text",),
    "review": ("confirm",),
    "plan":   ("text",),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT    NOT NULL UNIQUE,
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
    updated_at   TEXT    NOT NULL
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
    choices: list[Choice]
    allow_free: bool
    context: str | None
    asked_by: str | None
    status: str
    created_at: str
    updated_at: str
    recommend: list[str] = field(default_factory=list)
    confidence: str | None = None
    recommend_why: str | None = None
    answer: Answer | None = None
    answers: list[Answer] = field(default_factory=list)
    review: Review | None = None
    steps: list[Step] = field(default_factory=list)
    depth: int = 0

    @property
    def persistent(self) -> bool:
        return self.act in PERSISTENT_ACTS

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
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
            "answer": self.answer.as_dict() if self.answer else None,
            "answers": [a.as_dict() for a in self.answers],
            "review": self.review.as_dict() if self.review else None,
            "steps": [st.as_dict() for st in self.steps],
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
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

        # NOT called here. Rebuilding `answers` is destructive-shaped and
        # changes the schema under any process that already imported the old
        # module — which is exactly what happened to a long-running agent when
        # `cactus where` migrated the live inbox out from under it. Additive
        # column adds are safe to do on open; a table rebuild is not, so it
        # needs `cactus migrate` or CACTUS_MIGRATE=1.
        if os.environ.get("CACTUS_MIGRATE") == "1":
            self._drop_answer_uniqueness()

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
        choices: Sequence[Choice] | None = None,
        allow_free: bool = True,
        recommend: Sequence[str] | None = None,
        confidence: str | None = None,
        recommend_why: str | None = None,
        thread: str | None = None,
        parent_key: str | None = None,
        context: str | None = None,
        asked_by: str | None = None,
    ) -> Question:
        """Insert one question and return it, with its assigned key."""
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
            parent = self.get(parent_key)
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
        cur = self.conn.execute(
            """
            INSERT INTO questions
                (key, project, cwd, thread, parent_id, text, kind, act, agent,
                 word, workspace, tab, pane, session, title, chosen, blocked,
                 choices, allow_free, recommend, confidence, recommend_why,
                 context, asked_by, status, created_at, updated_at)
            VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project, cwd, thread, parent_id, text, kind, act, agent, word,
                workspace, tab, pane, session, title,
                chosen, 1 if blocked else 0,
                json.dumps([c.as_dict() for c in choices]),
                1 if allow_free else 0,
                json.dumps(recommend) if recommend else None,
                confidence, recommend_why,
                context, asked_by, status, now, now,
            ),
        )
        rowid = int(cur.lastrowid)
        key = f"q{rowid}"
        self.conn.execute("UPDATE questions SET key = ? WHERE id = ?", (key, rowid))
        result = self.get(key)
        assert result is not None
        return result

    def answer(
        self,
        key: str,
        *,
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
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if self.needs_rebuild():
            raise RuntimeError(
                "this database still has UNIQUE(question_id) on answers, which "
                "an append-only log cannot use — run `cactus migrate` once, "
                "and restart anything holding an older cactus module"
            )
        if not q.persistent and q.status == "answered":
            raise AlreadyAnswered(
                f"{key} was already answered "
                f"{'with ' + ', '.join(q.answer.selected) if q.answer and q.answer.selected else ''}"
                f" — undo it first if that verdict should change".replace("  ", " ")
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
        result = self.get(key)
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
    ) -> int:
        """Mark questions cleared. Returns the number of rows affected.

        Clearing is a status change, not a delete — the transcript survives so a
        thread can still be read back after the agent has moved on.

        `agent`, when given, restricts the update to rows owned by it — a
        NULL-owned row never matches `agent = ?`, so an unowned row is left
        alone without a separate check. The refusal policy for who may pass
        which `agent` lives in cli.py; this is mechanism only.
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
            r["key"] for r in self.conn.execute(
                "SELECT key FROM questions WHERE " + clause, params
            )
        ]
        sql = "UPDATE questions SET status = 'cleared', updated_at = ? WHERE " + clause
        cur = self.conn.execute(sql, [_now(), *params])
        for key in affected:
            row = self.get(key)
            if row is not None:
                self._record(row, event="clear")
        return cur.rowcount

    def reopen(self, key: str) -> Question:
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
        q = self.get(key)
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
        result = self.get(key)
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
        look_at: str | None = None,
        run_cmd: str | None = None,
        pass_when: str | None = None,
        fail_when: str | None = None,
        then_do: str | None = None,
    ) -> Question:
        """Attach or replace the verify block on a `review` row."""
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        # `run` rows carry a command too, and it belongs in the same place as a
        # review's: both are rows where something is going to be executed and
        # the human decides whether it should be.
        if q.act not in ("review", "run"):
            raise ValueError(f"{key} is act={q.act!r}, not 'review' or 'run'")
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
            (q.id, look_at, run_cmd, pass_when, fail_when, then_do),
        )
        return self._touch(q.id, key)

    def set_steps(self, key: str, steps: Sequence[str]) -> Question:
        """Replace the step list on a `plan` row, preserving done state by index."""
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        if q.act != "plan":
            raise ValueError(f"{key} is act={q.act!r}, not 'plan'")
        done = {st.idx for st in q.steps if st.done}
        self.conn.execute("DELETE FROM steps WHERE question_id = ?", (q.id,))
        self.conn.executemany(
            "INSERT INTO steps (question_id, idx, text, done) VALUES (?, ?, ?, ?)",
            [(q.id, i, t, 1 if i in done else 0) for i, t in enumerate(steps)],
        )
        return self._touch(q.id, key)

    def set_step_done(self, key: str, idx: int, done: bool = True) -> Question:
        """Tick or untick one step.

        Both the human surfaces and the agent write this, which is why steps are
        rows rather than a JSON blob on the question: a blob would make every
        toggle a read-modify-write race between the two writers.
        """
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        cur = self.conn.execute(
            "UPDATE steps SET done = ? WHERE question_id = ? AND idx = ?",
            (1 if done else 0, q.id, idx),
        )
        if cur.rowcount == 0:
            raise KeyError(f"{key} has no step {idx}")
        return self._touch(q.id, key)

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

    def _touch(self, qid: int, key: str) -> Question:
        """Bump `updated_at` so a sidecar-only write still moves the cursor."""
        self.conn.execute(
            "UPDATE questions SET updated_at = ? WHERE id = ?", (_now(), qid)
        )
        result = self.get(key)
        assert result is not None
        return result

    # ---- reads ------------------------------------------------------------

    def get(self, key: str) -> Question | None:
        row = self.conn.execute(
            "SELECT * FROM questions WHERE key = ?", (key,)
        ).fetchone()
        return self._hydrate(row) if row else None

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
        """Projects with live questions, counted by status, busiest first.

        Cleared questions are excluded outright — a project whose whole inbox has
        been retired should not keep a row in the rail.
        """
        rows = self.conn.execute(
            """
            SELECT project,
                   SUM(CASE WHEN status = 'open'     THEN 1 ELSE 0 END) AS open_count,
                   SUM(CASE WHEN status = 'live'     THEN 1 ELSE 0 END) AS live_count,
                   SUM(CASE WHEN status = 'answered' THEN 1 ELSE 0 END) AS answered_count,
                   COUNT(*) AS total,
                   MAX(updated_at) AS last_activity
            FROM questions
            WHERE status != 'cleared'
            GROUP BY project
            ORDER BY open_count DESC, live_count DESC, last_activity DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def threads(self, *, project: str | None = None, all_projects: bool = False) -> list[dict[str, Any]]:
        where, params = self._scope_where(project=project, all_projects=all_projects)
        where.append("status != 'cleared'")
        rows = self.conn.execute(
            "SELECT thread, project, COUNT(*) AS total, "
            "SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_count, "
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
        self, key: str, *, timeout: float | None = None, poll: float = 0.4
    ) -> Question | None:
        """Block until `key` leaves `open`. Returns None on timeout.

        A cleared question returns too — the agent asked, the human declined to
        answer, and that is an outcome rather than a hang.
        """
        first = self.get(key)
        if first is None:
            raise KeyError(f"no such question: {key}")
        # The row's own flag decides, because the agent that wrote it decided.
        if not first.blocked:
            raise ValueError(
                f"{key} was posted with blocked=false — watch the monitor "
                f"stream for its disposition instead of waiting on it"
            )
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            q = self.get(key)
            if q is None:
                raise KeyError(f"no such question: {key}")
            if q.status != "open":
                return q
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(poll)

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
            answer=answer,
            answers=answers,
            review=review,
            steps=steps,
        )
