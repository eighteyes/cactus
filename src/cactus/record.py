"""
record.py — decision records: one markdown file per question, on disk.

Responsibilities:
- Render a Question's current state (and the event that produced it) to
  markdown, fully and idempotently — the same row state always renders to the
  same bytes. An `edit`'s `prior` fields render as a `## Rewrite` section, so
  the record shows the question before and after.
- Resolve where that markdown lives: <project>/.ai/cactus/q{N}-{slug}.md,
  reusing whatever filename a row already has even if its word changes.
- Write it atomically (temp file + os.replace), creating .ai/cactus/ as
  needed.

This module is pure rendering and file I/O — it never touches the database.
Callers (store.py) decide when a record is due and swallow errors it raises;
nothing here is fail-soft on its own.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .store import CONFIDENCE_GLYPH

if TYPE_CHECKING:
    from .store import Answer, Question

RECORDS_DIRNAME = Path(".ai") / "cactus"


def _slugify(text: str, max_len: int) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "q"


def slug_for(row: "Question") -> str:
    """The slug half of a record's filename: row.word, else the first 5 words."""
    base = row.word if row.word else " ".join(row.text.split()[:5])
    return _slugify(base, 40)


def records_dir(project: str) -> Path:
    return Path(project) / RECORDS_DIRNAME


def record_path(row: "Question") -> Path:
    """Where a row's record lives, reusing an existing file's name if one exists.

    A record is named from the row's word or text at the time it was first
    written. A later `--word` on the same row must not orphan the old file, so
    an existing q{N}-*.md is reused verbatim rather than re-slugged.
    """
    d = records_dir(row.project)
    existing = sorted(d.glob(f"{row.key}-*.md"))
    if existing:
        return existing[0]
    return d / f"{row.key}-{slug_for(row)}.md"


def _status_label(row: "Question", event: str) -> str:
    """The record's status field — a superset of the DB's `status` column.

    `clear` and `reopen` fan a single DB status ('cleared' / 'live' / 'answered'
    / 'open') out into the reader-facing distinction the spec calls for:
    declined vs. retired, withdrawn vs. live.
    """
    if event == "clear":
        return "retired" if row.answers else "declined"
    if event == "reopen":
        return "live" if row.persistent else "withdrawn"
    if event == "elaborate":
        return "elaborate"
    if event in ("edit", "unelaborate"):
        # Both leave the row exactly at its current, already-correct status
        # (open/live) — no fan-out needed, unlike clear/reopen above.
        return row.status
    if event == "restore":
        # A restore un-clears a row rather than undoing an answer, so its
        # verdict log (or lack of one) is intact, not withdrawn.
        if row.persistent:
            return "live"
        if row.answer is not None and row.answer.skipped:
            return "skipped"
        return "answered" if row.answer is not None else "open"
    # event == "answer"
    if row.answer is not None and row.answer.skipped:
        return "skipped"
    return "live" if row.persistent else "answered"


def _rel_cwd(row: "Question") -> str:
    try:
        return os.path.relpath(row.cwd, row.project)
    except ValueError:
        return row.cwd


def _field_block(row: "Question", status: str) -> list[str]:
    fields: list[tuple[str, str]] = [("status", status), ("act", row.act), ("kind", row.kind)]
    if row.thread:
        fields.append(("thread", row.thread))
    if row.parent_key:
        fields.append(("parent", row.parent_key))
    if row.agent:
        fields.append(("agent", row.agent))
    if row.asked_by:
        fields.append(("asked by", row.asked_by))
    rel_cwd = _rel_cwd(row)
    if rel_cwd:
        fields.append(("cwd", rel_cwd))
    fields.append(("asked at", row.created_at))
    return [f"{label}: {value}" for label, value in fields]


def _option_lines(row: "Question") -> list[str]:
    lines = []
    for c in row.choices:
        line = f"- {c.label}"
        if c.description:
            line += f" — {c.description}"
        markers = []
        if c.label in row.recommend:
            markers.append("★" + CONFIDENCE_GLYPH.get(row.confidence or "", ""))
        if row.chosen == c.label:
            markers.append("doing")
        if markers:
            line += "  (" + ", ".join(markers) + ")"
        lines.append(line)
    return lines


def _answer_content(a: "Answer") -> str:
    if a.skipped:
        return "skipped"
    parts = []
    if a.selected:
        parts.append(", ".join(a.selected))
    if a.text:
        parts.append(a.text)
    return " — ".join(parts) if parts else "(no content)"


