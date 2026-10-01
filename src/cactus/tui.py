"""
tui.py — interactive Textual application for answering questions in the cactus inbox.

Responsibilities:
- Render the active question as a full-width detail card, with the rest of the
  inbox as fixed-height blocks in a left rail under a project header.
- Let a human answer choice, multi, confirm, and text questions from the keyboard,
  including free text attached to the active question.
- Poll the store's change cursor and refresh the view without losing focus or
  in-progress input.
- Provide project switching, skip, and clear actions, plus key-hint and count footers.
- Show a dedicated Projects page where Cactus can be ignored or reactivated per
  project, and a smaller due-ranked projects pane beside the rail as a preview.
- Show an answers view (`a`) of this project's history — answered and cleared
  rows with a verdict — newest verdict first.
- Let a human ask an agent to rewrite a row (`e`) and withdraw that request
  (`u`) before the agent addresses it.
- Grow a small sky/weather/cactus simulation under the card, dropping a seed
  on every answer, or manually via backtick/tilde at any time outside
  free-text mode. Card first: the field gets only the rows the card's
  content leaves, hidden below `FIELD_MIN_ROWS`; the key bar (left, centre
  or right per `keybar_align`) drops each seed under the key pressed, or
  at its mirrored column under the `seed_release = "right"` setting.
- Show a `T` tuning overlay listing every `SkyConfig` key, nudge it live
  with h/l/H/L, reset it with r, and keep the on-disk file and the running
  sky in agreement on every nudge.
- Perf (v6f): the field timer samples at `1 / SkyConfig.fps` rather than a
  fixed interval, restarted by `_sync_field_interval` whenever `fps` changes
  (a config reload or a tuning nudge) — `World.advance(dt)` still gets the
  real elapsed time either way. `_render_field` skips `FieldView.update`
  outright when the frame's text and spans are unchanged from the last one
  drawn.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from . import garden, tradeoffs
from .field import World
from .scope import project_label
from .sky import (SkyConfig, TuneField, config_path as sky_config_path, slots as sky_slots, tuning_fields_for,
                  tuning_panel_of, tuning_panel_order)
from .store import (ACTIONABLE, CONFIDENCE_GLYPH, AlreadyAnswered, Answer,
                    Question, Store)

POLL_INTERVAL = 0.5
# The field's per-frame `dt` cap (v6b): a stalled or suspended terminal must
# never hand `World.advance` a giant elapsed time and make the sky or a
# falling seed jump.
FIELD_MAX_DT = 0.5
# Card first: the field gets only the rows the card leaves, and hides rather
# than squashes when fewer than this are left (sky plus the 2 ground rows).
FIELD_MIN_ROWS = 4

TUI_SETTINGS_DEFAULTS = {
    "orientation": "side", "figlet_header": False, "projects_pane": True,
    "field": True, "pile_only": False, "seed_release": "left",
    "keybar_align": "center",
}
KEYBAR_ALIGNS = ("left", "center", "right")


def _tui_settings_path() -> Path:
    root = Path(os.environ["XDG_CONFIG_HOME"]) if os.environ.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return root / "cactus" / "tui.json"


def _load_tui_settings() -> dict[str, Any]:
    """Best-effort user preferences; a bad config never prevents the TUI opening."""
    settings = dict(TUI_SETTINGS_DEFAULTS)
    try:
        data = json.loads(_tui_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if isinstance(data, dict) and data.get("orientation") in ("side", "bottom"):
        settings["orientation"] = data["orientation"]
    if isinstance(data, dict) and isinstance(data.get("figlet_header"), bool):
        settings["figlet_header"] = data["figlet_header"]
    if isinstance(data, dict) and isinstance(data.get("projects_pane"), bool):
        settings["projects_pane"] = data["projects_pane"]
    if isinstance(data, dict) and isinstance(data.get("field"), bool):
        settings["field"] = data["field"]
    if isinstance(data, dict) and isinstance(data.get("pile_only"), bool):
        settings["pile_only"] = data["pile_only"]
    if isinstance(data, dict) and data.get("seed_release") in ("left", "right"):
        settings["seed_release"] = data["seed_release"]
    if isinstance(data, dict) and data.get("keybar_align") in KEYBAR_ALIGNS:
        settings["keybar_align"] = data["keybar_align"]
    return settings


def _save_tui_settings(settings: dict[str, Any]) -> str | None:
    try:
        path = _tui_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        return str(exc)
    return None


def _figlet_project_name(label: str) -> str:
    """Render the requested local Figlet font, with a readable no-tool fallback."""
    try:
        result = subprocess.run(
            ["figlet", "-f", "cybermedium", label],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return f"  {label}"
    return result.stdout.rstrip() if result.returncode == 0 and result.stdout.strip() else f"  {label}"

# How many lines of command output the card shows; the rest spills to a file.
RUN_TAIL = 12

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

# `confirm` is built at render time from the row's own choice labels — see
# `_confirm_pairs` — because a review answers pass/fail and a run approve/deny,
# and a fixed yes/no hint would lie about what the keys send.
HINTS = {
    "choice": (("{digits}", "pick"), ("i", "type"), ("s", "skip (answers)"), ("c", "clear")),
    "multi": (("{digits}", "toggle"), ("enter", "submit"), ("i", "type"),
              ("s", "skip (answers)"), ("c", "clear")),
    "text": (("enter", "type"), ("esc", "back to list"),
             ("s", "skip (answers)"), ("c", "clear")),
}

# Acts whose hint is not their kind's: a plan is text-shaped but closes with
# `c`; a notice is dismissed; a data row is worked by digit.
ACT_HINTS = {
    "plan": (("enter", "type"), ("esc", "back to list"),
             ("s", "skip (answers)"), ("c", "close")),
    "notify": (("d", "dismiss"), ("enter", "type"),
               ("s", "skip (answers)"), ("c", "clear")),
    "data": (("{digits}", "copy chunk"), ("i", "note"),
             ("s", "skip (answers)"), ("d", "close")),
}


def _parse_exit_code(lines: list[str]) -> int:
    """The exit code shell.run recorded as its last "— exit N —" line.

    -1 if the command never got that far — killed, or a start-up failure that
    raised before a shell was ever spawned — matching the "killed" line's own
    exit code, so both read as the same kind of non-completion.
    """
    for line in reversed(lines):
        if line.startswith("— exit") and line.endswith("—"):
            try:
                return int(line.strip("— ").split()[-1])
            except ValueError:
                return -1
    return -1


def _flatten(text: str) -> str:
    """One-line form for a queue row; the row's own CSS ellipsizes the overflow."""
    return " ".join(text.split())


PROJECT_POKE_MESSAGE = (
    "cactus: update your rows — re-read your answers, act on them, "
    "clear what is done, edit stale questions."
)


def _pokeable(q: Question) -> bool:
    """A row can be poked when a nudge has somewhere to land.

    Poke is question-level: an override transport, a webhook mapped to
    `q.agent`, or the row's herdr pane stamp for the default prompt. An owner
    with none of those is unreachable, and the footer must not offer `p`.
    """
    from .poke import reachable

    return reachable(q.agent, q.pane)


# Two spaces, not three: the brackets already separate a key from its verb,
# so the old three-space gap only made the row wrap sooner.
KEY_GAP = "  "


def _keys(*pairs: tuple[str, str]) -> str:
    """A hint row. Each key is bracketed so it reads apart from its verb."""
    return KEY_GAP.join(f"[{key}] {verb}" for key, verb in pairs)


def _digit_range(n: int) -> str:
    """The digit keys a row answers to — `1`, or `1-n`. Only nine keys exist."""
    n = min(n, 9)
    return "1" if n <= 1 else f"1-{n}"


def _relative_age(ts: str) -> str:
    """Compact age — `45s`/`12m`/`3h`/`2d` — for a timeline reading, not a clock."""
    try:
        then = datetime.fromisoformat(ts)
    except ValueError:
        return "?"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    delta = max(0.0, (datetime.now(timezone.utc) - then).total_seconds())
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def _confirm_pairs(q: Question) -> tuple[tuple[str, str], ...]:
    """Confirm-row keys built from the row's own labels, not a fixed yes/no."""
    labels = [c.label for c in q.choices] or ["yes", "no"]
    keys = ["y/1", "n/2"]
    return (*zip(keys, labels), ("i", "type"), ("s", "skip (answers)"), ("c", "clear"))


def _verdict_repr(a: Answer) -> str:
    """One answer from the log, as a short label for the verdicts line."""
    text = ""
    if a.text:
        text = a.text.strip()
        text = text if len(text) <= 24 else text[:23] + "…"
    if a.selected and text:
        # A labeled verdict can still carry a note (`cactus answer -s fail
        # "button missing"`) — dropping it here is the only place a human
        # would ever see it again once a later verdict lands.
        return f"{', '.join(a.selected)} — {text}"
    if a.selected:
        return ", ".join(a.selected)
    if text:
        return text
    if a.skipped:
        return "skipped"
    return "—"


def _heard_line(q: Question) -> str:
    """The sent / heard status line for a review or plan row (q405)."""
    state = q.heard_state
    if state == "sent":
        return "sent · waiting for the agent"
    if state == "heard":
        return "heard ✓ · agent is on it"
    return ""


def _finished_prompt(q: Question) -> bool:
    """A plan with every step done, or a review with a verdict, may be closed (q404)."""
    if q.status != "live":
        return False
    if q.act == "plan":
        return bool(q.steps) and all(st.done for st in q.steps)
    return q.act == "review" and q.answer is not None


def _card_lines(
    q: Question,
    *,
    selected: set[str],
    pending: str,
    show_project: bool,
    run_output: list[str] | None = None,
    run_state: str = "",
    preview: list[str] | None = None,
) -> Text:
    """Full detail for the one question being answered."""
    # LABEL:qN when spanning projects (q166) — the bare key alone can recur
    # across projects once keys number per project.
    meta = [f"{project_label(q.project)}:{q.key}" if show_project else q.key]
    if q.thread:
        # Agent-scoped (q164/q165): a thread name is only unique within one
        # agent, so the reader has to see the owner alongside it, not the
        # bare name a second agent could be reusing.
        meta.append(f"thread {q.agent or '?'}/{q.thread}")
    if q.asked_by:
        meta.append(f"from {q.asked_by}")
    lines: list[str | Text] = ["  ".join(meta)]
    if q.parent_key:
        lines.append(f"follow-up to {q.parent_key}")
    lines.append("")
    lines.append(q.text)
    if q.context:
        lines.append("")
        lines.append(q.context)

    if q.files:
        lines.append("")
        for i, path in enumerate(q.files, start=1):
            label = "files" if i == 1 else ""
            lines.append(f"  {label:<8}{i} {path}")
    if preview:
        lines.append("")
        lines.extend(f"  {row}" for row in preview)

    if q.status == "elaborate":
        lines.append("")
        if q.elaborate == DECOMPOSE_INSTRUCTION.format(key=q.key):
            lines.append("wants this question split into smaller questions")
        else:
            lines.append(f"wants more: {q.elaborate}" if q.elaborate else "wants more (no hint given)")

    if q.answers:
        # A persistent row (review/plan) takes repeated verdicts, so the card
        # has to show the current one — without this, "y" then "n" look
        # identical on screen.
        reprs = [_verdict_repr(a) for a in q.answers]
        lines.append("")
        lines.append(f"verdicts: {', '.join(reprs)}  (latest: {reprs[-1]})")

    heard = _heard_line(q)
    if heard:
        lines.append("")
        lines.append(heard)
    if _finished_prompt(q):
        lines.append("")
        lines.append("finished? x closes it (or the agent will)")

    if q.chosen:
        lines.append("")
        lines.append(f"doing anyway: {q.chosen}   — pick below to redirect")

    if q.review is not None:
        block = [
            ("look at", q.review.look_at),
            ("run", q.review.run_cmd),
            ("pass", q.review.pass_when),
            ("fail", q.review.fail_when),
            ("then", q.review.then_do),
        ]
        rows = [(label, value) for label, value in block if value]
        if rows:
            lines.append("")
            for label, value in rows:
                lines.append(f"  {label:<8}{value}")

    if q.act == "plan" and q.steps:
        lines.append("")
        for st in q.steps:
            mark = "x" if st.done else " "
            lines.append(f"  {st.idx + 1})  [{mark}] {st.text}")

    if run_output:
        lines.append("")
        lines.append(f"  output ({run_state})")
        for row in run_output[-RUN_TAIL:]:
            lines.append(f"  | {row}")

    if q.act == "data":
        lines.append("")
        for i, choice in enumerate(q.choices, start=1):
            lines.append(f"  {i})  {choice.label}")
            for body_line in (choice.description or "").splitlines():
                lines.append(f"      | {body_line}")
    elif q.kind in ("choice", "multi"):
        lines.append("")
        for i, choice in enumerate(q.choices, start=1):
            mark = "[x] " if q.kind == "multi" and choice.label in selected else (
                "[ ] " if q.kind == "multi" else ""
            )
            rec = f" ★{CONFIDENCE_GLYPH.get(q.confidence, '')}" if choice.label in q.recommend else ""
            summary, marks = tradeoffs.split(choice.description)
            desc = f"  — {summary}" if summary else ""
            lines.append(f"  {i})  {mark}{choice.label}{rec}{desc}")
            for is_pro, text in marks:
                lines.append(
                    Text(f"      {'✓' if is_pro else '✗'} {text}", style="green" if is_pro else "red")
                )
        if q.recommend_why:
            lines.append(f"  recommend: {', '.join(q.recommend)} — {q.recommend_why}")
    elif q.kind == "confirm":
        labels = [c.label for c in q.choices] or ["yes", "no"]
        keys = ["y", "n"]
        lines.append("")
        for i, label in enumerate(labels, start=1):
            accel = f"   ({keys[i - 1]})" if i <= len(keys) else ""
            rec = f" ★{CONFIDENCE_GLYPH.get(q.confidence, '')}" if label in q.recommend else ""
            lines.append(f"  {i})  {label}{rec}{accel}")
        if q.recommend_why:
            lines.append(f"  recommend: {', '.join(q.recommend)} — {q.recommend_why}")

    if pending:
        lines.append("")
        # "draft", not "answer": this text has not been sent yet, whether it
        # was just typed or restored by `u` — either way it still needs
        # enter (or a pick) to record it.
        label = "draft" if q.kind == "text" else "free text"
        lines.append(f"{label}: {pending}")
        if q.kind != "text":
            lines.append("enter submits this text alone, or pick above to send both")

    lines.append("")
    if q.status == "elaborate":
        # Stopped accepting answers — the pick/type/skip hints above would
        # promise a key that check_action already refuses.
        hint = "awaiting rewrite by the agent — no answers accepted"
        extras = [("c", "clear"), ("u", "withdraw request")]
        if _pokeable(q):
            extras.append(("p", "poke"))
        if q.pane:
            extras.append(("v", "visit"))
    else:
        if q.kind == "confirm":
            pairs = _confirm_pairs(q)
        else:
            pairs = ACT_HINTS.get(q.act) or HINTS.get(q.kind, ())
        if not q.allow_free:
            # --no-free: check_action hides `i`, so the hint must not offer it.
            pairs = tuple(pair for pair in pairs if pair[0] != "i")
        hint = _keys(*pairs).format(digits=_digit_range(len(q.choices)))
        extras = []
        if q.review is not None and q.review.run_cmd:
            extras += [("C", "copy"), ("R", "run")]
        if _pokeable(q):
            extras.append(("p", "poke"))
        if q.pane:
            extras.append(("v", "visit"))
        if q.act == "plan" and q.steps:
            # Past 9 steps the digits buffer briefly, so "1" then "2" reaches
            # step 12; the hint names the whole reachable range.
            n = len(q.steps)
            extras.append((_digit_range(n) if n <= 9 else f"1-{n}", "toggle step"))
        if run_output:
            extras.append(("O", "open full output"))
        if q.status in ("open", "live"):
            extras.append(("e", "elaborate"))
            extras.append(("D", "decompose"))
    if q.act in ("review", "plan") and q.status == "live":
        lines.append("enter = note · x = close")
    lines.append(KEY_GAP.join(filter(None, [hint, _keys(*extras)])))
    # Text, not markup: agent text is never parsed; only mark lines carry a style.
    out = Text()
    for n, line in enumerate(lines):
        if n:
            out.append("\n")
        out.append(line) if isinstance(line, str) else out.append_text(line)
    return out


