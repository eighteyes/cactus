"""
store.py — SQLite persistence for the qaui question/answer inbox.

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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

KINDS = ("choice", "multi", "text", "confirm")
STATUSES = ("open", "answered", "cleared")

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
    choices      TEXT    NOT NULL DEFAULT '[]',
    allow_free   INTEGER NOT NULL DEFAULT 1,
    context      TEXT,
    asked_by     TEXT,
    status       TEXT    NOT NULL DEFAULT 'open',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
    selected     TEXT    NOT NULL DEFAULT '[]',
    text         TEXT,
    skipped      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_q_project_status ON questions(project, status);
CREATE INDEX IF NOT EXISTS idx_q_parent         ON questions(parent_id);
CREATE INDEX IF NOT EXISTS idx_q_updated        ON questions(updated_at);
"""


def default_db_path() -> Path:
    """Database location, overridable with QAUI_DB for tests and alternate inboxes."""
    env = os.environ.get("QAUI_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / "qaui" / "qaui.db"


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
    choices: list[Choice]
    allow_free: bool
    context: str | None
    asked_by: str | None
    status: str
    created_at: str
    updated_at: str
    answer: Answer | None = None
    depth: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "project": self.project,
            "cwd": self.cwd,
            "thread": self.thread,
            "parent": self.parent_key,
            "text": self.text,
            "kind": self.kind,
            "choices": [c.as_dict() for c in self.choices],
            "allow_free": self.allow_free,
            "context": self.context,
            "asked_by": self.asked_by,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "answer": self.answer.as_dict() if self.answer else None,
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
        choices = list(choices or [])
        if kind in ("choice", "multi") and not choices:
            raise ValueError(f"kind={kind!r} requires at least one choice")
        if kind == "confirm" and not choices:
            choices = [Choice("yes"), Choice("no")]

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
        cur = self.conn.execute(
            """
            INSERT INTO questions
                (key, project, cwd, thread, parent_id, text, kind, choices,
                 allow_free, context, asked_by, status, created_at, updated_at)
            VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                project, cwd, thread, parent_id, text, kind,
                json.dumps([c.as_dict() for c in choices]),
                1 if allow_free else 0, context, asked_by, now, now,
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
        """Record an answer and flip the question to `answered`."""
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        now = _now()
        self.conn.execute(
            """
            INSERT INTO answers (question_id, selected, text, skipped, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                selected = excluded.selected,
                text     = excluded.text,
                skipped  = excluded.skipped,
                created_at = excluded.created_at
            """,
            (q.id, json.dumps(list(selected or [])), text, 1 if skipped else 0, now),
        )
        self.conn.execute(
            "UPDATE questions SET status = 'answered', updated_at = ? WHERE id = ?",
            (now, q.id),
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
        """Return a question to `open` and discard its answer.

        Undo for the human surfaces. It cannot recall an answer an agent has
        already read — `--wait` returns the moment the status leaves `open` — so
        the question simply becomes askable again.
        """
        q = self.get(key)
        if q is None:
            raise KeyError(f"no such question: {key}")
        now = _now()
        self.conn.execute("DELETE FROM answers WHERE question_id = ?", (q.id,))
        self.conn.execute(
            "UPDATE questions SET status = 'open', updated_at = ? WHERE id = ?",
            (now, q.id),
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
        limit: int | None = None,
    ) -> list[Question]:
        where, params = self._scope_where(
            keys=keys, project=project, thread=thread, all_projects=all_projects
        )
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            where.append("status IN (%s)" % ",".join("?" * len(statuses)))
            params.extend(statuses)
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
    ) -> list[Question]:
        """Questions in parent-before-child order, each carrying its `depth`.

        A follow-up is only reachable through its parent, so a child whose parent
        is out of scope is promoted to depth 0 rather than being dropped.
        """
        items = self.list(
            project=project, thread=thread, status=status, all_projects=all_projects
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

        arow = self.conn.execute(
            "SELECT * FROM answers WHERE question_id = ?", (row["id"],)
        ).fetchone()
        answer = None
        if arow:
            answer = Answer(
                selected=json.loads(arow["selected"] or "[]"),
                text=arow["text"],
                skipped=bool(arow["skipped"]),
                created_at=arow["created_at"],
            )

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
            choices=[Choice.parse(c) for c in json.loads(row["choices"] or "[]")],
            allow_free=bool(row["allow_free"]),
            context=row["context"],
            asked_by=row["asked_by"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            answer=answer,
        )