def _review_block(row: "Question") -> list[str]:
    r = row.review
    if r is None:
        return []
    lines = []
    if r.look_at:
        lines.append(f"look at: {r.look_at}")
    if r.run_cmd:
        lines.append(f"run: {r.run_cmd}")
    if r.pass_when:
        lines.append(f"pass: {r.pass_when}")
    if r.fail_when:
        lines.append(f"fail: {r.fail_when}")
    if r.then_do:
        lines.append(f"then: {r.then_do}")
    return lines


def _steps_lines(row: "Question") -> list[str]:
    return [
        f"{st.idx + 1}. [{'x' if st.done else ' '}] {st.text}"
        for st in row.steps
    ]


def render(
    row: "Question",
    *,
    event: str,
    withdrawn_answer: "Answer | None" = None,
    prior: "dict[str, Any] | None" = None,
) -> str:
    """Render a row's full markdown record for the given event.

    Idempotent: the same row state and event always render byte-identical
    output — no timestamp of the write itself appears anywhere in it.

    `prior` (an `edit`'s `text`/`context`/`choices` before the rewrite) adds
    a `## Rewrite` section so the record shows the question before and
    after, alongside the current state every other section already shows.
    """
    status = _status_label(row, event)
    title = " ".join(row.text.split())
    parts: list[str] = [f"# {row.key} — {title}", ""]
    parts.extend(_field_block(row, status))

    if event == "elaborate":
        parts += ["", "## Elaborate requested", ""]
        parts.append(row.elaborate or "(no hint given)")
        parts.append(f"requested at: {row.elaborate_at}")

    if event == "unelaborate":
        # A one-line note, not a fresh section of prose — `unelaborate` only
        # ever rewrites a record the `elaborate` request above already wrote.
        parts += ["", "## Elaborate withdrawn", ""]
        parts.append(f"withdrawn at: {row.updated_at}")

    if row.context:
        parts += ["", "## Context", "", row.context]

    option_lines = _option_lines(row)
    if option_lines:
        parts += ["", "## Options", ""]
        parts += option_lines

    if row.recommend:
        parts += ["", "## Recommendation", ""]
        head = ", ".join(row.recommend)
        if row.confidence:
            head += f" — {row.confidence}"
        parts.append(head)
        if row.recommend_why:
            parts.append(row.recommend_why)

    if row.persistent:
        verdict_lines: list[str] = []
        review_lines = _review_block(row)
        if review_lines:
            verdict_lines += review_lines
        steps_lines = _steps_lines(row)
        if steps_lines:
            if verdict_lines:
                verdict_lines.append("")
            verdict_lines += steps_lines
        if row.answers:
            if verdict_lines:
                verdict_lines.append("")
            verdict_lines += [
                f"- {a.created_at}: {_answer_content(a)}" for a in row.answers
            ]
        if verdict_lines:
            parts += ["", "## Verdicts", ""]
            parts += verdict_lines
    else:
        if status == "withdrawn" and withdrawn_answer is not None:
            parts += ["", "## Withdrawn", ""]
            parts.append(_answer_content(withdrawn_answer))
            parts.append(f"answered at: {withdrawn_answer.created_at}")
        elif row.answer is not None:
            parts += ["", "## Answer", ""]
            parts.append(_answer_content(row.answer))
            parts.append(f"answered at: {row.answer.created_at}")

    if row.act == "run" and row.run_exit is not None:
        parts += ["", "## Result", ""]
        parts.append(f"exit: {row.run_exit}")
        if row.run_tail:
            parts += ["", "```", *row.run_tail, "```"]
        if row.run_log:
            parts += ["", f"log: {row.run_log}"]

    if event == "edit" and prior is not None:
        parts += ["", "## Rewrite", ""]
        parts.append(f"was: {prior.get('text', '')}")
        if prior.get("context"):
            parts += ["", prior["context"]]
        prior_choices = prior.get("choices") or []
        if prior_choices:
            parts += ["", "options were:"]
            for c in prior_choices:
                line = f"- {c.label}"
                if c.description:
                    line += f" — {c.description}"
                parts.append(line)

    return "\n".join(parts) + "\n"


def write_record(
    row: "Question",
    *,
    event: str,
    withdrawn_answer: "Answer | None" = None,
    prior: "dict[str, Any] | None" = None,
) -> Path:
    """Write (or rewrite) a row's record. Raises on any I/O failure.

    Atomic: a temp file in the same directory, then os.replace, so a poller
    (or a human's editor) never observes a half-written file.
    """
    path = record_path(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render(row, event=event, withdrawn_answer=withdrawn_answer, prior=prior)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content)
    os.replace(tmp, path)
    return path
