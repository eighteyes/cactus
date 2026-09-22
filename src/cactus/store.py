"""
store.py — SQLite persistence for the cactus question/answer inbox.

Responsibilities:
- Own the database location, schema, and migrations.
- Create, read, answer, and clear questions and their threaded follow-ups.
- Expose a change cursor so the TUI and watch feed can poll cheaply.
- Keep every read and write safe for concurrent agent writers via WAL mode.
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
from typing import Any, Iterable, Sequence

KINDS = ("choice", "multi", "text", "confirm")
STATUSES = ("open", "live", "answered", "cleared")

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
    chosen       TEXT,
    blocked      INTEGER NOT NULL DEFAULT 1,
    choices      TEXT    NOT NULL DEFAULT '[]',
    allow_free   INTEGER NOT NULL DEFAULT 1,
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


_legacy_notice_shown = False


def default_db_path() -> Path:
    """Database location, overridable with CACTUS_DB for tests and alternate inboxes.

    When the cactus database is absent and a qaui-era one exists, that older file
    is used and a move instruction is printed once. The old file is never
    written to a new location automatically; relocating it stays the user's
    decision.
    """
    env = os.environ.get("CACTUS_DB")
    if env is not None and not env.strip():
        # An empty value is a scripting accident — a failed mktemp, an unset
        # variable in a test harness. Falling through would silently target the
        # live inbox, which is exactly what the variable exists to avoid.
        raise ValueError("CACTUS_DB is set but empty; unset it or give it a path")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    new_path = root / "cactus" / "cactus.db"
    if new_path.exists():
        return new_path
    legacy = root / "qaui" / "qaui.db"
    if legacy.exists():
        global _legacy_notice_shown
        if _legacy_notice_shown:
            return legacy
        _legacy_notice_shown = True
        print(
            f"cactus: using the qaui inbox at {legacy}\n"
            f"cactus: adopt it with  mkdir -p {new_path.parent} && "
            f"sqlite3 {legacy} \"VACUUM INTO '{new_path}'\"",
            file=sys.stderr,
        )
        return legacy
    return new_path


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
        return {"idx": self.idx, "text": self.text, "done": self.done}


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
    chosen: str | None
    blocked: bool
    choices: list[Choice]
    allow_free: bool
    context: str | None
    asked_by: str | None
    status: str
    created_at: str
    updated_at: str
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
            "chosen": self.chosen,
            "blocked": self.blocked,
            "choices": [c.as_dict() for c in self.choices],
            "allow_free": self.allow_free,
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
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES)

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

        self._drop_answer_uniqueness()

    def _drop_answer_uniqueness(self) -> None:
        """Rebuild `answers` without UNIQUE(question_id), once.

        A persistent row takes a verdict more than once, so answers became an
        append-only log. SQLite cannot drop a constraint in place, and the
        rebuild has to outlive a crash mid-way, so it runs inside one explicit
        transaction with foreign keys off — dropping the old table with them on
        would cascade the questions' answers away.
        """
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='answers'"
        ).fetchone()
        if not row or "UNIQUE" not in (row["sql"] or ""):
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
        chosen: str | None = None,
        blocked: bool | None = None,
        choices: Sequence[Choice] | None = None,
        allow_free: bool = True,
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
        choices = list(choices or [])
        if kind in ("choice", "multi") and not choices:
            raise ValueError(f"kind={kind!r} requires at least one choice")
        if kind == "confirm" and not choices:
            choices = [Choice("yes"), Choice("no")]
        if chosen is not None and choices:
            labels = [c.label for c in choices]
            if chosen not in labels:
                raise ValueError(f"chosen must be one of {labels}, got {chosen!r}")
        if act == "steer" and chosen is None:
            raise ValueError(
                "act='steer' needs a chosen option: a steer states what "
                "happens anyway, and one that states nothing is an ask"
            )
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
                 word, chosen, blocked, choices, allow_free, context, asked_by,
                 status, created_at, updated_at)
            VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project, cwd, thread, parent_id, text, kind, act, agent, word,
                chosen, 1 if blocked else 0,
                json.dumps([c.as_dict() for c in choices]),
                1 if allow_free else 0, context, asked_by, status, now, now,
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
        now = _now()
        self.conn.execute(
            """
            INSERT INTO answers (question_id, selected, text, skipped, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (q.id, json.dumps(list(selected or [])), text, 1 if skipped else 0, now),
        )
        status = "live" if q.persistent else "answered"
        self.conn.execute(
            "UPDATE questions SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, q.id),
        )
        result = self.get(key)
        assert result is not None
        return result

    def clear(
        self,
        *,
        keys: Sequence[str] | None = None,
        project: str | None = None,
        thread: str | None = None,
        all_projects: bool = False,
        include_answered: bool = True,
    ) -> int:
        """Mark questions cleared. Returns the number of rows affected.

        Clearing is a status change, not a delete — the transcript survives so a
        thread can still be read back after the agent has moved on.
        """
        where, params = self._scope_where(
            keys=keys, project=project, thread=thread, all_projects=all_projects
        )
        if not include_answered:
            where.append("status = 'open'")
        else:
            where.append("status != 'cleared'")
        sql = "UPDATE questions SET status = 'cleared', updated_at = ? WHERE " + " AND ".join(where)
        cur = self.conn.execute(sql, [_now(), *params])
        return cur.rowcount

    def reopen(self, key: str) -> Question:
        """Withdraw the latest answer.

        Undo for the human surfaces. It cannot recall an answer an agent has
        already read — `--wait` returns the moment the status leaves `open` — so
        the question simply becomes askable again.
        """
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        now = _now()
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
        self.conn.execute(
            "UPDATE questions SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, q.id),
        )
        result = self.get(key)
        assert result is not None
        return result

    def purge(
        self,
        *,
        keys: Sequence[str] | None = None,
        project: str | None = None,
        thread: str | None = None,
        all_projects: bool = False,
    ) -> int:
        """Delete rows outright. Follow-ups cascade with their parent."""
        where, params = self._scope_where(
            keys=keys, project=project, thread=thread, all_projects=all_projects
        )
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
        if q.act != "review":
            raise ValueError(f"{key} is act={q.act!r}, not 'review'")
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
                   SUM(CASE WHEN status = 'answered' THEN 1 ELSE 0 END) AS answered_count,
                   COUNT(*) AS total,
                   MAX(updated_at) AS last_activity
            FROM questions
            WHERE status != 'cleared'
            GROUP BY project
            ORDER BY open_count DESC, last_activity DESC
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
    ) -> list[Question]:
        """Questions in parent-before-child order, each carrying its `depth`.

        A follow-up is only reachable through its parent, so a child whose parent
        is out of scope is promoted to depth 0 rather than being dropped.
        """
        items = self.list(
            project=project, thread=thread, status=status,
            all_projects=all_projects, acts=acts, agent=agent,
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
        if row["act"] == "review":
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
            chosen=row["chosen"],
            blocked=bool(row["blocked"]),
            choices=[Choice.parse(c) for c in json.loads(row["choices"] or "[]")],
            allow_free=bool(row["allow_free"]),
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
