"""
watch.py — read-only live feed of the cactus inbox.

Responsibilities:
- Render the current backlog of open questions on start.
- Poll the store's change cursor and append only new ASK/ANSWER events as they occur.
- Track displayed state per question so an edited answer re-emits exactly once.
- Offer pause/resume, answered-visibility toggle, screen-only clear, and scrolling,
  without ever writing to the store.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, RichLog, Static

from .scope import project_display, project_label
from .store import Question, Store

POLL_INTERVAL = 0.5


def _fmt_choices(q: Question) -> str:
    return " | ".join(c.label for c in q.choices)


def _fmt_answer_text(q: Question) -> str:
    if q.status == "cleared":
        return "(cleared)"
    if q.answer is None:
        return ""
    if q.answer.skipped:
        return "(skipped)"
    parts = []
    if q.answer.selected:
        parts.append(", ".join(q.answer.selected))
    if q.answer.text:
        parts.append(q.answer.text)
    return " — ".join(parts) if parts else "(empty)"


@dataclass
class _Seen:
    """Last displayed (status, updated_at) for one question key."""

    status: str
    updated_at: str


class WatchApp(App[None]):
    """Textual app driving the live feed."""

    CSS = """
    #feed {
        height: 1fr;
    }
    #status {
        height: 1;
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "quit"),
        ("ctrl+c", "quit", "quit"),
        ("p", "toggle_pause", "pause/resume"),
        ("f", "toggle_answered", "toggle answered"),
        ("c", "clear_screen", "clear screen"),
        ("home", "scroll_home", "top"),
        ("end", "scroll_end", "bottom"),
        ("pageup", "scroll_page_up", "page up"),
        ("pagedown", "scroll_page_down", "page down"),
    ]

    def __init__(self, store: Store, project: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.project = project
        self._seen: dict[str, _Seen] = {}
        self._cursor: tuple[int, str, int] = (0, "", 0)
        self._paused = False
        self._pending: list[Question] = []
        self._show_answered = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            RichLog(id="feed", wrap=True, highlight=False, markup=False, auto_scroll=True),
            Static(id="status"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "cactus watch"
        db = str(self.store.path)
        scope = project_display(self.project) if self.project else "all projects"
        self.sub_title = f"{db} — {scope}"
        self._load_backlog()
        self._refresh_status()
        self.set_interval(POLL_INTERVAL, self._poll)

    # ---- data ---------------------------------------------------------

    def _questions(self) -> list[Question]:
        return self.store.tree(
            project=self.project,
            status=("open", "answered", "cleared"),
            all_projects=self.project is None,
        )

    def _load_backlog(self) -> None:
        backlog = self.store.list(
            project=self.project,
            status="open",
            all_projects=self.project is None,
        )
        for q in backlog:
            self._emit_ask(q)
            self._seen[q.key] = _Seen(q.status, q.updated_at)
        self._cursor = self.store.cursor()

    def _poll(self) -> None:
        cursor = self.store.cursor()
        if cursor == self._cursor:
            return
        self._cursor = cursor
        events = self._diff()
        if self._paused:
            self._pending.extend(events)
        else:
            for q in events:
                self._emit_event(q)
        self._refresh_status()

    def _diff(self) -> list[Question]:
        changed: list[Question] = []
        for q in self._questions():
            prior = self._seen.get(q.key)
            if prior is None or prior.status != q.status or prior.updated_at != q.updated_at:
                changed.append(q)
                self._seen[q.key] = _Seen(q.status, q.updated_at)
        return changed

    # ---- rendering ------------------------------------------------------

    def _emit_event(self, q: Question) -> None:
        if q.status == "open":
            self._emit_ask(q)
        elif q.status in ("answered", "cleared"):
            self._emit_answer(q)

    def _emit_ask(self, q: Question) -> None:
        log = self.query_one("#feed", RichLog)
        indent = "  " * q.depth
        head = f"[{q.created_at}] ASK {q.key}"
        if self.project is None:
            head += f" [{project_label(q.project)}]"
        if q.thread:
            head += f" ({q.thread})"
        if q.asked_by:
            head += f" by {q.asked_by}"
        log.write(f"{head}\n{indent}  {q.text}")
        choices = _fmt_choices(q)
        if choices:
            log.write(f"{indent}    choices: {choices}")

    def _emit_answer(self, q: Question) -> None:
        if not self._show_answered:
            return
        log = self.query_one("#feed", RichLog)
        label = "ANSWER" if q.status == "answered" else "CLEAR"
        head = f"[{q.updated_at}] {label} {q.key}"
        if self.project is None:
            head += f" [{project_label(q.project)}]"
        log.write(f"{head}\n  -> {_fmt_answer_text(q)}")

    def _refresh_status(self) -> None:
        rows = self.store.projects()
        if self.project is not None:
            rows = [r for r in rows if r["project"] == self.project]
        open_count = sum(int(r["open_count"]) for r in rows)
        answered_count = sum(int(r["answered_count"]) for r in rows)
        project_count = len(rows)
        state = "paused" if self._paused else "live"
        answered_flag = "on" if self._show_answered else "off"
        status = self.query_one("#status", Static)
        status.update(
            f"{open_count} open · {answered_count} answered · {project_count} projects "
            f"· [{state}] · answered:{answered_flag} · q quit · p pause · f answered · c clear"
        )

    # ---- actions --------------------------------------------------------

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        if not self._paused and self._pending:
            for q in self._pending:
                self._emit_event(q)
            self._pending.clear()
        self._refresh_status()

    def action_toggle_answered(self) -> None:
        self._show_answered = not self._show_answered
        self._refresh_status()

    def action_clear_screen(self) -> None:
        self.query_one("#feed", RichLog).clear()

    def action_scroll_home(self) -> None:
        self.query_one("#feed", RichLog).scroll_home()

    def action_scroll_end(self) -> None:
        self.query_one("#feed", RichLog).scroll_end()

    def action_scroll_page_up(self) -> None:
        self.query_one("#feed", RichLog).scroll_page_up()

    def action_scroll_page_down(self) -> None:
        self.query_one("#feed", RichLog).scroll_page_down()


def run_watch(store: Store, project: str | None = None) -> int:
    """Run the live read-only feed. Returns a process exit code."""
    app = WatchApp(store, project=project)
    try:
        app.run()
    except KeyboardInterrupt:
        return 130
    return 0
