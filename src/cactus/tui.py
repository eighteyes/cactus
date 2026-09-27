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
- Show a dedicated Projects pane where Cactus can be ignored or reactivated per project.
- Let a human ask an agent to rewrite a row (`e`) and withdraw that request
  (`u`) before the agent addresses it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from functools import partial
from pathlib import Path
from typing import Any

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from .scope import project_label
from .store import (ACTIONABLE, CONFIDENCE_GLYPH, AlreadyAnswered, Answer,
                    Question, Store)

POLL_INTERVAL = 0.5

TUI_SETTINGS_DEFAULTS = {"orientation": "side", "figlet_header": False}


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
    "Post each replacement as a follow-up (`cactus ask ... -p {key} --agent ID`), "
    "then clear the original row after the replacements are posted."
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


def _card_lines(
    q: Question,
    *,
    selected: set[str],
    pending: str,
    show_project: bool,
    run_output: list[str] | None = None,
    run_state: str = "",
) -> str:
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
    lines = ["  ".join(meta)]
    if q.parent_key:
        lines.append(f"follow-up to {q.parent_key}")
    lines.append("")
    lines.append(q.text)
    if q.context:
        lines.append("")
        lines.append(q.context)

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
            desc = f"  — {choice.description}" if choice.description else ""
            lines.append(f"  {i})  {mark}{choice.label}{rec}{desc}")
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
    lines.append(KEY_GAP.join(filter(None, [hint, _keys(*extras)])))
    return "\n".join(lines)


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
        if not q.blocked and q.status == "open":
            parts.append("not blocking")
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
    #card {
        border: round $accent;
        padding: 0 2;
        height: 1fr;
        margin: 0 1;
        overflow-y: auto;
    }
    #answer-input {
        display: none;
        margin: 0 1;
    }
    #empty-state {
        display: none;
        padding: 1 3;
        color: $text-muted;
    }
    #status-bar {
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
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
        Binding("s", "skip", "Skip (answers)"),
        Binding("c", "clear_focused", "Clear"),
        Binding("i", "toggle_free_text", "type"),
        Binding("y", "confirm_yes", "Yes"),
        Binding("n", "confirm_no", "No"),
        Binding("[", "prev_project", "PrevProj", key_display="["),
        Binding("]", "next_project", "NextProj", key_display="]"),
        Binding("P", "open_projects", "Projects"),
        Binding("I", "ignore_project", "Ignore"),
        Binding("A", "activate_project", "Activate"),
        Binding("u", "undo", "Undo"),
        Binding("e", "elaborate", "Elaborate"),
        Binding("D", "decompose", "Decompose"),
        Binding("?", "open_settings", "Settings", key_display="?"),
        Binding("p", "poke", "Poke"),
        Binding("v", "visit", "Visit"),
        Binding("C", "copy_command", "Copy"),
        Binding("R", "run_command", "Run"),
        Binding("O", "open_output", "Output"),
        Binding("d", "dismiss", "Dismiss"),
        Binding("r", "refresh_view", "Refresh"),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+c", "quit_app", "Quit", show=False),
        # Neutral label: the digits pick a choice on an ask row but toggle a
        # step on a plan row. The description here is the default; `_relabel`
        # swaps it (and y/n's) for the focused row's own wording on every
        # card rebuild, so the footer says what the key does on *this* row.
        Binding("1", "select_choice(1)", "Pick", show=True, key_display="1-9"),
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
        self._figlet_label: str | None = None
        self._figlet_text = ""
        self.free_text_mode = False
        # Set while the input is open for `e`'s prompt, so on_input_submitted
        # and escape route to the elaborate request instead of an answer.
        self.elaborating = False
        self.last_cursor: tuple[int, str, int] = (-1, "", -1)
        self._rebuilding = False
        self._synced_key: str | None = None
        # Plan keys already seen fully done, so the "all done" flash fires
        # once per completion rather than on every poll.
        self._plan_all_done: set[str] = set()
        # Digit buffer for a plan step past 9 (q16): "1" then "2" reaches
        # step 12 instead of toggling step 1 immediately. Empty when idle.
        self._step_buffer = ""
        self._step_buffer_key: str | None = None
        self._step_buffer_timer = None

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
            with Vertical(id="rail"):
                yield Static(id="project-head", markup=False)
                yield RailList(id="rail-list")
            with Vertical(id="main"):
                yield Static(id="card", markup=False)
                yield Input(id="answer-input", placeholder="free text — enter to confirm")
                yield Static("inbox empty — waiting for questions", id="empty-state")
        yield Static(id="settings-panel", markup=False)
        yield Static(id="projects-panel", markup=False)
        yield Static(id="status-bar", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        if self.scoped_project is None:
            live = self._live_projects()
            if self.current_project is None and live:
                self.current_project = live[0]
        self.query_one("#card", Static).border_title = "answering"
        self._apply_tui_settings()
        await self._reload(force=True)
        self.query_one("#rail-list", ListView).focus()
        self._sync_input_focus()
        # The footer's first read of check_action lands before the first row is
        # focused; re-ask once the screen has settled.
        self.call_after_refresh(self.refresh_bindings)
        self.set_interval(POLL_INTERVAL, self._poll)

    def _apply_tui_settings(self) -> None:
        body = self.query_one("#body", Horizontal)
        body.set_class(self.tui_settings["orientation"] == "bottom", "bottom")
        self._rebuild_project_banner()

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
        return "\n".join([
            "settings",
            "",
            f"1  left / right   questions left, detail right  {'●' if orientation == 'side' else '○'}",
            f"2  under / over   detail above, questions bottom {'●' if orientation == 'bottom' else '○'}",
            f"f  Figlet project header (cybermedium)            {figlet}",
            "",
            "esc or ?  return to the inbox",
        ])

    def _projects_text(self) -> str:
        """Render all known projects, including ignored and currently quiet ones."""
        if not self.project_rows:
            return "projects\n\nno projects yet\n\nesc or P  return to inbox"
        lines = ["projects", ""]
        for i, row in enumerate(self.project_rows):
            marker = "▸" if i == self.project_index else " "
            state = "active" if row["enabled"] else "ignored"
            counts = f"{row['open_count']} open"
            if row["live_count"]:
                counts += f" · {row['live_count']} live"
            lines.append(f"{marker} {project_label(row['project'])}  {state}  {counts}")
        lines.extend(["", "j/k or ↑/↓ move   enter open   I ignore   A activate", "esc or P  return to inbox"])
        return "\n".join(lines)

    def _render_projects(self) -> None:
        self.project_rows = self.store.projects()
        if self.project_rows:
            self.project_index = max(0, min(self.project_index, len(self.project_rows) - 1))
        else:
            self.project_index = 0
        self.query_one("#projects-panel", Static).update(self._projects_text())

    def _render_settings(self) -> None:
        self.query_one("#settings-panel", Static).update(self._settings_text())

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
        self.settings_open = False
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
        if self.questions or self.scoped_project is not None:
            return
        live = self._live_projects()
        if live and self.current_project not in live:
            self.current_project = live[0]
            self.questions = self.store.tree(
                project=self.current_project, status=list(ACTIONABLE)
            )

    async def _reload(self, *, force: bool = False) -> None:
        cursor = self.store.cursor()
        if not force and cursor == self.last_cursor:
            return
        self.last_cursor = cursor
        self._load_questions()
        self._flash_plan_done()
        self._rebuild_project_banner()
        self._rebuild_project_head()
        await self._rebuild_rail()
        self._rebuild_card()
        self._rebuild_status_bar()

    async def _poll(self) -> None:
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

    async def _rebuild_rail(self) -> None:
        listview = self.query_one("#rail-list", ListView)
        empty_state = self.query_one("#empty-state", Static)
        prior_key = self.focused_key
        self._rebuilding = True
        try:
            await listview.clear()
            for q in self.questions:
                await listview.append(
                    QuestionBlock(q, active=q.key == prior_key, draft=q.key in self.drafts)
                )
            empty_state.display = not self.questions
            self.query_one("#card", Static).display = bool(self.questions)
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

    def _rebuild_card(self) -> None:
        card = self.query_one("#card", Static)
        q = self._current_question()
        if q is None:
            card.display = False
            self.refresh_bindings()
            return
        card.display = True
        card.border_title = f"answering  {q.key}"
        card.update(
            _card_lines(
                q,
                selected=self.multi_selected,
                pending=self.pending_text,
                show_project=self._show_project,
                run_output=self.run_output.get(q.key),
                run_state=self.run_state.get(q.key, ""),
            )
        )
        # check_action is a pure function of the focused question and its
        # state, but Textual only re-asks it here — without this call the
        # footer keeps showing the previous row's keys after every navigation
        # or answer.
        self._relabel(q)
        self.refresh_bindings()

    # Footer labels that follow the focused row. A Binding's description is
    # static, so `y` would read "Yes" on a review that answers pass/fail and
    # `1-9` would read "Pick" on a plan whose digits toggle steps.
    _RELABEL_DEFAULTS = {"y": "Yes", "n": "No", "1": "Pick", "d": "Dismiss"}

    def _labels_for(self, q: Question) -> dict[str, str]:
        labels = dict(self._RELABEL_DEFAULTS)
        if q.kind == "confirm":
            names = [c.label for c in q.choices] or ["yes", "no"]
            labels["y"], labels["n"] = names[0], names[1] if len(names) > 1 else "No"
        if q.act == "plan":
            labels["1"] = "Toggle step"
        elif q.act == "data":
            labels["1"] = "Copy chunk"
            labels["d"] = "Close"
        elif q.kind == "multi":
            labels["1"] = "Toggle"
        return labels

    def _relabel(self, q: Question) -> None:
        """Rewrite the footer descriptions of the row-dependent keys.

        Reaches into Textual's binding map, which is the only place a
        description lives; every other path (check_action, the card hint) can
        only show or hide a key, not reword it. Fails soft: a Textual without
        that map keeps the neutral defaults from BINDINGS.
        """
        table = getattr(getattr(self, "_bindings", None), "key_to_bindings", None)
        if not isinstance(table, dict):
            return
        for key, description in self._labels_for(q).items():
            bindings = table.get(key)
            if not bindings:
                continue
            table[key] = [
                dataclasses.replace(b, description=description)
                if b.description != description else b
                for b in bindings
            ]

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
        if self.settings_open:
            return action in ("open_settings", "quit_app")
        if self.projects_open:
            return action in (
                "open_projects", "focus_next", "focus_prev", "submit",
                "ignore_project", "activate_project", "quit_app",
            )
        if self.free_text_mode or self.elaborating:
            if action in ("open_projects", "ignore_project", "activate_project"):
                return False
        if action in ("refresh_view", "quit_app", "open_settings"):
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
            return action in (
                "focus_next", "focus_prev", "prev_project", "next_project",
                "clear_focused", "undo", "poke", "visit", "refresh_view", "quit_app",
            )

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
        await self._submit_answer(q, selected=[], text=None, skipped=True, label="dismissed")

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
        # this method ever changes — refresh here so the footer's `u` tracks it.
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
        if self.projects_open:
            if event.key == "escape":
                self._close_projects()
                event.stop()
            return
        if self.settings_open:
            if event.key == "escape":
                self._close_settings()
            elif event.key == "1":
                self._set_orientation("side")
            elif event.key == "2":
                self._set_orientation("bottom")
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

    def action_focus_next(self) -> None:
        if self.projects_open:
            if self.project_rows:
                self.project_index = (self.project_index + 1) % len(self.project_rows)
                self._render_projects()
            return
        self._clear_flash()
        listview = self.query_one("#rail-list", ListView)
        listview.focus()
        listview.action_cursor_down()

    def action_focus_prev(self) -> None:
        if self.projects_open:
            if self.project_rows:
                self.project_index = (self.project_index - 1) % len(self.project_rows)
                self._render_projects()
            return
        self._clear_flash()
        listview = self.query_one("#rail-list", ListView)
        listview.focus()
        listview.action_cursor_up()

    async def action_prev_project(self) -> None:
        await self._switch_project(-1)

    async def action_next_project(self) -> None:
        await self._switch_project(1)

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
            await self._submit_answer(q, selected=[choice.label], text=None)
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
            await self._confirm(n - 1)
            return
        if n < 1 or n > len(q.choices):
            self.flash = f"{q.key} has no choice {n}"
            self._rebuild_status_bar()
            return
        label = q.choices[n - 1].label
        if q.kind == "choice":
            await self._submit_answer(q, selected=[label], text=self.pending_text or None)
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
                q, selected=sorted(self.multi_selected), text=self.pending_text or None
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
            await self._submit_answer(q, selected=[], text=self.pending_text)
        elif q.recommend:
            # No pick and no typed text: enter submits the agent's own
            # recommendation. It is advisory, not a `chosen` that already
            # proceeded — this tap is what confirms it.
            await self._submit_answer(q, selected=list(q.recommend), text=None)
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
        await self._confirm(0)

    async def action_confirm_no(self) -> None:
        await self._confirm(1)

    async def _confirm(self, index: int) -> None:
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
        await self._submit_answer(q, selected=[label], text=self.pending_text or None)

    async def action_skip(self) -> None:
        q = self._current_question()
        if q is None:
            return
        await self._submit_answer(q, selected=[], text=None, skipped=True)

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
        self._load_questions()
        self.last_cursor = self.store.cursor()
        if self.questions:
            next_index = min(old_index, len(self.questions) - 1)
            self.focused_key = self.questions[next_index].key
            self.multi_selected = self._default_multi_selection(self.focused_key)
        else:
            self.focused_key = None
        self._rebuild_project_head()
        await self._rebuild_rail()
        self._rebuild_card()
        self._rebuild_status_bar()
        self._synced_key = None
        self._sync_input_focus()

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