class FieldView(Static):
    """The pachinko field strip inside the answering card; content is set by
    CactusApp._render_field, which also keeps the world sized to this
    widget."""

    def on_resize(self, event: events.Resize) -> None:
        app = self.app
        if isinstance(app, CactusApp):
            app._render_field()


class KeyBar(Static):
    """The in-card row key bar; content is set by CactusApp._rebuild_keybar,
    which aligns it in this widget's width — so a resize re-aligns it."""

    def on_resize(self, event: events.Resize) -> None:
        app = self.app
        if isinstance(app, CactusApp):
            app._rebuild_keybar()


class RailList(ListView):
    """The question rail. A click moves the highlight; only a key submits.

    ListView posts Selected on a click, and Selected is where submit fires
    (enter never reaches an App binding). With a recommendation preselected,
    a click meant to focus a row answered it.
    """

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        # Textual dispatches a handler on every class in the MRO; without
        # prevent_default, ListView's own handler still posts Selected.
        event.prevent_default()
        event.stop()
        self.focus()
        self.index = self._nodes.index(event.item)


class QuestionBlock(ListItem):
    """One block of the question rail — key, gist, and kind, at a fixed height."""

    HEIGHT = 4

    def __init__(self, question: Question, *, active: bool, draft: bool) -> None:
        super().__init__(id=f"row-{question.key}")
        self.key = question.key
        self._text = Static(self._block(question, active, draft), markup=False)
        self.set_class(active, "active")
        self._dim(question)

    @staticmethod
    def _kind_line(q: Question, draft: bool) -> str:
        if q.act == "plan":
            done = sum(1 for st in q.steps if st.done)
            shape = f"{done}/{len(q.steps)} steps"
        elif q.kind == "choice":
            shape = f"{len(q.choices)} choices"
        elif q.kind == "multi":
            shape = f"{len(q.choices)} choices · multi"
        elif q.kind == "confirm":
            # The row's own choice labels (a review reads pass / fail, a run
            # reads approve / deny) — a fixed "yes / no" would lie about what
            # the keys send, same reasoning as `_confirm_pairs` on the card.
            labels = [c.label for c in q.choices] or ["yes", "no"]
            shape = " / ".join(labels)
        else:
            shape = "text"
        # The act leads, because it says what is being asked of the reader; a
        # live row is marked so a re-answerable one is never mistaken for a
        # fork that is still holding an agent.
        parts = [q.act, shape]
        if q.status == "live":
            parts.append("live")
        elif q.status == "elaborate":
            parts.append("wants more")
        if q.blocked and q.status == "open":
            parts.append("BLOCKING")
        elif not q.blocked and q.status == "open":
            parts.append("not blocking")
        if q.source:
            parts.append(q.source.upper())
        if draft:
            parts.append("draft")
        return " · ".join(parts)

    @classmethod
    def _block(cls, q: Question, active: bool, draft: bool) -> str:
        pad = "  " * q.depth
        marker = "▸" if active else " "
        return "\n".join([
            f"{marker} {pad}{q.key}",
            f"  {pad}{_flatten(q.text)}",
            f"  {pad}{cls._kind_line(q, draft)}",
        ])

    def compose(self) -> ComposeResult:
        yield self._text

    def update(self, question: Question, *, active: bool, draft: bool) -> None:
        self._text.update(self._block(question, active, draft))
        self.set_class(active, "active")
        self._dim(question)

    def _dim(self, question: Question) -> None:
        """`-sent` / `-heard` while a review/plan verdict awaits the agent (q405)."""
        state = question.heard_state
        self.set_class(state == "sent", "-sent")
        self.set_class(state == "heard", "-heard")


class CactusApp(App[int]):
    """Human answering surface for the cactus question inbox."""

    TITLE = "cactus"
    SUB_TITLE = "answering"
    # No palette: its header icon and footer hint are chrome with no cactus use.
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #body {
        height: 1fr;
    }
    #body.bottom {
        layout: vertical;
    }
    #projects-pane {
        width: 22;
        border-right: solid $panel;
        padding: 0 1;
        overflow-y: auto;
        color: $text-muted;
    }
    #body.bottom #projects-pane {
        display: none;
    }
    #rail {
        width: 32;
        border-right: solid $panel;
    }
    #project-head {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    #rail-list {
        height: 1fr;
    }
    #rail-list > ListItem {
        /* Fixed block height: a rail that resizes per question would shift
           every other block under the reader's eye on each refresh. */
        height: 4;
        padding: 0 1;
        color: $text-muted;
    }
    #rail-list > ListItem.active {
        color: $text;
        text-style: bold;
    }
    #rail-list Static {
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    #main {
        width: 1fr;
    }
    #body.bottom #rail {
        dock: bottom;
        width: 1fr;
        height: 12;
        border-right: none;
        border-top: solid $panel;
    }
    #body.bottom #main {
        width: 1fr;
        height: 1fr;
    }
    #project-banner {
        display: none;
        background: $panel;
        color: $accent;
        padding: 0 1;
        text-wrap: nowrap;
    }
    #settings-panel {
        display: none;
        height: 1fr;
        border: round $accent;
        margin: 1 2;
        padding: 1 2;
    }
    #projects-panel {
        display: none;
        height: 1fr;
        border: round $accent;
        margin: 1 2;
        padding: 1 2;
        overflow-y: auto;
    }
    #answers-panel {
        display: none;
        height: 1fr;
        border: round $accent;
        margin: 1 2;
        padding: 1 2;
        overflow-y: auto;
    }
    #tuning-scroll {
        display: none;
        height: 1fr;
        border: round $accent;
        margin: 1 2;
        padding: 0 2;
    }
    #tuning-panel {
        display: none;
        height: auto;
        padding: 1 0;
    }
    #card {
        border: round $accent;
        margin: 0 1;
        height: 1fr;
    }
    #card.-sent #card-text, #card.-heard #card-text {
        opacity: 60%;
    }
    QuestionBlock.-sent, QuestionBlock.-heard {
        opacity: 60%;
    }
    /* Card first: the text takes every row it needs, up to the whole card
       above the docked key bar (then it scrolls); the field gets the rest. */
    #card-text {
        height: auto;
        max-height: 100%;
        overflow-y: auto;
        padding: 0 2;
    }
    #answer-input {
        display: none;
        margin: 0 1;
    }
    #status-bar {
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    #field {
        height: 1fr;
        min-height: 0;
        width: 100%;
        background: $surface;
    }
    #keybar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("up", "focus_prev", "Up", show=False),
        Binding("down", "focus_next", "Down", show=False),
        Binding("j", "focus_next", "Down"),
        Binding("k", "focus_prev", "Up"),
        Binding("enter", "submit", "Submit"),
        # priority: the Input would otherwise swallow escape and strand focus
        # inside a text question, where j/k/[/] are unreachable.
        Binding("escape", "leave_input", "Back", show=False, priority=True),
        # Row-dependent: what these keys do — and whether they mean anything
        # at all — depends on the focused row, so they live in the in-card
        # key bar (`_rebuild_keybar`) instead of the Footer, which now only
        # ever shows the global keys.
        Binding("s", "skip", "Skip (answers)", show=False),
        Binding("c", "clear_focused", "Clear", show=False),
        Binding("x", "close_row", "Close", show=False),
        Binding("i", "toggle_free_text", "type", show=False),
        Binding("y", "confirm_yes", "Yes", show=False),
        Binding("n", "confirm_no", "No", show=False),
        Binding("[", "prev_project", "PrevProj", key_display="["),
        Binding("]", "next_project", "NextProj", key_display="]"),
        Binding("P", "open_projects", "Projects"),
        Binding("a", "open_answers", "Answers"),
        Binding("I", "ignore_project", "Ignore"),
        Binding("A", "activate_project", "Activate"),
        Binding("u", "undo", "Undo", show=False),
        Binding("e", "elaborate", "Elaborate", show=False),
        Binding("D", "decompose", "Decompose", show=False),
        Binding("?", "open_settings", "Settings", key_display="?"),
        Binding("T", "open_tuning", "Tune"),
        Binding("p", "poke", "Poke", show=False),
        Binding("v", "visit", "Visit", show=False),
        Binding("C", "copy_command", "Copy", show=False),
        Binding("R", "run_command", "Run", show=False),
        Binding("O", "open_output", "Output", show=False),
        Binding("f", "view_file", "View file", show=False),
        Binding("F", "edit_file", "Edit file", show=False),
        Binding("o", "toggle_preview", "Preview files", show=False),
        Binding("d", "dismiss", "Dismiss", show=False),
        Binding("r", "refresh_view", "Refresh"),
        # Manual seed drop (q368) / garden toggles: the bare glyph (`grave`)
        # drops a seed while the field is shown, or flips `pile_only` while
        # it is hidden — one binding either way, `action_grave` dispatches.
        # The shifted glyph (`tilde`) always toggles the field itself.
        Binding("grave_accent", "grave", "drop", key_display="`"),
        Binding("tilde", "toggle_field", "field", show=False, key_display="`"),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+c", "quit_app", "Quit", show=False),
        # Neutral label: the digits pick a choice on an ask row but toggle a
        # step on a plan row. The in-card key bar (`_rebuild_keybar`) is what
        # shows the focused row's own wording for each digit now; the Footer
        # never shows the digits at all.
        Binding("1", "select_choice(1)", "Pick", show=False, key_display="1-9"),
        Binding("2", "select_choice(2)", "2", show=False),
        Binding("3", "select_choice(3)", "3", show=False),
        Binding("4", "select_choice(4)", "4", show=False),
        Binding("5", "select_choice(5)", "5", show=False),
        Binding("6", "select_choice(6)", "6", show=False),
        Binding("7", "select_choice(7)", "7", show=False),
        Binding("8", "select_choice(8)", "8", show=False),
        Binding("9", "select_choice(9)", "9", show=False),
    ]

    def __init__(self, store: Store, project: str | None = None) -> None:
        super().__init__()
        self.store = store
        # Route a record-write failure to the status line instead of stderr,
        # which a Textual screen would otherwise swallow or corrupt.
        self.store.record_warning = self._on_record_warning
        self.scoped_project = project
        self.current_project: str | None = project
        self.questions: list[Question] = []
        self.focused_key: str | None = None
        self.multi_selected: set[str] = set()
        self.drafts: dict[str, str] = {}
        self.undo_stack: list[dict[str, Any]] = []
        self.run_output = {}
        # Project of each running command's row: keys are only unique per project.
        self.run_projects: dict[str, str] = {}
        self.run_state = {}
        self.tui_settings = _load_tui_settings()
        self.settings_open = False
        self.projects_open = False
        self.project_rows: list[dict[str, Any]] = []
        self.project_index = 0
        # answers_open follows the exact pattern settings_open/projects_open
        # use (q354 vetoed a `view` enum): the three panel booleans are
        # mutually exclusive, never more than one true at a time.
        self.answers_open = False
        self.answers_rows: list[Question] = []
        self.answers_index = 0
        self.answers_expanded = False
        # T tuning overlay (v6c): same mutual-exclusion pattern as the three
        # panels above. tuning_rows is rebuilt fresh from sky.tuning_fields()
        # on every open, so a key added to SkyConfig always shows up.
        self.tuning_open = False
        self.tuning_rows: list[TuneField] = []
        self.tuning_index = 0
        # Save/recall slots (v6g): armed by `S`, a following digit 1-9 saves
        # the live config to that slot; a bare digit (not armed) recalls it.
        # A named slot (v6h) takes one more step: the digit opens a name
        # prompt (tuning_name_slot set, tuning_name_buf the typed text)
        # rather than saving immediately.
        self.tuning_save_armed = False
        self.tuning_name_slot: int | None = None
        self.tuning_name_buf = ""
        self._figlet_label: str | None = None
        self._figlet_text = ""
        self.free_text_mode = False
        # Set while the input is open for `e`'s prompt, so on_input_submitted
        # and escape route to the elaborate request instead of an answer.
        self.elaborating = False
        self.last_cursor: tuple[int, str, int] = (-1, "", -1)
        self._rebuilding = False
        # One lock serializes every reload and every rail rebuild: the rebuild
        # awaits `clear`/`append`, so two of them interleaving would append the
        # same row id twice (DuplicateIds). A poll that finds it held sets
        # `_reload_pending` and returns; the holder loops once more.
        self._reload_lock = asyncio.Lock()
        self._reload_pending = False
        # Row moves (j/k/arrows) requested while a rebuild is in flight,
        # applied by the rebuild once it has restored focus.
        self._rebuild_move = 0
        self._synced_key: str | None = None
        # Plan keys already seen fully done, so the "all done" flash fires
        # once per completion rather than on every poll.
        self._plan_all_done: set[str] = set()
        # Digit buffer for a plan step past 9 (q16): "1" then "2" reaches
        # step 12 instead of toggling step 1 immediately. Empty when idle.
        self._step_buffer = ""
        self._step_buffer_key: str | None = None
        self._step_buffer_timer = None
        # Digit-prefix arming for a multi-file row's `f`/`F`: which action is
        # armed ("view"/"edit"), which row it was armed on, and the timer that
        # disarms it if no digit follows. None/empty when idle.
        self.file_pending: str | None = None
        self.file_pending_key: str | None = None
        self.file_pending_timer = None
        # `o` inline preview of the focused row's files; resets on a row move.
        self.preview_open = False
        # Field: an in-memory sky/weather/cactus simulation living inside the
        # card, anchored to the bottom under the key bar. Sized 1x10 until
        # the first render, when the FieldView's actual size is known.
        self.world = World(cols=1, rows=10)
        self._field_timer = None
        # Continuous time (v6b): `_field_tick` measures real elapsed seconds
        # between calls, clamped to 0.5 s so a stalled terminal never makes
        # the field jump, and passes that `dt` straight to `world.advance`.
        self._field_last_time: float | None = None
        # Frame rate lever (v6f): the timer's own sampling interval, `1 /
        # SkyConfig.fps` — `_sync_field_interval` restarts the timer only when
        # this has actually changed from whatever it was last started at.
        self._field_interval: float | None = None
        # Change-only redraw (v6f): the last frame's `(plain, spans)` handed
        # to the field widget, so an unchanged sky never repaints.
        self._field_last_signature: tuple[str, list] | None = None
        # Sky tuning: reread the config file every SKY_RELOAD_SECONDS of wall
        # time, only acting on it when its mtime has actually moved.
        self._sky_config_mtime: float | None = None
        self._sky_reload_last: float | None = None
        # Each key bar glyph's field column (its x from the card's left edge,
        # which `#field` shares), rebuilt on every `_rebuild_keybar` —
        # `_field_column` reads this to drop a seed under the key that answered.
        self._keybar_x: dict[str, int] = {}
        # Garden persistence: the landed pile is shared across every TUI on
        # this database, saved beside it (garden.py) and reloaded whenever
        # another process's write is newer than ours.
        self._garden_path = garden.garden_path(self.store.path)
        self._garden_mtime: float | None = None

    @property
    def pending_text(self) -> str:
        """Free text typed for the active question, held per key.

        Drafts are keyed so moving through the queue or switching projects does
        not silently discard what was already typed.
        """
        return self.drafts.get(self.focused_key or "", "")

    @pending_text.setter
    def pending_text(self, value: str) -> None:
        if self.focused_key is None:
            return
        if value:
            self.drafts[self.focused_key] = value
        else:
            self.drafts.pop(self.focused_key, None)

    # ---- layout -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(icon="")
        yield Static(id="project-banner", markup=False)
        with Horizontal(id="body"):
            yield Static(id="projects-pane", markup=False)
            with Vertical(id="rail"):
                yield Static(id="project-head", markup=False)
                yield RailList(id="rail-list")
            with Vertical(id="main"):
                with Vertical(id="card"):
                    yield Static(id="card-text", markup=False)
                    yield FieldView(id="field", markup=False)
                    yield KeyBar(id="keybar", markup=False)
                yield Input(id="answer-input", placeholder="free text — enter to confirm")
        yield Static(id="settings-panel", markup=False)
        yield Static(id="projects-panel", markup=False)
        yield Static(id="answers-panel", markup=False)
        yield VerticalScroll(Static(id="tuning-panel", markup=False), id="tuning-scroll")
        yield Static(id="status-bar", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        if self.scoped_project is None:
            live = self._live_projects()
            if self.current_project is None and live:
                self.current_project = live[0]
        self.query_one("#card", Vertical).border_title = "answering"
        self._apply_tui_settings()
        await self._reload(force=True)
        self.query_one("#rail-list", ListView).focus()
        self._sync_input_focus()
        # The footer's first read of check_action lands before the first row is
        # focused; re-ask once the screen has settled.
        self.call_after_refresh(self.refresh_bindings)
        self.set_interval(POLL_INTERVAL, self._poll)
        self._reload_sky_config(initial=True)
        self._load_garden()
        self._sky_reload_last = time.monotonic()
        self._field_last_time = time.monotonic()
        self._sync_field_interval()
        self._render_field()

    def _apply_tui_settings(self) -> None:
        body = self.query_one("#body", Horizontal)
        body.set_class(self.tui_settings["orientation"] == "bottom", "bottom")
        self._rebuild_project_banner()
        self._rebuild_projects_pane()
        self._apply_field_visibility()

    def _apply_field_visibility(self) -> None:
        """Show/hide `#field` per `field`/`pile_only`. The timer keeps
        running either way: a hidden garden still grows — every answer's
        seed still falls and lands, and the landing still reaches
        garden.json for the other TUIs — only the draw is skipped
        (`_render_field` returns early while nothing is on screen)."""
        self._fit_field()
        self._sync_field_interval()
        self.call_after_refresh(self._render_field)

    def _fit_field(self) -> None:
        """Card first: size `#field` to the rows the card leaves over.

        CSS does the split — `#card-text` is `height: auto` capped at the
        card, `#keybar` docks to the bottom, `#field` is `1fr` with no
        minimum — so the field already gets exactly the remainder. This
        only adds what CSS cannot say: below `FIELD_MIN_ROWS` spare rows the
        field is hidden, not squashed. Spare is measured from the text's own
        height, which never depends on the field, so hiding cannot flip it.
        Pile-only caps the field at the pile's rows and shows down to the
        pile's own height when that is under the minimum."""
        try:
            card = self.query_one("#card", Vertical)
            text = self.query_one("#card-text", Static)
            keybar = self.query_one("#keybar", Static)
            widget = self.query_one("#field", FieldView)
        except NoMatches:
            return
        pile_only = not self.tui_settings["field"] and self.tui_settings["pile_only"]
        floor = FIELD_MIN_ROWS
        if pile_only:
            rows = self.world.pile_rows()
            widget.styles.max_height = rows
            floor = min(rows, FIELD_MIN_ROWS)
        else:
            widget.styles.max_height = None
        spare = card.content_size.height - keybar.outer_size.height - text.outer_size.height
        show = (self.tui_settings["field"] or self.tui_settings["pile_only"]) and spare >= floor
        if widget.display != show:
            widget.display = show

    def _rebuild_project_banner(self) -> None:
        banner = self.query_one("#project-banner", Static)
        if not self.tui_settings["figlet_header"] or self.current_project is None:
            banner.display = False
            return
        label = project_label(self.current_project)
        if label != self._figlet_label:
            self._figlet_label = label
            self._figlet_text = _figlet_project_name(label)
        banner.update(self._figlet_text)
        banner.display = True

    def _settings_text(self) -> str:
        orientation = self.tui_settings["orientation"]
        figlet = "on" if self.tui_settings["figlet_header"] else "off"
        pane = "on" if self.tui_settings["projects_pane"] else "off"
        release = self.tui_settings["seed_release"]
        align = self.tui_settings["keybar_align"]
        return "\n".join([
            "settings",
            "",
            f"1  left / right   questions left, detail right  {'●' if orientation == 'side' else '○'}",
            f"2  under / over   detail above, questions bottom {'●' if orientation == 'bottom' else '○'}",
            f"3  projects pane  due-ranked, left of the rail    {pane}",
            f"4  seed release   drop under the key, or mirror   {release}",
            f"5  key bar        left / center / right           {align}",
            f"f  Figlet project header (cybermedium)            {figlet}",
            "",
            "esc or ?  return to the inbox",
        ])

    def _projects_text(self) -> str:
        """Render all known projects, including ignored and currently quiet ones.

        Line: `▸ label  active  N due · N live · N answered  3m` — due leads
        because it is what ranks the list (q349/q351); the relative last
        activity (`_relative_age`) trails, same reading order as the answers
        view's own line.
        """
        if not self.project_rows:
            return "projects\n\nno projects yet\n\nesc or P  return to inbox"
        lines = ["projects", ""]
        for i, row in enumerate(self.project_rows):
            marker = "▸" if i == self.project_index else " "
            state = "active" if row["enabled"] else "ignored"
            counts = f"{row['due_count']} due"
            if row["live_count"]:
                counts += f" · {row['live_count']} live"
            if row["answered_count"]:
                counts += f" · {row['answered_count']} answered"
            age = f"  {_relative_age(row['last_activity'])}" if row["last_activity"] else ""
            lines.append(f"{marker} {project_label(row['project'])}  {state}  {counts}{age}")
        lines.extend(["", "j/k or ↑/↓ move   enter open   I ignore   A activate   p poke", "esc or P  return to inbox"])
        return "\n".join(lines)

    def _render_projects(self) -> None:
        self.project_rows = self.store.projects()
        if self.project_rows:
            self.project_index = max(0, min(self.project_index, len(self.project_rows) - 1))
        else:
            self.project_index = 0
        self.query_one("#projects-panel", Static).update(self._projects_text())

    def _rebuild_projects_pane(self) -> None:
        """The main-screen projects pane (q349/q352): due-ranked, left of the rail.

        Read-only and never focused — it is a preview, not a second way to
        answer. Hidden in `bottom` orientation (there is no room beside the
        rail there) and behind the settings `3` toggle. Never shifts the rail
        rows: it lives in its own column of `#body`, beside the rail, not
        stacked above it.
        """
        pane = self.query_one("#projects-pane", Static)
        visible = self.tui_settings["projects_pane"] and self.tui_settings["orientation"] != "bottom"
        pane.display = visible
        if not visible:
            return
        rows = [r for r in self.store.projects() if r["enabled"]]
        lines = []
        for row in rows:
            marker = "▸" if row["project"] == self.current_project else " "
            lines.append(f"{marker} {project_label(row['project'])}  {row['due_count']}")
        pane.update("\n".join(lines))

    def _toggle_projects_pane(self) -> None:
        self.tui_settings["projects_pane"] = not self.tui_settings["projects_pane"]
        self._apply_tui_settings()
        self._save_settings()
        self._render_settings()

    def _render_settings(self) -> None:
        self.query_one("#settings-panel", Static).update(self._settings_text())

    # ---- answers view (`a`) --------------------------------------------

    def _load_answers(self) -> None:
        """Reload this view's rows from the store: current project only (q353)."""
        self.answers_rows = (
            self.store.history(self.current_project, limit=200)
            if self.current_project else []
        )
        if self.answers_rows:
            self.answers_index = max(0, min(self.answers_index, len(self.answers_rows) - 1))
        else:
            self.answers_index = 0

    def _render_answers(self) -> None:
        """Reload and redraw — the entry point on open and on project rotation."""
        self._load_answers()
        self.answers_expanded = False
        self._redraw_answers()

    def _redraw_answers(self) -> None:
        """Redraw from already-loaded rows — a selection move needs no reload."""
        self.query_one("#answers-panel", Static).update(self._answers_text())

    @staticmethod
    def _answers_verdict(q: Question) -> str:
        """The line's verdict column: `cleared` overrides even a real verdict (q347)."""
        if q.status == "cleared":
            return "cleared"
        return _verdict_repr(q.answers[-1]) if q.answers else "—"

    @staticmethod
    def _answers_age(q: Question) -> str:
        ts = q.answers[-1].created_at if q.answers else q.updated_at
        return _relative_age(ts)

    def _answers_text(self) -> str:
        """Line: `q123  question text…  → verdict  2h`; enter expands the selected one."""
        label = project_label(self.current_project) if self.current_project else "no project"
        header = f"answers — {label}"
        if not self.answers_rows:
            return f"{header}\n\nno history yet\n\nj/k or [ ] switch project   esc or a  return to inbox"
        lines = [header, ""]
        for i, q in enumerate(self.answers_rows):
            marker = "▸" if i == self.answers_index else " "
            text = _flatten(q.text)
            if len(text) > 48:
                text = text[:47] + "…"
            lines.append(
                f"{marker} {q.key}  {text}  → {self._answers_verdict(q)}  {self._answers_age(q)}"
            )
            if i == self.answers_index and self.answers_expanded:
                lines.append("")
                lines.append(f"    {q.text}")
                if q.context:
                    lines.append(f"    {q.context}")
                for a in q.answers:
                    lines.append(f"      {_verdict_repr(a)}  ({_relative_age(a.created_at)})")
                lines.append("")
        lines.extend([
            "", "j/k move   enter expand   [ ] switch project", "esc or a  return to inbox",
        ])
        return "\n".join(lines)

    def _save_settings(self) -> None:
        error = _save_tui_settings(self.tui_settings)
        if error:
            self.flash = f"settings not saved: {error}"

    def action_open_settings(self) -> None:
        if self.settings_open:
            self._close_settings()
            return
        self.free_text_mode = False
        self.elaborating = False
        self._hide_input()
        self._close_other_panels("settings")
        self.settings_open = True
        self.query_one("#body", Horizontal).display = False
        panel = self.query_one("#settings-panel", Static)
        panel.display = True
        self._render_settings()
        self.refresh_bindings()

    def action_open_projects(self) -> None:
        """Toggle the project manager without stealing text-entry keys."""
        if self.free_text_mode or self.elaborating:
            return
        if self.projects_open:
            self._close_projects()
            return
        self._close_other_panels("projects")
        self.projects_open = True
        self.query_one("#body", Horizontal).display = False
        panel = self.query_one("#projects-panel", Static)
        panel.display = True
        self._render_projects()
        self.refresh_bindings()

    def _close_projects(self) -> None:
        self.projects_open = False
        self.query_one("#projects-panel", Static).display = False
        self.query_one("#body", Horizontal).display = True
        self._sync_input_focus()
        self.refresh_bindings()

    def action_open_answers(self) -> None:
        """`a`: toggle the answers view — this project's history (q347/q353).

        Same pattern as `action_open_projects`: mutually exclusive with the
        settings and projects panels, and never steals text-entry keys.
        """
        if self.free_text_mode or self.elaborating:
            return
        if self.answers_open:
            self._close_answers()
            return
        self._close_other_panels("answers")
        self.answers_open = True
        self.query_one("#body", Horizontal).display = False
        panel = self.query_one("#answers-panel", Static)
        panel.display = True
        self._render_answers()
        self.refresh_bindings()

    def _close_answers(self) -> None:
        self.answers_open = False
        self.query_one("#answers-panel", Static).display = False
        self.query_one("#body", Horizontal).display = True
        self._sync_input_focus()
        self.refresh_bindings()

    def _close_other_panels(self, opening: str) -> None:
        """Settings/projects/answers/tuning are mutually exclusive (q354 vetoed
        a `view` enum; the v6c tuning overlay follows the same pattern).

        Called by each panel's own open action before it flips its own flag,
        so opening one always closes whichever of the others was open.
        """
        if opening != "settings" and self.settings_open:
            self.settings_open = False
            self.query_one("#settings-panel", Static).display = False
        if opening != "projects" and self.projects_open:
            self.projects_open = False
            self.query_one("#projects-panel", Static).display = False
        if opening != "answers" and self.answers_open:
            self.answers_open = False
            self.query_one("#answers-panel", Static).display = False
        if opening != "tuning" and self.tuning_open:
            self.tuning_open = False
            self.query_one("#tuning-panel", Static).display = False
            self.query_one("#tuning-scroll", VerticalScroll).display = False

    # ---- tuning overlay (`T`, v6c) --------------------------------------

    def action_open_tuning(self) -> None:
        if self.tuning_open:
            self._close_tuning()
            return
        self.free_text_mode = False
        self.elaborating = False
        self._hide_input()
        self._close_other_panels("tuning")
        self.tuning_open = True
        self.tuning_rows = tuning_fields_for(self.world.sky.config)
        if self.tuning_rows:
            self.tuning_index = max(0, min(self.tuning_index, len(self.tuning_rows) - 1))
        else:
            self.tuning_index = 0
        self.query_one("#body", Horizontal).display = False
        self.query_one("#tuning-scroll", VerticalScroll).display = True
        panel = self.query_one("#tuning-panel", Static)
        panel.display = True
        self._render_tuning()
        self.refresh_bindings()

    def _close_tuning(self) -> None:
        self.tuning_open = False
        self.query_one("#tuning-panel", Static).display = False
        self.query_one("#tuning-scroll", VerticalScroll).display = False
        self.query_one("#body", Horizontal).display = True
        self._sync_input_focus()
        self.refresh_bindings()

    def _tuning_obj(self, group: str) -> Any:
        """The live object a tuning row's field lives on: a grid's own
        `GridConfig`, or the `SkyConfig` itself for a `shared` row."""
        cfg = self.world.sky.config
        return cfg if group == "shared" else getattr(cfg, group)

    def _apply_and_dump_tuning(self) -> None:
        """Push the mutated config into the running grids and to disk in one
        step, so the overlay, the sky, and the file never disagree — then
        remember the write's own mtime so the reload timer skips it."""
        cfg = self.world.sky.config
        self.world.apply_sky_config(cfg)
        self._sync_field_interval()
        path = cfg.dump()
        try:
            self._sky_config_mtime = path.stat().st_mtime
        except OSError:
            pass

    def _move_tuning_cursor(self, delta: int) -> None:
        if not self.tuning_rows:
            return
        # tuning_rows is in panel order (sky.tuning_fields_for), so a flat
        # step past a panel's last row lands on the next panel's first.
        self.tuning_index = (self.tuning_index + delta) % len(self.tuning_rows)
        self._render_tuning()

    def _tuning_panels(self) -> list[tuple[str, int, int]]:
        """The non-empty panels in page order as `(name, start, end)` slices
        of `tuning_rows` — contiguous because the rows arrive panel-sorted."""
        spans: list[tuple[str, int, int]] = []
        for i, row in enumerate(self.tuning_rows):
            name = tuning_panel_of(row)
            if spans and spans[-1][0] == name:
                spans[-1] = (name, spans[-1][1], i + 1)
            else:
                spans.append((name, i, i + 1))
        return spans

    def _current_tuning_panel(self) -> int:
        """Index into `_tuning_panels()` of the panel holding the cursor."""
        for n, (_, start, end) in enumerate(self._tuning_panels()):
            if start <= self.tuning_index < end:
                return n
        return 0

    def _switch_tuning_panel(self, delta: int) -> None:
        """`tab`/`]` (+1) and `shift+tab`/`[` (-1): the cursor jumps to the
        first row of the next/previous non-empty panel, wrapping."""
        panels = self._tuning_panels()
        if not panels:
            return
        n = (self._current_tuning_panel() + delta) % len(panels)
        self.tuning_index = panels[n][1]
        self._render_tuning()

    def _nudge_tuning(self, steps: int) -> None:
        """Move the focused key by `steps` of its own declared `step`
        (negative for h/H, positive for l/L; `steps` is `±1` or `±10`).

        A `choices`-valued row (v6d, e.g. `pile_style`) has no numeric step:
        `h`/`l` instead cycle to the previous/next value in that tuple, one
        step regardless of `steps`'s magnitude — `H`/`L`'s x10 has nothing
        further to multiply against a handful of fixed choices.
        """
        if not self.tuning_rows:
            return
        row = self.tuning_rows[self.tuning_index]
        obj = self._tuning_obj(row.group)
        if row.choices is not None:
            old = getattr(obj, row.name)
            choices = row.choices
            idx = choices.index(old) if old in choices else 0
            new = choices[(idx + (1 if steps > 0 else -1)) % len(choices)]
            setattr(obj, row.name, new)
            self._apply_and_dump_tuning()
            self._render_tuning()
            return
        if row.step is None:
            self.flash = f"{row.name} has no tuning range"
            self._rebuild_status_bar()
            return
        old = getattr(obj, row.name)
        new = old + row.step * steps
        if row.lo is not None:
            new = max(row.lo, new)
        if row.hi is not None:
            new = min(row.hi, new)
        if isinstance(old, int) and not isinstance(old, bool):
            new = int(round(new))
        setattr(obj, row.name, new)
        self._apply_and_dump_tuning()
        self._render_tuning()

    def _reset_tuning(self) -> None:
        if not self.tuning_rows:
            return
        row = self.tuning_rows[self.tuning_index]
        default_cfg = SkyConfig()
        default_obj = default_cfg if row.group == "shared" else getattr(default_cfg, row.group)
        default_value = getattr(default_obj, row.name)
        setattr(self._tuning_obj(row.group), row.name, default_value)
        self._apply_and_dump_tuning()
        self.flash = f"{row.name} reset to {default_value!r}"
        self._render_tuning()
        self._rebuild_status_bar()

    def _slot_grid_lines(self) -> list[str]:
        """The named-slot grid, three per row: `N label` cells padded to
        line up, an empty slot reads `N —`, a nameless one `N (unnamed)`."""
        names = sky_slots()
        cells = []
        for n in sorted(names):
            name = names[n]
            if name is None:
                label = "—"
            elif name == "":
                label = "(unnamed)"
            else:
                label = name if len(name) <= 18 else name[:17] + "…"
            cells.append(f"{n} {label}")
        width = max((len(c) for c in cells), default=0)
        cells = [c.ljust(width) for c in cells]
        return ["  " + "  ".join(cells[i:i + 3]) for i in range(0, len(cells), 3)]

    def _tuning_text(self) -> str:
        return "\n".join(self._tuning_lines()[0])

    def _tuning_lines(self) -> tuple[list[str], int]:
        """The overlay's lines and the index of the cursor's line in them
        (0 when there is no cursor) — the title, the panel strip, the
        saved-skies grid, then only the current panel's rows."""
        if not self.tuning_rows:
            return ["tuning", "", "no tunable keys", "", "esc or T  return to inbox"], 0
        cfg = self.world.sky.config
        engine = cfg.sky_engine + (f" / {cfg.cloud_style}" if cfg.sky_engine == "puffs" else "")
        panels = self._tuning_panels()
        current = self._current_tuning_panel()
        strip = "  ".join(f"[{name}]" if n == current else name for n, (name, _, _) in enumerate(panels))
        lines = [f"tuning   engine {engine}   (keys shown follow the engine)", "", strip, ""]
        lines.append("saved skies      digit loads one    S then digit saves the current sky")
        lines.extend(self._slot_grid_lines())
        if self.tuning_name_slot is not None:
            lines.append(f"  name for slot {self.tuning_name_slot}: {self.tuning_name_buf}▏   enter saves   esc cancels")
        elif self.tuning_save_armed:
            lines.append("  press a digit 1-9 to name and save the current sky there (esc cancels)")
        lines.append("")
        _, start, end = panels[current]
        cursor_line = 0
        for i in range(start, end):
            row = self.tuning_rows[i]
            if i == self.tuning_index:
                cursor_line = len(lines)
            marker = "▸" if i == self.tuning_index else " "
            value = getattr(self._tuning_obj(row.group), row.name)
            lines.append(f"{marker} {row.name}  {value!r}  # {row.comment}")
        lines.extend([
            "",
            "tab / [ ]  panels   j/k ↑↓  move   h/l ←→  nudge   H/L shift+←→  x10   r  reset",
            "esc or T  return to inbox",
        ])
        return lines, cursor_line

    def _refilter_tuning(self) -> None:
        """Rebuild the visible rows for the current engine and style (v8),
        keeping the cursor on the same key when it is still shown, else on
        the nearest row above it — a nudge of `sky_engine` or `perspective`
        reshapes the page on the spot."""
        current = self.tuning_rows[self.tuning_index] if 0 <= self.tuning_index < len(self.tuning_rows) else None
        self.tuning_rows = tuning_fields_for(self.world.sky.config)
        if current is None or not self.tuning_rows:
            self.tuning_index = 0
            return
        for i, row in enumerate(self.tuning_rows):
            if row.group == current.group and row.name == current.name:
                self.tuning_index = i
                return
        self.tuning_index = max(0, min(self.tuning_index, len(self.tuning_rows) - 1))

    def _render_tuning(self) -> None:
        self._refilter_tuning()
        lines, cursor_line = self._tuning_lines()
        self.query_one("#tuning-panel", Static).update("\n".join(lines))
        # The Static's new height lands on the next layout pass; scroll after it.
        self.call_after_refresh(self._scroll_tuning_cursor)

    def _tuning_cursor_span(self) -> tuple[int, int]:
        """`(y, h)`: the cursor row's first screen row inside `#tuning-scroll`'s
        virtual space and how many rows it wraps to. A long comment wraps, so
        the logical line index alone would undercount everything above it."""
        from textual.content import Content

        lines, cursor_line = self._tuning_lines()
        panel = self.query_one("#tuning-panel", Static)
        width = max(1, panel.content_region.width)

        def rows(line: str) -> int:
            return max(1, len(Content(line).wrap(width)))

        y = panel.virtual_region.y + panel.styles.padding.top + sum(rows(line) for line in lines[:cursor_line])
        return y, rows(lines[cursor_line])

    def _scroll_tuning_cursor(self) -> None:
        """Scroll `#tuning-scroll` the least amount that brings the cursor's
        whole (possibly wrapped) row into view."""
        if not self.tuning_open or not self.tuning_rows:
            return
        scroll = self.query_one("#tuning-scroll", VerticalScroll)
        top, height = int(scroll.scroll_y), scroll.scrollable_content_region.height
        if height <= 0:
            return
        y, h = self._tuning_cursor_span()
        if y < top:
            scroll.scroll_to(y=y, animate=False)
        elif y + h > top + height:
            scroll.scroll_to(y=min(y, y + h - height), animate=False)

    def _selected_project_row(self) -> dict[str, Any] | None:
        if 0 <= self.project_index < len(self.project_rows):
            return self.project_rows[self.project_index]
        return None

    async def _set_selected_project_enabled(self, enabled: bool) -> None:
        row = self._selected_project_row()
        if row is None:
            return
        self.store.set_project_enabled(row["project"], enabled)
        self.flash = f"{project_label(row['project'])} — {'active' if enabled else 'ignored'}"
        self._render_projects()
        await self._reload(force=True)

    async def action_ignore_project(self) -> None:
        if self.projects_open:
            await self._set_selected_project_enabled(False)

    async def action_activate_project(self) -> None:
        if self.projects_open:
            await self._set_selected_project_enabled(True)

    def _close_settings(self) -> None:
        self.settings_open = False
        self.query_one("#settings-panel", Static).display = False
        self.query_one("#body", Horizontal).display = True
        self._sync_input_focus()
        self.refresh_bindings()

    def _set_orientation(self, orientation: str) -> None:
        self.tui_settings["orientation"] = orientation
        self._apply_tui_settings()
        self._save_settings()
        self._render_settings()

    def _toggle_figlet_header(self) -> None:
        self.tui_settings["figlet_header"] = not self.tui_settings["figlet_header"]
        self._apply_tui_settings()
        self._save_settings()
        self._render_settings()

    def _toggle_seed_release(self) -> None:
        """Flip `seed_release` between `left` (a seed drops under its key)
        and `right` (the mirrored column); `_field_column` reads it."""
        self.tui_settings["seed_release"] = "right" if self.tui_settings["seed_release"] == "left" else "left"
        self._save_settings()
        self._render_settings()

    def _cycle_keybar_align(self) -> None:
        """Cycle `keybar_align` left -> center -> right -> left and re-pad
        the bar, so `_keybar_x` (and every later seed drop) follows it."""
        i = KEYBAR_ALIGNS.index(self.tui_settings["keybar_align"])
        self.tui_settings["keybar_align"] = KEYBAR_ALIGNS[(i + 1) % len(KEYBAR_ALIGNS)]
        self._rebuild_keybar()
        self._save_settings()
        self._render_settings()

    # ---- data loading ---------------------------------------------------

    def _live_projects(self) -> list[str]:
        """Projects with something left to answer.

        A drained project is not a place to be: switching into one lands on an
        empty rail with nothing to do, so it leaves the rotation until an agent
        asks there again.
        """
        return [r["project"] for r in self._live_projects_rows()]

    def _load_questions(self) -> None:
        self.questions = self.store.tree(
            project=self.current_project,
            status=list(ACTIONABLE),
            all_projects=self.current_project is None,
        )
        self.questions = self._raise_blocking_acp(self.questions)
        if self.questions or self.scoped_project is not None:
            return
        live = self._live_projects()
        if live and self.current_project not in live:
            self.current_project = live[0]
            self.questions = self.store.tree(
                project=self.current_project, status=list(ACTIONABLE)
            )
            self.questions = self._raise_blocking_acp(self.questions)

    @staticmethod
    def _raise_blocking_acp(rows: list[Question]) -> list[Question]:
        """Put a blocking ACP request before ordinary root question groups.

        ``Store.tree`` deliberately keeps insertion order for stable board
        letters.  The answering surface can still elevate protocol requests
        whose agent is waiting, while moving each root and all its children as
        one block so thread structure never changes.
        """
        groups: list[list[Question]] = []
        current: list[Question] = []
        for q in rows:
            if q.depth == 0:
                if current:
                    groups.append(current)
                current = [q]
            else:
                current.append(q)
        if current:
            groups.append(current)
        urgent = [g for g in groups if g[0].source == "acp" and g[0].blocked and g[0].status == "open"]
        return [q for group in urgent + [g for g in groups if g not in urgent] for q in group]

    async def _reload(self, *, force: bool = False) -> None:
        async with self._reload_lock:
            await self._reload_locked(force=force)
            # Polls that landed while this held the lock coalesced into the
            # flag; run their rebuild once, and only if the cursor moved.
            while self._reload_pending:
                await self._reload_locked(force=False)

    async def _reload_locked(self, *, force: bool) -> None:
        self._reload_pending = False
        cursor = self.store.cursor()
        if not force and cursor == self.last_cursor:
            return
        self.last_cursor = cursor
        self._load_questions()
        self._flash_plan_done()
        self._rebuild_project_banner()
        self._rebuild_project_head()
        self._rebuild_projects_pane()
        await self._rebuild_rail_locked()
        self._rebuild_card()
        self._rebuild_status_bar()

    async def _poll(self) -> None:
        if self._reload_lock.locked():
            self._reload_pending = True
            return
        await self._reload()

    async def action_refresh_view(self) -> None:
        await self._reload(force=True)

    def _flash_plan_done(self) -> None:
        """Flash once when a tick — from this TUI or a CLI writer — finishes a plan.

        Tracked per key so the message fires once per completion rather than
        on every poll, and clears again the moment a step reopens.
        """
        for q in self.questions:
            if q.act != "plan" or not q.steps:
                continue
            all_done = all(st.done for st in q.steps)
            if all_done and q.key not in self._plan_all_done:
                self._plan_all_done.add(q.key)
                if q.key == self.focused_key:
                    self.flash = "all done — c to close"
            elif not all_done:
                self._plan_all_done.discard(q.key)

    # ---- rendering --------------------------------------------------------

    @property
    def _show_project(self) -> bool:
        return self.scoped_project is None

    def _rebuild_project_head(self) -> None:
        head = self.query_one("#project-head", Static)
        if self.current_project is None:
            head.update("no project")
            return
        rows = self.store.projects()
        row = next((r for r in rows if r["project"] == self.current_project), None)
        open_count = row["open_count"] if row else 0
        live_count = row["live_count"] if row else 0
        label = project_label(self.current_project)
        others = len(self._live_projects())
        switch = "" if self.scoped_project is not None or others < 2 else "  [ ] switch"
        counts = f"{open_count} open"
        if live_count:
            counts += f" · {live_count} live"
        prefix = "" if self.tui_settings["figlet_header"] else f"{label}  "
        head.update(f"{prefix}{counts}{switch}")

    def _live_projects_rows(self) -> list[dict[str, Any]]:
        return [
            r for r in self.store.projects()
            if r["enabled"] and (r["open_count"] > 0 or r["live_count"] > 0)
            and (self.scoped_project is None or r["project"] == self.scoped_project)
        ]

    async def _rebuild_rail_locked(self) -> None:
        """Rebuild the rail. Caller holds `_reload_lock`; nothing else appends
        to `#rail-list`."""
        listview = self.query_one("#rail-list", ListView)
        prior_key = self.focused_key
        self._rebuilding = True
        self._rebuild_move = 0
        try:
            await listview.clear()
            for q in self.questions:
                await listview.append(
                    QuestionBlock(q, active=q.key == prior_key, draft=q.key in self.drafts)
                )
            if not self.questions:
                self.focused_key = None
                return
            target_index = 0
            for i, q in enumerate(self.questions):
                if q.key == prior_key:
                    target_index = i
                    break
            listview.index = target_index
            self.focused_key = self.questions[target_index].key
            if self.focused_key != prior_key:
                self.multi_selected = self._default_multi_selection(self.focused_key)
                row = listview.children[target_index]
                if isinstance(row, QuestionBlock):
                    active_q = self.questions[target_index]
                    row.update(active_q, active=True, draft=active_q.key in self.drafts)
        finally:
            self._rebuilding = False
        # A row move that landed mid-rebuild was parked in `_rebuild_move`
        # (the list was half built); replay it through the ListView so the
        # highlight handler does its usual focus bookkeeping.
        move, self._rebuild_move = self._rebuild_move, 0
        for _ in range(abs(move)):
            if move > 0:
                listview.action_cursor_down()
            else:
                listview.action_cursor_up()

    def _rebuild_card(self) -> None:
        card = self.query_one("#card", Vertical)
        text = self.query_one("#card-text", Static)
        q = self._current_question()
        if q is None:
            card.border_title = "answering"
            card.set_class(False, "-sent")
            card.set_class(False, "-heard")
            text.update("inbox empty — waiting for questions")
            self._rebuild_keybar()
            self.refresh_bindings()
            self.call_after_refresh(self._render_field)
            return
        card.border_title = f"answering  {q.key}"
        card.set_class(q.heard_state == "sent", "-sent")
        card.set_class(q.heard_state == "heard", "-heard")
        preview: list[str] | None = None
        if self.preview_open and q.files:
            from .shell import file_preview

            preview = [row for path in q.files for row in file_preview(path)]
        text.update(
            _card_lines(
                q,
                selected=self.multi_selected,
                pending=self.pending_text,
                show_project=self._show_project,
                run_output=self.run_output.get(q.key),
                run_state=self.run_state.get(q.key, ""),
                preview=preview,
            )
        )
        # check_action is a pure function of the focused question and its
        # state, but Textual only re-asks it here — without this call the
        # footer keeps showing the previous row's keys after every navigation
        # or answer, and the key bar (built from the same check_action gates)
        # would go stale right along with it.
        self._rebuild_keybar()
        self.refresh_bindings()
        # Card first: once the new text is laid out, re-fit the field to the
        # rows it left and resize the World to match.
        self.call_after_refresh(self._render_field)

    def _keybar_items(self, q: Question | None) -> list[tuple[str, str]]:
        """`(key, label)` pairs for the row key bar, in display order.

        Every item here is a key `check_action` would actually let through on
        this row — the bar and the keyboard agree — though not every key
        `check_action` allows is necessarily listed (free text, for one, is
        reachable from more rows than the bar spells out for).
        """
        if q is None:
            return [("`", "seed")]
        if q.status == "elaborate":
            items: list[tuple[str, str]] = [("c", "clear"), ("u", "withdraw request")]
            if self.check_action("poke", ()):
                items.append(("p", "poke"))
            if self.check_action("visit", ()):
                items.append(("v", "visit"))
            items.append(("`", "seed"))
            return items

        items = []
        if q.act == "data":
            for i, choice in enumerate(q.choices[:9], start=1):
                items.append((str(i), choice.label))
            items.append(("d", "close"))
        elif q.act == "plan":
            steps = q.steps
            if steps:
                if len(steps) <= 9:
                    for st in steps:
                        items.append((str(st.idx + 1), st.text))
                else:
                    items.append((f"1-{len(steps)}", "toggle step"))
            items.append(("i", "note"))
        elif q.act == "notify":
            items.append(("d", "dismiss"))
        elif q.kind == "confirm":
            labels = [c.label for c in q.choices] or ["yes", "no"]
            items.append(("y", labels[0]))
            items.append(("n", labels[1] if len(labels) > 1 else "no"))
        elif q.kind == "multi":
            for i, choice in enumerate(q.choices[:9], start=1):
                items.append((str(i), choice.label))
            items.append(("enter", "submit"))
            if q.allow_free:
                items.append(("i", "type"))
        elif q.kind == "text":
            if q.allow_free:
                items.append(("i", "type"))
            items.append(("enter", "submit"))
        else:  # "choice"
            for i, choice in enumerate(q.choices[:9], start=1):
                label = choice.label + ("*" if choice.label in q.recommend else "")
                items.append((str(i), label))
            if q.allow_free:
                items.append(("i", "type"))

        if self.check_action("run_command", ()):
            items.append(("R", "run"))
        if self.check_action("copy_command", ()):
            items.append(("C", "copy"))
        if self.check_action("open_output", ()):
            items.append(("O", "open"))

        if self.check_action("skip", ()):
            items.append(("s", "skip"))
        items.append(("c", "clear"))
        if self.check_action("close_row", ()):
            items.append(("x", "close"))
        if self.check_action("elaborate", ()):
            items.append(("e", "elaborate"))
        if self.check_action("decompose", ()):
            items.append(("D", "decompose"))
        if self.check_action("view_file", ()):
            items.append(("f", "view"))
        if self.check_action("edit_file", ()):
            items.append(("F", "edit"))
        if self.check_action("toggle_preview", ()):
            items.append(("o", "preview"))
        if self.check_action("poke", ()):
            items.append(("p", "poke"))
        if self.check_action("visit", ()):
            items.append(("v", "visit"))
        if self.check_action("undo", ()):
            items.append(("u", "undo"))
        items.append(("`", "seed"))
        return items

    def _rebuild_keybar(self) -> None:
        """Render the row key bar, aligned, and record each key's x offset.

        `_field_column` reads `self._keybar_x` to drop a seed under the key
        that answered — so this must run before any seed drop, which is why
        every caller runs it alongside `refresh_bindings()`. The
        `keybar_align` setting pads it left (0), center (half the slack, the
        default, so the digits sit mid-field) or right (all the slack); a bar
        with no slack is left-flush whatever the setting. Each recorded x
        includes that pad and the bar's
        own left gutter, so it is the glyph's column in `#field`, which spans
        the same card width from the same left edge.
        """
        try:
            bar = self.query_one("#keybar", Static)
        except NoMatches:
            return
        q = self._current_question()
        items = self._keybar_items(q)
        width = max(bar.size.width, 1)
        self._keybar_x = {}
        pieces: list[str] = []
        pos = 0
        for i, (key, label) in enumerate(items):
            sep = "  " if i else ""
            head = f"{sep}{key} "
            if pos + len(head) >= width and pos > 0:
                break
            self._keybar_x[key] = pos + len(sep)
            remaining = max(width - pos - len(head), 0)
            shown = label if len(label) <= remaining else (
                label[: remaining - 1] + "…" if remaining > 1 else ""
            )
            piece = head + shown
            pieces.append(piece)
            pos += len(piece)
        slack = max(width - pos, 0)
        align = self.tui_settings["keybar_align"]
        pad = slack // 2 if align == "center" else slack if align == "right" else 0
        left = pad + bar.styles.gutter.left
        self._keybar_x = {key: x + left for key, x in self._keybar_x.items()}
        bar.update(" " * pad + "".join(pieces))

    # Transient one-line feedback for actions that touch the outside world, so a
    # poke that failed says so instead of looking like a dead key.
    flash: str = ""

    # Command output, per row. Kept whole; the card shows a tail and `O` spills
    # the rest to a file, because a run worth doing is often longer than a card.
    run_output: dict[str, list[str]]
    run_state: dict[str, str]

    def _command_of(self, q: Question) -> str | None:
        return q.review.run_cmd if q.review is not None else None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show and enable a binding only where it means something.

        Textual asks this for every binding on every refresh, so the footer and
        the keyboard stay the same surface: a `Run` key offered on a row with
        no command is a promise the row cannot keep, and finding that out by
        pressing it is worse than never seeing it.
        """
        # The tuning overlay (v6c) gates off everything but quit — closing it
        # (`escape`/`T`) and its own j/k/h/l/H/L/r keys all go through
        # on_key instead, the same way settings' escape does.
        if self.tuning_open:
            return action == "quit_app"
        # Manual seed drop (q368): reachable from every screen state — panels
        # open, an elaborate row, even an empty inbox — except while typing,
        # where the same physical key must reach the input instead.
        if action in ("drop_seed", "grave", "toggle_field"):
            return not self.free_text_mode
        # Each of the three panel-open keys stays reachable from inside any of
        # the others (`_close_other_panels` makes the switch itself a no-op
        # extra step, not the reader's job to close-then-reopen).
        if self.settings_open:
            return action in ("open_settings", "open_projects", "open_answers", "quit_app")
        if self.projects_open:
            return action in (
                "open_projects", "open_settings", "open_answers",
                "focus_next", "focus_prev", "submit",
                "ignore_project", "activate_project", "poke", "quit_app",
            )
        if self.answers_open:
            return action in (
                "open_answers", "open_projects", "open_settings",
                "focus_next", "focus_prev", "submit",
                "prev_project", "next_project", "quit_app",
            )
        if self.free_text_mode or self.elaborating:
            if action in ("open_projects", "ignore_project", "activate_project", "open_answers"):
                return False
        if action in ("refresh_view", "quit_app", "open_settings", "open_answers", "open_tuning"):
            return True

        q = self._current_question()
        if q is None:
            # Nothing on the rail to act on: navigation between live projects
            # and the two global keys are the only bindings that still mean
            # something on an empty inbox — except `undo`, which is exactly
            # what a human reaches for after clearing the last visible row,
            # the one action that empties the rail in the first place.
            if action in ("prev_project", "next_project"):
                return len(self._live_projects()) > 1
            if action == "undo":
                return bool(self.undo_stack)
            return False

        if q.status == "elaborate":
            # Stopped accepting answers until `edit` addresses the request —
            # only navigation, clearing, undo (withdrawing the request), and
            # poking the owning agent still mean anything here.
            if action in ("view_file", "edit_file", "toggle_preview"):
                return bool(q.files)
            if action == "select_choice":
                return self.file_pending is not None
            return action in (
                "focus_next", "focus_prev", "prev_project", "next_project",
                "clear_focused", "undo", "poke", "visit", "refresh_view", "quit_app",
            )

        if action == "close_row":
            # A finished review or plan closes with `x` (q404); every other
            # row already has `c`/`d`, so the key stays off there.
            return q.act in ("review", "plan") and q.persistent

        always = {
            "focus_next", "focus_prev", "prev_project", "next_project",
            "clear_focused", "skip", "submit", "leave_input",
        }
        if action in always:
            return True
        if action in ("copy_command", "run_command"):
            return bool(self._command_of(q))
        if action == "open_output":
            return bool(self.run_output.get(q.key))
        if action in ("view_file", "edit_file", "toggle_preview"):
            return bool(q.files)
        if action == "dismiss":
            return q.act in ("notify", "data")
        if action == "poke":
            return _pokeable(q)
        if action == "visit":
            return bool(q.pane)
        if action == "undo":
            return bool(self.undo_stack)
        if action in ("elaborate", "decompose"):
            return q.status in ("open", "live")
        if action == "toggle_free_text":
            return bool(q.allow_free)
        if action in ("confirm_yes", "confirm_no"):
            return q.kind == "confirm"
        if action == "select_choice":
            # A digit-prefix armed by `f`/`F` on a multi-file row (q-files)
            # takes every digit, even on a row with no choices of its own.
            if self.file_pending is not None:
                return True
            # Enabled for the whole shape, not the exact digit: a digit past
            # the count still reaches action_select_choice, which flashes
            # rather than looking like a dead key.
            if q.act == "plan":
                return bool(q.steps)
            if q.act == "data":
                return bool(q.choices)
            return q.kind in ("choice", "multi", "confirm")
        return True

    def action_copy_command(self) -> None:
        """Put the focused row's command on the clipboard."""
        from .shell import copy, ShellError

        q = self._current_question()
        if q is None:
            return
        command = self._command_of(q)
        if not command:
            self.flash = f"{q.key} carries no command"
        else:
            try:
                tool = copy(command)
            except ShellError as exc:
                self.flash = f"copy failed: {exc}"
            else:
                self.flash = f"copied to clipboard via {tool}"
        self._rebuild_status_bar()

    def action_run_command(self) -> None:
        """Run the focused row's command in the row's own directory.

        Never on arrival, only on this key: the command is agent-written text
        and the keypress is the authorisation. It runs where the row was
        recorded, not where the reader happens to be looking. On a `run`
        act row this is the same path as approving with y/1 — see
        _run_and_record.
        """
        q = self._current_question()
        if q is None:
            return
        if q.act == "run":
            self._run_and_record(q)
            return
        command = self._command_of(q)
        if not command:
            self.flash = f"{q.key} carries no command"
            self._rebuild_status_bar()
            return
        if self.run_state.get(q.key) == "running":
            self.flash = f"{q.key} is already running"
            self._rebuild_status_bar()
            return
        self.run_output[q.key] = []
        self.run_projects[q.key] = q.project
        self.run_state[q.key] = "running"
        self.flash = f"running in {q.cwd}"
        self._rebuild_status_bar()
        self._redraw_active()
        self._stream_command(q.key, command, q.cwd)

    @work(thread=True)
    def _stream_command(self, key: str, command: str, cwd: str) -> None:
        from .shell import run, ShellError

        try:
            for line in run(command, cwd=cwd):
                self.call_from_thread(self._append_output, key, line)
        except ShellError as exc:
            self.call_from_thread(self._append_output, key, f"— {exc} —")
        self.call_from_thread(self._finish_output, key)

    def _run_and_record(self, q: Question) -> None:
        """Run a `run` act row's command and record the verdict on completion.

        Approving a run row means running it — there is no separate "approve
        without running" — so this is what both `R` and approving y/1 do on a
        run row. A kill or a start-up failure still lands here and still
        records `approve`, with whatever exit code and error line the run
        produced; only `n`/deny skips running altogether.
        """
        command = self._command_of(q)
        if not command:
            self.flash = f"{q.key} carries no command"
            self._rebuild_status_bar()
            return
        if self.run_state.get(q.key) == "running":
            self.flash = f"{q.key} is already running"
            self._rebuild_status_bar()
            return
        self.run_output[q.key] = []
        self.run_projects[q.key] = q.project
        self.run_state[q.key] = "running"
        self.flash = f"running in {q.cwd}"
        self._rebuild_status_bar()
        self._redraw_active()
        self._stream_run_row(q.key, command, q.cwd)

    @work(thread=True)
    def _stream_run_row(self, key: str, command: str, cwd: str) -> None:
        from .shell import run, ShellError

        try:
            for line in run(command, cwd=cwd):
                self.call_from_thread(self._append_output, key, line)
        except ShellError as exc:
            self.call_from_thread(self._append_output, key, f"— {exc} —")
        self.call_from_thread(self._finish_run_row, key)

    def _finish_run_row(self, key: str) -> None:
        """Spill the full capture, record the result, and record approve.

        A `run` row's result has to outlive this process for `get
        --json`/`feed`/the monitor to read it back, not just the card's tail
        — same reason `_finish_output` spills and persists a review row's
        result (q20), but that path stops short of recording an answer.
        """
        from .shell import spill

        lines = self.run_output.get(key) or []
        exit_code = _parse_exit_code(lines)
        last = lines[-1] if lines else ""
        self.run_state[key] = last.strip("— ") if last.startswith("—") else "done"
        log_path = spill(lines, key=key)
        try:
            project = self.run_projects.get(key)
            self.store.set_run_result(
                key, project=project, exit_code=exit_code, tail=lines[-50:], log=str(log_path)
            )
            answered = self.store.answer(key, project=project, selected=["approve"], text=None)
            self._auto_poke_webhook(answered.agent)
        except Exception as exc:
            self.flash = f"{key}: result not recorded: {exc}"
        if self.focused_key == key:
            self._rebuild_card()
            # Prefer auto-poke flash when set; otherwise the approve summary.
            if not (self.flash or "").startswith("answered"):
                self.flash = f"{key}: approved, exit {exit_code}"
            self._rebuild_status_bar()

    def _append_output(self, key: str, line: str) -> None:
        self.run_output.setdefault(key, []).append(line)
        if self.focused_key == key:
            self._rebuild_card()

    def _finish_output(self, key: str) -> None:
        """A review row's `R`: spill, persist the result (q20), never answer it.

        Unlike `_finish_run_row`, this never touches `answer()` — a review's
        pass/fail stays the human's verdict, not something running the
        command decides. The result still has to outlive this process for
        the asking agent's `get --json`/`feed` to read it back, so it is
        spilled and recorded exactly like a `run` row's.
        """
        from .shell import spill

        lines = self.run_output.get(key) or []
        exit_code = _parse_exit_code(lines)
        last = lines[-1] if lines else ""
        self.run_state[key] = last.strip("— ") if last.startswith("—") else "done"
        log_path = spill(lines, key=key)
        try:
            project = self.run_projects.get(key)
            self.store.set_run_result(
                key, project=project, exit_code=exit_code, tail=lines[-50:], log=str(log_path)
            )
        except Exception as exc:
            self.flash = f"{key}: result not recorded: {exc}"
        if self.focused_key == key:
            self._rebuild_card()
            if not (self.flash or "").startswith(f"{key}: result not recorded"):
                self.flash = f"{key}: {self.run_state[key]}"
            self._rebuild_status_bar()

    def action_open_output(self) -> None:
        """Spill the focused row's full capture to a file and name it."""
        from .shell import spill

        q = self._current_question()
        if q is None:
            return
        lines = self.run_output.get(q.key)
        if not lines:
            self.flash = f"{q.key} has no captured output"
        else:
            self.flash = f"full output: {spill(lines, key=q.key)}"
        self._rebuild_status_bar()

    def action_view_file(self) -> None:
        """Preview the focused row's file (q-files) in the human's pager."""
        self._start_file_action("view")

    def action_toggle_preview(self) -> None:
        """Show or hide the inline preview (diff vs HEAD) of the row's files."""
        q = self._current_question()
        if q is None or not q.files:
            return
        self.preview_open = not self.preview_open
        self._rebuild_card()

    def action_edit_file(self) -> None:
        """Open the focused row's file (q-files) in the human's editor."""
        self._start_file_action("edit")

    def _start_file_action(self, mode: str) -> None:
        """Run a single-file row's action immediately, or arm a digit pick.

        A one-file row has nothing to pick, so `f`/`F` runs it straight away.
        A multi-file row instead arms `file_pending` and waits ~1.5s for the
        digit that names which one — `action_select_choice` intercepts it.
        """
        q = self._current_question()
        if q is None or not q.files:
            # check_action/on_key already handle messaging for this case.
            return
        if len(q.files) == 1:
            self._run_file_action(q, mode, 0)
            return
        self.file_pending = mode
        self.file_pending_key = q.key
        self.flash = f"file 1-{len(q.files)}?"
        self.file_pending_timer = self.set_timer(
            1.5, partial(self._disarm_file_pending, q.key)
        )
        self._rebuild_card()

    def _cancel_file_pending(self) -> None:
        """Drop an armed file pick without a flash of its own.

        The caller (a disarming keypress, a row move, a fired pick) is the
        one that knows what flash — if any — belongs on screen next.
        """
        if self.file_pending_timer is not None:
            self.file_pending_timer.stop()
            self.file_pending_timer = None
        self.file_pending = None
        self.file_pending_key = None

    def _disarm_file_pending(self, key: str) -> None:
        """Timer callback: no digit arrived — drop the arm and its flash."""
        if self.file_pending_key != key:
            return
        self._cancel_file_pending()
        self.flash = ""
        self._rebuild_status_bar()
        self._rebuild_card()

    async def _resolve_file_pending(self, n: int) -> None:
        """The digit `f`/`F` armed for — run that file, or flash why not."""
        mode = self.file_pending
        key = self.file_pending_key
        self._cancel_file_pending()
        q = self._current_question()
        if q is None or q.key != key:
            return
        if n < 1 or n > len(q.files):
            self.flash = f"{q.key} has no file {n}"
            self._rebuild_card()
            return
        assert mode is not None
        self._run_file_action(q, mode, n - 1)

    def _run_file_action(self, q: Question, mode: str, idx: int) -> None:
        """View or edit `q.files[idx]` under a suspended screen, and flash the result."""
        from textual.app import SuspendNotSupported

        from .shell import ShellError
        from .shell import edit as shell_edit
        from .shell import view as shell_view

        path = q.files[idx]
        func = shell_view if mode == "view" else shell_edit
        verb = "view" if mode == "view" else "edit"
        try:
            try:
                with self.suspend():
                    ran = func(path)
            except SuspendNotSupported:
                ran = func(path)
        except ShellError as exc:
            self.flash = f"{verb} failed: {exc}"
            self._rebuild_card()
            return
        past = "viewed" if mode == "view" else "edited"
        self.flash = f"{past} {idx + 1}/{len(q.files)} {path} ({ran})"
        self._rebuild_card()

    def _on_record_warning(self, message: str) -> None:
        """Store.record_warning hook: surface a failed record write as a flash."""
        self.flash = message

    async def action_dismiss(self) -> None:
        """Dismiss a notify row — it wanted acknowledgement, not an answer.

        A data row closes the same way `c` does instead: a skipped answer
        would only append an idle verdict on a persistent row, not retire it.
        """
        q = self._current_question()
        if q is None:
            return
        if q.act == "data":
            await self.action_clear_focused()
            return
        if q.act != "notify":
            self.flash = f"{q.key} is act={q.act}, not a dismissable notice"
            self._rebuild_status_bar()
            return
        await self._submit_answer(q, selected=[], text=None, skipped=True, label="dismissed", key="d")

    def _auto_poke_webhook(self, agent: str | None) -> None:
        """After an answer, wake webhook-mapped agents only (never herdr)."""
        from .poke import poke_webhook_if_mapped, PokeError

        try:
            woke = poke_webhook_if_mapped(agent, timeout=5.0)
        except PokeError as exc:
            self.flash = f"answered; webhook poke failed: {exc}"
            return
        if woke:
            self.flash = f"answered; auto-poked {agent}"

    async def action_poke(self) -> None:
        """Nudge the agent that owns the focused row to re-read its feed.

        The nudge carries no instruction. It says the inbox moved and leaves the
        agent to decide what that means, which keeps a human from having to
        compose a prompt and keeps cactus out of driving agents.
        """
        from .poke import poke, PokeError

        if self.projects_open:
            self._poke_project()
            return
        q = self._current_question()
        if q is None:
            return
        if not _pokeable(q):
            # check_action keeps the binding off here; on_key owns the flash.
            return
        else:
            try:
                poke(q.agent, pane=q.pane, timeout=5.0)
            except PokeError as exc:
                self.flash = f"poke failed: {exc}"
            else:
                self.flash = f"poked {q.pane or q.agent}"
        self._rebuild_status_bar()

    def _poke_project(self) -> None:
        """`p` on the projects page: sync message to every herdr pane in the project.

        One poke per distinct pane stamped on the project's open/live/elaborate
        rows; herdr only, so no webhook and no owner-only fallback.
        """
        from .poke import poke, PokeError

        row = self._selected_project_row()
        if row is None:
            return
        label = project_label(row["project"])
        reach = self.store.project_panes(row["project"])
        panes, skipped = reach["panes"], reach["skipped"]
        if not panes:
            self.flash = f"{label}: no herdr panes ({skipped} rows unstamped)"
        else:
            failed = 0
            for entry in panes:
                try:
                    poke(entry["agent"], pane=entry["pane"], message=PROJECT_POKE_MESSAGE,
                         timeout=5.0, webhook=False)
                except PokeError:
                    failed += 1
            noun = "pane" if len(panes) - failed == 1 else "panes"
            self.flash = f"poked {len(panes) - failed} {noun} in {label}"
            if failed:
                self.flash += f" ({failed} failed)"
        self._rebuild_status_bar()

    def action_visit(self) -> None:
        """Jump the herdr view to the pane that asked the focused row."""
        from .poke import visit, PokeError

        q = self._current_question()
        if q is None or not q.pane:
            # check_action keeps the binding off here; on_key owns the flash.
            return
        try:
            visit(q.pane)
        except PokeError as exc:
            self.flash = f"visit failed: {exc}"
        else:
            self.flash = f"visited {q.pane}"
        self._rebuild_status_bar()

    def _rebuild_status_bar(self) -> None:
        bar = self.query_one("#status-bar", Static)
        rows = self.store.projects()
        open_total = sum(r["open_count"] for r in rows)
        live_total = sum(r["live_count"] for r in rows)
        proj_total = sum(1 for r in rows if r["open_count"] > 0 or r["live_count"] > 0)
        mode = "typing — esc to leave" if self.free_text_mode else "ready"
        noun = "project" if proj_total == 1 else "projects"
        counts = f"{open_total} open"
        if live_total:
            counts += f" · {live_total} live"
        undo = ""
        if self.undo_stack:
            last = self.undo_stack[-1]
            undo = f"    {last['label']} {last['key']} · u undo"
        flash = f"    {self.flash}" if self.flash else ""
        bar.update(f"{counts} / {proj_total} {noun}    {mode}{undo}{flash}")
        # The undo binding's availability depends on the stack, which only
        # this method ever changes — refresh here so the footer's `u` tracks
        # it, and rebuild the key bar alongside it for the same reason.
        self._rebuild_keybar()
        self.refresh_bindings()

    def _current_question(self) -> Question | None:
        for q in self.questions:
            if q.key == self.focused_key:
                return q
        return None

    def _default_multi_selection(self, key: str | None) -> set[str]:
        """The set a multi row starts with on arrival: the agent's recommendation, if any.

        So enter alone submits it, and a tap still redirects to anything else.
        """
        q = next((x for x in self.questions if x.key == key), None)
        if q is not None and q.kind == "multi" and q.recommend:
            return set(q.recommend)
        return set()

    def _redraw_active(self) -> None:
        self._rebuild_card()
        q = self._current_question()
        if q is None:
            return
        try:
            row = self.query_one(f"#row-{q.key}", QuestionBlock)
        except Exception:
            return
        row.update(q, active=True, draft=q.key in self.drafts)

    # ---- focus / navigation ------------------------------------------------

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "rail-list" or self._rebuilding:
            return
        item = event.item
        if item is None:
            # Fires as a side effect of clearing the list during a rebuild;
            # it does not represent a real navigation change.
            return
        new_key = getattr(item, "key", None)
        if new_key == self.focused_key:
            return
        prior_key = self.focused_key
        self.focused_key = new_key
        self.multi_selected = self._default_multi_selection(new_key)
        self.free_text_mode = False
        self._cancel_step_buffer()
        self._cancel_file_pending()
        self.preview_open = False
        self._hide_input()
        for key in (prior_key, new_key):
            if key is None:
                continue
            try:
                row = self.query_one(f"#row-{key}", QuestionBlock)
            except Exception:
                continue
            q = next((x for x in self.questions if x.key == key), None)
            if q is not None:
                row.update(q, active=key == new_key, draft=key in self.drafts)
        self._rebuild_card()
        self._sync_input_focus()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        # ListView consumes `enter` before the app binding can see it, so the
        # selection event is where submit has to be triggered from.
        if event.list_view.id != "rail-list":
            return
        await self.action_submit()

    def _clear_flash(self) -> None:
        if self.flash:
            self.flash = ""
            self._rebuild_status_bar()

    async def on_event(self, event: events.Event) -> None:
        # Every keypress retires the previous flash, not only the ones that
        # move the row — a stale "poke failed" otherwise lingers under a
        # completely unrelated action until the next j/k. Runs ahead of
        # binding dispatch, so an action fired by this same key still gets
        # to set its own fresh flash afterwards.
        if isinstance(event, events.Key):
            # Any key that is not itself extending the buffer abandons it —
            # a row move, a mode switch, or an unrelated action must not
            # leave a stale digit waiting to fire against a different row.
            if self._step_buffer and not (len(event.key) == 1 and event.key.isdigit()):
                self._cancel_step_buffer()
            if self.file_pending is not None and not (len(event.key) == 1 and event.key.isdigit()):
                self._cancel_file_pending()
                self._rebuild_card()
            if not self.free_text_mode and not self.elaborating:
                self._clear_flash()
        await super().on_event(event)

    async def on_key(self, event: events.Key) -> None:
        """Catch keys check_action disables, so a press still gets a one-line answer.

        The footer hides `u` when the undo stack is empty — a key that cannot
        do anything should not be advertised — but that same gate stops the
        binding from firing, so the press would otherwise land in silence.
        This runs after bindings, so an enabled `u`/`y`/`n` never reaches here.
        """
        if self.tuning_open:
            if self.tuning_name_slot is not None:
                n = self.tuning_name_slot
                if event.key == "escape":
                    self.tuning_name_slot = None
                    self.tuning_name_buf = ""
                    self.flash = "save cancelled"
                elif event.key == "enter":
                    name = self.tuning_name_buf.strip() or None
                    self.world.sky.config.save_slot(n, name=name)
                    self.flash = f"saved slot {n} as {name}" if name else f"saved slot {n}"
                    self.tuning_name_slot = None
                    self.tuning_name_buf = ""
                elif event.key == "backspace":
                    self.tuning_name_buf = self.tuning_name_buf[:-1]
                elif event.character and event.is_printable and len(self.tuning_name_buf) < 40:
                    self.tuning_name_buf += event.character
                self._render_tuning()
                self._rebuild_status_bar()
                event.stop()
                return
            if self.tuning_save_armed:
                if event.key == "escape":
                    self.tuning_save_armed = False
                    self.flash = "save cancelled"
                    self._render_tuning()
                    self._rebuild_status_bar()
                    event.stop()
                    return
                if event.key.isdigit() and event.key != "0":
                    n = int(event.key)
                    self.tuning_save_armed = False
                    existing = sky_slots().get(n) or ""
                    self.tuning_name_slot = n
                    self.tuning_name_buf = existing
                    self._render_tuning()
                    self._rebuild_status_bar()
                    event.stop()
                    return
                self.tuning_save_armed = False
                self._render_tuning()
                self._rebuild_status_bar()
                # fall through: this key still does its own thing below
            if event.key in ("escape", "T"):
                self._close_tuning()
            elif event.key in ("j", "down"):
                self._move_tuning_cursor(1)
            elif event.key in ("k", "up"):
                self._move_tuning_cursor(-1)
            elif event.key in ("tab", "right_square_bracket"):
                self._switch_tuning_panel(1)
            elif event.key in ("shift+tab", "left_square_bracket"):
                self._switch_tuning_panel(-1)
            elif event.key in ("h", "left"):
                self._nudge_tuning(-1)
            elif event.key in ("l", "right"):
                self._nudge_tuning(1)
            elif event.key in ("H", "shift+left"):
                self._nudge_tuning(-10)
            elif event.key in ("L", "shift+right"):
                self._nudge_tuning(10)
            elif event.key == "r":
                self._reset_tuning()
            elif event.key == "S":
                self.tuning_save_armed = True
                self.flash = "save to slot 1-9?"
                self._render_tuning()
                self._rebuild_status_bar()
            elif event.key.isdigit() and event.key != "0":
                n = int(event.key)
                cfg = SkyConfig.load_slot(n)
                if cfg is None:
                    self.flash = f"slot {n} is empty"
                    self._rebuild_status_bar()
                else:
                    self.world.apply_sky_config(cfg)
                    self._apply_and_dump_tuning()
                    name = sky_slots().get(n)
                    self.flash = f"recalled slot {n}: {name}" if name else f"recalled slot {n}"
                    self._render_tuning()
                    self._rebuild_status_bar()
            else:
                return
            event.stop()
            return
        if self.projects_open:
            if event.key == "escape":
                self._close_projects()
                event.stop()
            return
        if self.answers_open:
            if event.key == "escape":
                self._close_answers()
                event.stop()
            return
        if self.settings_open:
            if event.key == "escape":
                self._close_settings()
            elif event.key == "1":
                self._set_orientation("side")
            elif event.key == "2":
                self._set_orientation("bottom")
            elif event.key == "3":
                self._toggle_projects_pane()
            elif event.key == "4":
                self._toggle_seed_release()
            elif event.key == "5":
                self._cycle_keybar_align()
            elif event.key == "f":
                self._toggle_figlet_header()
            else:
                return
            event.stop()
            return
        if self.free_text_mode or self.elaborating:
            return
        if event.key == "u" and not self.undo_stack:
            self.flash = "nothing to undo"
            self._rebuild_status_bar()
            event.stop()
            return
        if event.key in ("y", "n"):
            # confirm_yes/confirm_no only bind on a confirm row (check_action);
            # a plan or text row otherwise ate the key in silence.
            q = self._current_question()
            if q is not None and q.kind != "confirm":
                # The act, not the kind — "q1 is act='plan'" says what the row
                # is for; "q1 is text" only names the shape of its answer.
                self.flash = f"y/n only answer a confirm row — {q.key} is act='{q.act}'"
                self._rebuild_status_bar()
                event.stop()
            return
        if event.key.isdigit():
            # `0` has no binding at all, and 1-9 fall through here only when
            # check_action disabled select_choice (a plan with no steps yet) —
            # an enabled digit never reaches this handler at all.
            q = self._current_question()
            if q is not None and q.act == "plan":
                if q.steps and event.key == "0":
                    # `0` never starts a buffer (no step is numbered 0), but
                    # it can still be the second digit of a buffered ten,
                    # twenty, etc. — same two-digit resolution as any other
                    # second digit.
                    if self._step_buffer and self._step_buffer_key == q.key:
                        buffer = self._step_buffer + "0"
                        self._cancel_step_buffer()
                        await self._resolve_step_buffer(q, buffer)
                    else:
                        self.flash = f"{q.key} has no step 0"
                        self._rebuild_status_bar()
                    event.stop()
                    return
                self.flash = (
                    f"{q.key} has no steps yet" if not q.steps
                    else f"{q.key} has no step {event.key}"
                )
                self._rebuild_status_bar()
                event.stop()
            return
        if event.key == "p":
            # poke only binds on a row with an owner and herdr stamps
            # (check_action); a row posted outside herdr otherwise ate the key.
            q = self._current_question()
            if q is not None and not _pokeable(q):
                self.flash = (
                    f"{q.key} has no agent to poke" if not q.agent
                    else f"{q.key} was posted outside herdr; nothing to poke"
                )
                self._rebuild_status_bar()
                event.stop()
        if event.key == "v":
            # visit only binds on a row with a herdr pane stamp (check_action).
            q = self._current_question()
            if q is not None and not q.pane:
                self.flash = f"{q.key} was posted outside herdr; nothing to visit"
                self._rebuild_status_bar()
                event.stop()
        if event.key == "x":
            q = self._current_question()
            if q is not None and q.act not in ("review", "plan"):
                self.flash = f"x closes review/plan rows — {q.key} is act='{q.act}'; c clears it"
                self._rebuild_status_bar()
                event.stop()
        if event.key in ("f", "F", "o"):
            # view/edit/preview only bind on a row carrying files (check_action).
            q = self._current_question()
            if q is not None and not q.files:
                self.flash = f"{q.key} carries no file"
                self._rebuild_status_bar()
                event.stop()

    def action_focus_next(self) -> None:
        if self.projects_open:
            if self.project_rows:
                self.project_index = (self.project_index + 1) % len(self.project_rows)
                self._render_projects()
            return
        if self.answers_open:
            if self.answers_rows:
                self.answers_index = (self.answers_index + 1) % len(self.answers_rows)
                self.answers_expanded = False
                self._redraw_answers()
            return
        self._clear_flash()
        if self._rebuilding:
            self._rebuild_move += 1
            return
        listview = self.query_one("#rail-list", ListView)
        listview.focus()
        listview.action_cursor_down()

    def action_focus_prev(self) -> None:
        if self.projects_open:
            if self.project_rows:
                self.project_index = (self.project_index - 1) % len(self.project_rows)
                self._render_projects()
            return
        if self.answers_open:
            if self.answers_rows:
                self.answers_index = (self.answers_index - 1) % len(self.answers_rows)
                self.answers_expanded = False
                self._redraw_answers()
            return
        self._clear_flash()
        if self._rebuilding:
            self._rebuild_move -= 1
            return
        listview = self.query_one("#rail-list", ListView)
        listview.focus()
        listview.action_cursor_up()

    async def action_prev_project(self) -> None:
        if self.answers_open:
            await self._rotate_answers_project(-1)
            return
        await self._switch_project(-1)

    async def action_next_project(self) -> None:
        if self.answers_open:
            await self._rotate_answers_project(1)
            return
        await self._switch_project(1)

    async def _rotate_answers_project(self, step: int) -> None:
        """`[`/`]` while the answers view is open: switch which project's history shows.

        Rotates over every known project, not just the live ones — a
        drained project's history is exactly what this view is for.
        """
        if self.scoped_project is not None:
            return
        names = [r["project"] for r in self.store.projects()]
        if not names:
            return
        try:
            idx = names.index(self.current_project)
        except ValueError:
            idx = -1 if step > 0 else 0
        self.current_project = names[(idx + step) % len(names)]
        self._render_answers()

    async def _switch_project(self, step: int) -> None:
        if self.scoped_project is not None:
            return
        names = self._live_projects()
        if not names:
            return
        try:
            idx = names.index(self.current_project)
        except ValueError:
            # Current project drained out of the rotation; step from its edge.
            idx = -1 if step > 0 else 0
        self.current_project = names[(idx + step) % len(names)]
        self.focused_key = None
        self.multi_selected = set()
        self.free_text_mode = False
        self.elaborating = False
        self._hide_input()
        await self._reload(force=True)
        self._sync_input_focus()

    # ---- input handling -----------------------------------------------

    def _focus_input(self) -> None:
        q = self._current_question()
        inp = self.query_one("#answer-input", Input)
        inp.placeholder = (
            "answer — enter to submit" if q is not None and q.kind == "text"
            else "free text — enter to attach"
        )
        inp.display = True
        inp.focus()

    def _hide_input(self) -> None:
        inp = self.query_one("#answer-input", Input)
        inp.value = ""
        inp.display = False

    def _sync_input_focus(self) -> None:
        """Typing is always an explicit mode.

        Auto-focusing the input on arrival at a text question silently retargets
        every key: j, k, s, c and the project brackets get typed instead of acted
        on, and the human only finds out when they read back what they sent.
        """
        q = self._current_question()
        if q is None or q.key == self._synced_key:
            return
        self._synced_key = q.key
        if not self.free_text_mode:
            self.query_one("#rail-list", ListView).focus()

    def action_toggle_free_text(self) -> None:
        q = self._current_question()
        if q is None or not q.allow_free:
            return
        if q.kind == "text":
            inp = self.query_one("#answer-input", Input)
            if not inp.display:
                inp.value = self.pending_text
            self.free_text_mode = True
            self._clear_flash()
            self._focus_input()
            return
        self.free_text_mode = not self.free_text_mode
        if self.free_text_mode:
            inp = self.query_one("#answer-input", Input)
            inp.value = self.pending_text
            self._clear_flash()
            self._focus_input()
        else:
            self._hide_input()
            self.query_one("#rail-list", ListView).focus()
        self._rebuild_status_bar()

    def action_elaborate(self) -> None:
        """`e`: open the input under the `elaborate:` prompt (q212).

        Enter (with or without text) submits the request; escape cancels —
        both routed through `elaborating`, the same way `free_text_mode`
        routes a plain free-text answer.
        """
        q = self._current_question()
        if q is None or q.status not in ("open", "live"):
            return
        self.elaborating = True
        inp = self.query_one("#answer-input", Input)
        inp.value = ""
        inp.placeholder = "elaborate: — enter to send, esc to cancel"
        inp.display = True
        inp.focus()

    async def action_decompose(self) -> None:
        """`D`: ask the owner to split a complex row via elaborate workflow."""
        q = self._current_question()
        if q is None or q.status not in ("open", "live"):
            return
        await self._submit_elaborate(q, DECOMPOSE_INSTRUCTION.format(key=q.key))

    async def _submit_elaborate(self, q: Question, hint: str) -> None:
        try:
            self.store.elaborate_request(q.key, hint=hint or None, project=q.project)
        except (KeyError, ValueError) as exc:
            self.flash = str(exc)
        else:
            self.flash = f"{q.key} — elaborate requested"
        self.elaborating = False
        self._hide_input()
        await self._reload(force=True)
        self._synced_key = None
        self._sync_input_focus()
        self.query_one("#rail-list", ListView).focus()
        self._rebuild_status_bar()

    async def _withdraw_elaborate(self, q: Question) -> None:
        try:
            self.store.unelaborate(q.key, project=q.project)
        except (KeyError, ValueError) as exc:
            self.flash = str(exc)
        else:
            self.flash = f"{q.key} — elaborate request withdrawn"
        await self._reload(force=True)
        self._rebuild_status_bar()

    def action_leave_input(self) -> None:
        if self.elaborating:
            self.elaborating = False
            self._hide_input()
            self._redraw_active()
            self._rebuild_status_bar()
            self.query_one("#rail-list", ListView).focus()
            return
        q = self._current_question()
        self.free_text_mode = False
        if q is not None:
            # Keep what was typed: escape is for reaching the queue keys, not a discard.
            inp = self.query_one("#answer-input", Input)
            self.pending_text = inp.value.strip()
            inp.display = False
        else:
            self._hide_input()
        self._redraw_active()
        self._rebuild_status_bar()
        self.query_one("#rail-list", ListView).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        q = self._current_question()
        if q is None:
            return
        value = event.value.strip()
        if self.elaborating:
            await self._submit_elaborate(q, value)
            return
        if q.act == "plan":
            await self._submit_plan(q, typed=value)
            return
        if q.act == "data":
            await self._submit_data(q, typed=value)
            return
        if q.act == "review":
            await self._submit_review(q, typed=value)
            return
        if q.kind == "text":
            if not value:
                self.flash = "empty — type an answer, or esc then s to skip"
                self._rebuild_status_bar()
                return
            await self._submit_answer(q, selected=[], text=value)
            return
        # Free text on a question that also takes a pick: park it on the card so
        # the human can see what will be sent, then hand focus back to the queue.
        self.pending_text = value
        self.free_text_mode = False
        self.query_one("#answer-input", Input).display = False
        self._redraw_active()
        self._rebuild_status_bar()
        self.query_one("#rail-list", ListView).focus()

    # ---- answering ----------------------------------------------------

    async def action_select_choice(self, n: int) -> None:
        if self.file_pending is not None:
            await self._resolve_file_pending(n)
            return
        plan = self._current_question()
        if plan is not None and plan.act == "plan" and plan.steps:
            await self._handle_step_digit(plan, n)
            return
        q = self._current_question()
        if q is None:
            return
        if q.act == "data":
            if n < 1 or n > len(q.choices):
                self.flash = f"{q.key} has no chunk {n}"
                self._rebuild_status_bar()
                return
            from .shell import copy, ShellError

            choice = q.choices[n - 1]
            try:
                tool = copy(choice.description)
            except ShellError as exc:
                self.flash = f"copy failed: {exc}"
                self._rebuild_status_bar()
                return
            await self._submit_answer(q, selected=[choice.label], text=None, key=str(n))
            self.flash = f"copied {n}) {choice.label} via {tool}"
            self._rebuild_status_bar()
            return
        if q.kind not in ("choice", "multi", "confirm"):
            return
        if q.kind == "confirm":
            # The digits pick a confirm the same way they pick a choice, so the
            # hand never has to learn two schemes for the same shape of answer.
            labels = [c.label for c in q.choices] or ["yes", "no"]
            if n < 1 or n > len(labels):
                self.flash = f"{q.key} has no choice {n}"
                self._rebuild_status_bar()
                return
            await self._confirm(n - 1, key=str(n))
            return
        if n < 1 or n > len(q.choices):
            self.flash = f"{q.key} has no choice {n}"
            self._rebuild_status_bar()
            return
        label = q.choices[n - 1].label
        if q.kind == "choice":
            await self._submit_answer(q, selected=[label], text=self.pending_text or None, key=str(n))
        else:
            if label in self.multi_selected:
                self.multi_selected.discard(label)
            else:
                self.multi_selected.add(label)
            self._redraw_active()

    def _cancel_step_buffer(self) -> None:
        """Drop a pending step digit without firing it — no flash of its own.

        The caller (a cancelling keypress, a row move, undo) is the one that
        knows what flash — if any — belongs on screen next.
        """
        if self._step_buffer_timer is not None:
            self._step_buffer_timer.stop()
            self._step_buffer_timer = None
        self._step_buffer = ""
        self._step_buffer_key = None

    async def _handle_step_digit(self, plan: Question, n: int) -> None:
        """Buffer a plan-row digit so a step past 9 is still reachable (q16).

        A plan with 9 or fewer steps can never have a two-digit step number,
        so every digit is unambiguous and fires the same instant it always
        did. Past 9 steps, "1" might be step 1 or the start of "12" — so it
        waits ~0.5s for a possible second digit, unless no second digit could
        keep it in range (or one is already buffered, since a step number is
        never more than two digits here), in which case it fires at once.
        """
        max_step = len(plan.steps)
        d = str(n)
        if self._step_buffer and self._step_buffer_key == plan.key:
            # Second digit: always final, matching the two-digit cap.
            buffer = self._step_buffer + d
            self._cancel_step_buffer()
            await self._resolve_step_buffer(plan, buffer)
            return
        if int(d + "0") <= max_step:
            self._step_buffer = d
            self._step_buffer_key = plan.key
            self.flash = f"step {d}…"
            self._step_buffer_timer = self.set_timer(
                0.5, partial(self._fire_step_buffer, plan.key)
            )
            self._rebuild_status_bar()
            return
        await self._resolve_step_buffer(plan, d)

    async def _fire_step_buffer(self, key: str) -> None:
        """Timer callback: the human stopped at one digit — resolve it."""
        if self._step_buffer_key != key or not self._step_buffer:
            return
        buffer = self._step_buffer
        self._cancel_step_buffer()
        plan = self._current_question()
        if plan is None or plan.key != key or plan.act != "plan":
            return
        await self._resolve_step_buffer(plan, buffer)

    async def _resolve_step_buffer(self, plan: Question, buffer: str) -> None:
        """Toggle the step the buffered digits name, or flash why not."""
        n = int(buffer)
        idx = n - 1
        step = next((st for st in plan.steps if st.idx == idx), None)
        if step is None:
            self.flash = f"{plan.key} has no step {n}"
        else:
            prior_done = step.done
            self.store.set_step_done(plan.key, idx, not prior_done, project=plan.project)
            self._push_step_undo(plan.key, idx, prior_done, project=plan.project)
            self.flash = f"step {n} {'done' if not prior_done else 'reopened'}"
        await self.action_refresh_view()
        self._rebuild_status_bar()

    async def action_submit(self) -> None:
        if self.projects_open:
            row = self._selected_project_row()
            if row is None:
                return
            self.current_project = row["project"]
            self.focused_key = None
            self._close_projects()
            await self._reload(force=True)
            return
        if self.answers_open:
            self.answers_expanded = not self.answers_expanded
            self._redraw_answers()
            return
        q = self._current_question()
        if q is None:
            return
        if q.act == "plan":
            if self.pending_text:
                await self._submit_plan(q)
            else:
                # No draft yet: enter opens typing, same as `i` — so the
                # card's "enter to type" hint is true and the first
                # keystrokes are never lost to a flash instead.
                self.action_toggle_free_text()
            return
        if q.act == "data":
            await self._submit_data(q)
            return
        if q.kind == "multi":
            if not self.multi_selected and not self.pending_text:
                self.flash = "pick at least one, or s to skip"
                self._rebuild_status_bar()
                return
            await self._submit_answer(
                q, selected=sorted(self.multi_selected), text=self.pending_text or None, key="enter",
            )
        elif q.kind == "text":
            inp = self.query_one("#answer-input", Input)
            if not inp.display:
                inp.value = self.pending_text
            self.free_text_mode = True
            self._focus_input()
        elif self.pending_text:
            # Choice and confirm normally need a pick, but typed text is a
            # complete answer on its own when the question allows free entry.
            await self._submit_answer(q, selected=[], text=self.pending_text, key="enter")
        elif q.recommend:
            # No pick and no typed text: enter submits the agent's own
            # recommendation. It is advisory, not a `chosen` that already
            # proceeded — this tap is what confirms it.
            await self._submit_answer(q, selected=list(q.recommend), text=None, key="enter")
        elif q.kind in ("choice", "confirm"):
            self.flash = self._pick_hint(q)
            self._rebuild_status_bar()

    async def _submit_plan(self, q: Question, typed: str | None = None) -> None:
        """Typed text plus enter records a verdict; it never closes the row.

        `typed` carries the Input widget's own value when this fires from
        `on_input_submitted` (the row wasn't focused there yet, so the pending
        draft cannot be trusted); the rail's enter falls back to the draft — and
        only reaches here with a draft already set (see `action_submit`, which
        opens the input instead of calling this on an empty one). Closing is
        `c`'s job — see the CLAUDE.md invariant this file keeps.
        """
        text = (typed if typed is not None else self.pending_text).strip()
        if not text:
            self.flash = "empty — type an answer, or esc then s to skip"
            self._rebuild_status_bar()
            return
        try:
            self.store.answer(q.key, project=q.project, selected=[], text=text, skipped=False)
        except (KeyError, ValueError) as exc:
            await self._refuse(exc)
            return
        self._auto_poke_webhook(q.agent)
        self._push_undo(q.key, "noted", [], text, project=q.project)
        self._field_drop("enter")
        self.pending_text = ""
        self.free_text_mode = False
        self._hide_input()
        # Distinct from the undo indicator's own "noted" label, so the status
        # bar never doubles the same word.
        self.flash = "verdict recorded"
        self._redraw_active()
        self._rebuild_status_bar()
        self.query_one("#rail-list", ListView).focus()

    async def _submit_review(self, q: Question, typed: str | None = None) -> None:
        """Typed text plus enter records a text-only verdict, same as a plan row's.

        A review's kind is `confirm` (pass/fail), so without this it fell
        through `on_input_submitted`'s generic park-then-second-enter path —
        `cactus answer qN "text"` already accepts text alone on a review row;
        this makes the TUI's enter do the same in one keystroke.
        """
        text = (typed if typed is not None else self.pending_text).strip()
        if not text:
            self.flash = "empty — type an answer, or esc then s to skip"
            self._rebuild_status_bar()
            return
        try:
            self.store.answer(q.key, project=q.project, selected=[], text=text, skipped=False)
        except (KeyError, ValueError) as exc:
            await self._refuse(exc)
            return
        self._auto_poke_webhook(q.agent)
        self._push_undo(q.key, "noted", [], text, project=q.project)
        self._field_drop("enter")
        self.pending_text = ""
        self.free_text_mode = False
        self._hide_input()
        self.flash = "verdict recorded"
        self._redraw_active()
        self._rebuild_status_bar()
        self.query_one("#rail-list", ListView).focus()

    async def _submit_data(self, q: Question, typed: str | None = None) -> None:
        """Enter on a data row: typed text is a verdict, same as a plan row's.

        Digits are how a data row is normally worked (copy a chunk); enter with
        no typed text records nothing and just points back at the digits.
        """
        text = (typed if typed is not None else self.pending_text).strip()
        if text:
            try:
                self.store.answer(q.key, project=q.project, selected=[], text=text, skipped=False)
            except (KeyError, ValueError) as exc:
                await self._refuse(exc)
                return
            self._auto_poke_webhook(q.agent)
            self._push_undo(q.key, "noted", [], text, project=q.project)
            self._field_drop("1")
            self.pending_text = ""
            self.free_text_mode = False
            self._hide_input()
            # Distinct from the undo indicator's own "noted" label, so the
            # status bar never doubles the same word.
            self.flash = "verdict recorded"
            self._redraw_active()
            self._rebuild_status_bar()
            self.query_one("#rail-list", ListView).focus()
            return
        self.flash = f"{_digit_range(len(q.choices))} copies a chunk"
        self._rebuild_status_bar()

    def _pick_hint(self, q: Question) -> str:
        """What enter means with no draft on a choice/confirm row, in its own keys."""
        if q.kind == "confirm":
            return f"pick with y/n or {_digit_range(len(q.choices) or 2)}"
        return f"pick with {_digit_range(len(q.choices))}"

    async def action_confirm_yes(self) -> None:
        await self._confirm(0, key="y")

    async def action_confirm_no(self) -> None:
        await self._confirm(1, key="n")

    async def _confirm(self, index: int, *, key: str = "y") -> None:
        q = self._current_question()
        if q is None or q.kind != "confirm":
            return
        labels = [c.label for c in q.choices] or ["yes", "no"]
        if index < 0 or index >= len(labels):
            return
        label = labels[index]
        if q.act == "run" and label == "approve":
            # Approving a run row means running it: the answer is recorded
            # once the command finishes, alongside its result, not on this
            # keypress — see _run_and_record.
            self._run_and_record(q)
            return
        await self._submit_answer(q, selected=[label], text=self.pending_text or None, key=key)

    async def action_skip(self) -> None:
        q = self._current_question()
        if q is None:
            return
        await self._submit_answer(q, selected=[], text=None, skipped=True, key="s")

    async def action_close_row(self) -> None:
        """`x`: close a review/plan row — the same store call and undo as `c`."""
        await self.action_clear_focused()

    async def action_clear_focused(self) -> None:
        q = self._current_question()
        if q is None:
            return
        self.store.clear(keys=[q.key], project=q.project)
        self._push_undo(q.key, "cleared", [], self.pending_text or None, project=q.project)
        await self._advance_after(q.key)

    async def _submit_answer(
        self,
        q: Question,
        *,
        selected: list[str],
        text: str | None,
        skipped: bool = False,
        label: str | None = None,
        key: str = "i",
    ) -> None:
        try:
            self.store.answer(q.key, project=q.project, selected=selected, text=text, skipped=skipped)
        except KeyError:
            return
        except (AlreadyAnswered, ValueError) as exc:
            await self._refuse(exc)
            return
        self._auto_poke_webhook(q.agent)
        self._push_undo(q.key, label or ("skipped" if skipped else "answered"), selected, text,
                        project=q.project)
        self._field_drop(key)
        await self._advance_after(q.key)

    async def _refuse(self, exc: Exception) -> None:
        """Flash a store refusal instead of letting it crash the app.

        Another surface can answer, clear, or purge a row between this app's
        polls, so the row on screen may be stale: reload before flashing.
        """
        await self._reload(force=True)
        self.flash = str(exc).strip("'\"")
        self._rebuild_status_bar()

    async def _advance_after(self, answered_key: str) -> None:
        old_index = 0
        for i, q in enumerate(self.questions):
            if q.key == answered_key:
                old_index = i
                break
        self.multi_selected = set()
        self.drafts.pop(answered_key, None)
        self.free_text_mode = False
        self._hide_input()
        async with self._reload_lock:
            self._load_questions()
            self.last_cursor = self.store.cursor()
            if self.questions:
                next_index = min(old_index, len(self.questions) - 1)
                self.focused_key = self.questions[next_index].key
                self.multi_selected = self._default_multi_selection(self.focused_key)
            else:
                self.focused_key = None
            self._rebuild_project_head()
            await self._rebuild_rail_locked()
        if self._reload_pending:
            await self._reload()
        self._rebuild_card()
        self._rebuild_status_bar()
        self._synced_key = None
        self._sync_input_focus()

    # ---- field ----------------------------------------------------------

    def action_drop_seed(self) -> None:
        """Backtick/tilde (q368): drop a seed at a random column, any time
        outside free-text mode — no answer recorded, nothing else changes."""
        self.world.drop(self.world.rng.randrange(self.world.cols))
        self._render_field()

    def action_grave(self) -> None:
        """The bare backtick: drop a seed while the field is shown, or flip
        `pile_only` while it is hidden — one action either way, so the
        Binding stays one entry."""
        if self.tui_settings["field"]:
            self.action_drop_seed()
            return
        self.tui_settings["pile_only"] = not self.tui_settings["pile_only"]
        self._save_settings()
        self._apply_tui_settings()
        self.flash = "pile shown" if self.tui_settings["pile_only"] else "pile hidden"
        self._rebuild_status_bar()

    def action_toggle_field(self) -> None:
        """Tilde: show or hide the field strip, giving the card the room
        back when hidden. Persisted like every other TUI setting."""
        self.tui_settings["field"] = not self.tui_settings["field"]
        self._save_settings()
        self._apply_tui_settings()
        self.flash = "garden shown" if self.tui_settings["field"] else "garden hidden"
        self._rebuild_status_bar()

    def _field_column(self, key: str) -> int:
        """Resolve the drop column for a key via its own key bar glyph's x.

        `self._keybar_x` (rebuilt on every `_rebuild_keybar`) already counts
        the bar's alignment pad and gutter from the card's left edge, which
        the field shares, so it is the field column directly — each digit now has its own column, not one
        shared "1" slot. `enter` falls back to `i`'s column when the row has
        no "enter" item of its own (a plan or review row, say), since that is
        where its typing began. Falls back to a column chosen uniformly at
        random when neither is on the bar, e.g. the key bar is not mounted
        yet, or the row offers neither key at all. `seed_release == "right"`
        mirrors a key's column across the field (`width - 1 - col`), so the
        pile builds on the right while the bar stays where it is.
        """
        try:
            pane_cols = max(self.query_one("#field", FieldView).size.width, 1)
        except NoMatches:
            return 0
        col = self._keybar_x.get(key)
        if col is None and key == "enter":
            col = self._keybar_x.get("i")
        if col is None:
            return random.randrange(pane_cols)
        col = max(0, min(col, pane_cols - 1))
        if self.tui_settings["seed_release"] == "right":
            col = pane_cols - 1 - col
        return col

    def _field_drop(self, key: str) -> None:
        """Drop a seed for the column named by `key`.

        Several seeds may be in flight at once; there is no queue — the sky
        timer (started in `on_mount`) keeps ticking whether or not one is
        falling.
        """
        self.world.drop(self._field_column(key))
        self._render_field()

    SKY_RELOAD_SECONDS = 2.0

    def _sync_field_interval(self) -> None:
        """(Re)start `_field_timer` at `1 / fps` (v6f) if `fps` has actually
        changed since the timer was last started — a no-op restart on every
        unrelated tuning nudge would otherwise briefly stall the field.
        `advance(dt)` still measures true elapsed wall time, so this only
        changes how often a frame is sampled and drawn, never how fast the
        sky or a falling seed moves."""
        interval = 1.0 / max(self.world.sky.config.fps, 1)
        if self._field_timer is not None and interval == self._field_interval:
            return
        if self._field_timer is not None:
            self._field_timer.stop()
        self._field_interval = interval
        self._field_timer = self.set_interval(interval, self._field_tick, name="field")

    def _field_tick(self) -> None:
        """One frame: `dt` is the real elapsed time since the last call,
        clamped so a stalled terminal (a suspended session, a slow poll)
        never makes the field jump — never exactly `TICK_SECONDS`, which is
        only this timer's sampling rate, not the physics' own step size."""
        now = time.monotonic()
        last = self._field_last_time if self._field_last_time is not None else now
        dt = min(max(now - last, 0.0), FIELD_MAX_DT)
        self._field_last_time = now
        self.world.advance(dt)
        if self.world.landed_since_save > 0:
            self._save_garden()
        if self._sky_reload_last is None or now - self._sky_reload_last >= self.SKY_RELOAD_SECONDS:
            self._sky_reload_last = now
            self._reload_sky_config()
            self._reload_garden_if_changed()
        self._render_field()

    def _reload_sky_config(self, *, initial: bool = False) -> None:
        """Best-effort: a missing file is the defaults, a bad file keeps the
        config already running and flashes why instead of raising."""
        path = sky_config_path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if not initial and mtime == self._sky_config_mtime:
            return
        self._sky_config_mtime = mtime
        try:
            config = SkyConfig.load(path)
        except ValueError as exc:
            self.flash = f"sky config: {exc}"
            self._rebuild_status_bar()
            return
        self.world.apply_sky_config(config)
        self._sync_field_interval()
        if not initial:
            self.flash = "sky config reloaded"
            self._rebuild_status_bar()

    def _load_garden(self) -> None:
        """The garden (shared landed pile) is a file beside the database, not
        a per-process default — every TUI on this database reads the same
        one. A missing file leaves the world's fresh, empty pile as-is; a
        malformed one flashes and is otherwise ignored."""
        try:
            mtime = self._garden_path.stat().st_mtime
        except OSError:
            return
        data = garden.read(self._garden_path)
        if data is None:
            return
        try:
            garden.load_into(self.world, data)
        except ValueError:
            self.flash = "garden.json unreadable"
            self._rebuild_status_bar()
            return
        self._garden_mtime = mtime

    def _save_garden(self) -> None:
        """Flush landings since the last save (`World.landed_since_save`) to
        the shared garden file. Fails soft: a write error leaves the counter
        alone so the next tick retries."""
        try:
            self._garden_mtime = garden.save(self.world, self._garden_path)
        except OSError:
            return
        self.world.landed_since_save = 0

    def _reload_garden_if_changed(self) -> None:
        """Another TUI on this database may have written a newer garden —
        polled at the same `SKY_RELOAD_SECONDS` cadence as the sky config,
        one clock for both. Fails soft on OSError."""
        try:
            mtime = self._garden_path.stat().st_mtime
        except OSError:
            return
        if mtime == self._garden_mtime:
            return
        data = garden.read(self._garden_path)
        if data is None:
            return
        try:
            garden.load_into(self.world, data)
        except ValueError:
            self.flash = "garden.json unreadable"
            self._rebuild_status_bar()
            return
        self._garden_mtime = mtime
        self.flash = "garden updated"
        self._rebuild_status_bar()

    def on_resize(self, event: events.Resize) -> None:
        """A terminal resize re-fits the field once the layout settles; a
        hidden field gets no Resize of its own to do it."""
        self.call_after_refresh(self._render_field)

    def on_unmount(self) -> None:
        if self._field_timer is not None:
            self._field_timer.stop()
            self._field_timer = None

    def _render_field(self) -> None:
        try:
            widget = self.query_one("#field", FieldView)
        except NoMatches:
            if self._field_timer is not None:
                self._field_timer.stop()
                self._field_timer = None
            return
        # Every draw re-fits first, so the timer is the backstop for any
        # layout change no event reached (a hidden field gets no Resize).
        self._fit_field()
        if not widget.display:
            return  # hidden by the setting or by the card — nothing to draw
        if widget.size.height == 0:
            return  # just shown, not laid out yet; its Resize draws it
        pile_only = not self.tui_settings["field"] and self.tui_settings["pile_only"]
        width = max(widget.size.width, 1)
        height = max(widget.size.height, 1)
        if width != self.world.cols or height != self.world.rows:
            self.world.resize(width, height)
        text = self.world.render(pile_only=pile_only)
        # Change-only redraw (v6f, perf): a still sky between two samples at
        # a low `fps` is common, and Textual's own `update` still triggers a
        # layout/paint even when nothing changed — skip it when this frame's
        # plain text and spans are identical to the last one drawn.
        signature = (text.plain, text.spans)
        if signature == self._field_last_signature:
            return
        self._field_last_signature = signature
        widget.update(text)

    # ---- undo -----------------------------------------------------------

    def _push_undo(
        self, key: str, label: str, selected: list[str], text: str | None,
        *, project: str,
    ) -> None:
        self.undo_stack.append(
            {"key": key, "project": project, "label": label, "kind": "answer",
             "selected": list(selected), "text": text or ""}
        )

    def _push_step_undo(self, key: str, idx: int, prior_done: bool, *, project: str) -> None:
        """Record a step toggle so `u` can flip it back without touching the verdict log."""
        self.undo_stack.append(
            {"key": key, "project": project, "label": "toggled", "kind": "step",
             "idx": idx, "prior_done": prior_done, "selected": [], "text": ""}
        )

    @staticmethod
    def _undo_flash(entry: dict[str, Any]) -> str:
        """What `u` says it just undid, in the entry's own terms."""
        if entry["kind"] == "step":
            return f"step {entry['idx'] + 1} undone"
        label = entry["label"]
        if label == "cleared":
            return "clear undone"
        if label == "skipped":
            return "skip undone"
        if label == "noted":
            return "verdict withdrawn"
        return "answer undone"

    async def action_undo(self) -> None:
        """Put the last resolved question back, with what was typed and picked.

        A purged entry's row is gone, so `reopen` raises `KeyError` and the
        loop keeps walking to the next-older one — but that walk used to run
        silently: it could drain several stack entries in one press with no
        flash and no status-bar refresh, which reads as `u` "doing nothing"
        even though it quietly consumed the stack underneath. Every exit from
        this method now leaves the status bar current, whether it restored a
        row or ran out of stack trying.

        On a row awaiting elaboration, `u` means something else entirely —
        withdraw the request itself (`Store.unelaborate`) rather than pop the
        answer-undo stack, which this row was never pushed onto.
        """
        q = self._current_question()
        if q is not None and q.status == "elaborate":
            await self._withdraw_elaborate(q)
            return
        while self.undo_stack:
            entry = self.undo_stack.pop()
            is_step = entry["kind"] == "step"
            try:
                if is_step:
                    self.store.set_step_done(
                        entry["key"], entry["idx"], entry["prior_done"], project=entry["project"]
                    )
                else:
                    self.store.reopen(entry["key"], project=entry["project"])
            except (KeyError, ValueError):
                # Purged (or, for a step, cleared) out from under us; the next
                # entry down is still good.
                continue
            if not is_step:
                self.drafts[entry["key"]] = entry["text"]
                if not entry["text"]:
                    self.drafts.pop(entry["key"], None)
                self.multi_selected = set(entry["selected"])
            self.focused_key = entry["key"]
            self.free_text_mode = False
            self._hide_input()
            self.current_project = entry["project"] \
                if self.scoped_project is None else self.current_project
            # Every undo names what it just undid — a silent `u` otherwise
            # looks identical to a no-op.
            self.flash = self._undo_flash(entry)
            await self._reload(force=True)
            self._synced_key = self.focused_key
            self.query_one("#rail-list", ListView).focus()
            return
        # Every remaining entry was purged out from under us: the stack is
        # now empty, same as if there had been nothing to undo at all.
        self.flash = "nothing to undo"
        self._rebuild_status_bar()

    # ---- misc -----------------------------------------------------------

    def action_quit_app(self) -> None:
        self.exit(0)


def run_tui(store: Store, project: str | None = None) -> int:
    """Run the interactive Textual answering app. Returns a process exit code."""
    app = CactusApp(store, project=project)
    result = app.run()
    return int(result) if isinstance(result, int) else 0
