"""
tui.py — interactive Textual application for answering questions in the qaui inbox.

Responsibilities:
- Render open questions as a threaded list, scoped to one project or all projects.
- Let a human answer choice, multi, confirm, and text questions from the keyboard.
- Poll the store's change cursor and refresh the view without losing focus or
  in-progress input.
- Provide project switching, skip, and clear actions, plus key-hint and count footers.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

from .scope import project_label
from .store import Question, Store

POLL_INTERVAL = 0.5


def _format_choices(q: Question, selected: set[str]) -> str:
    lines: list[str] = []
    for i, choice in enumerate(q.choices, start=1):
        mark = "[x]" if choice.label in selected else "[ ]"
        prefix = f"{mark} {i}" if q.kind == "multi" else f"{i}"
        desc = f" — {choice.description}" if choice.description else ""
        lines.append(f"      {prefix}) {choice.label}{desc}")
    return "\n".join(lines)


def _format_question(q: Question, *, focused: bool, selected: set[str]) -> str:
    indent = "  " * q.depth
    marker = ">" if focused else " "
    head = f"{marker} {indent}{q.key}"
    if q.thread:
        head += f"  ({q.thread})"
    if q.asked_by:
        head += f"  [{q.asked_by}]"
    lines = [head, f"{indent}    {q.text}"]
    if q.context:
        lines.append(f"{indent}    {q.context}")
    if q.kind in ("choice", "multi"):
        lines.append(_format_choices(q, selected))
    elif q.kind == "confirm":
        yes = q.choices[0].label if q.choices else "yes"
        no = q.choices[1].label if len(q.choices) > 1 else "no"
        lines.append(f"      y) {yes}   n) {no}")
    if q.allow_free and q.kind != "text":
        lines.append("      i) add free text")
    return "\n".join(lines)


class QuestionRow(ListItem):
    """One row of the threaded question list, keyed to a question."""

    def __init__(self, question: Question, *, focused: bool, selected: set[str]) -> None:
        super().__init__(id=f"row-{question.key}")
        self.key = question.key
        # markup=False: question text carries literal brackets — the [x]/[ ] multi marks
        # and the [asked_by] tag — which Textual's markup parser would consume silently.
        self._text = Static(
            _format_question(question, focused=focused, selected=selected), markup=False
        )

    def compose(self) -> ComposeResult:
        yield self._text

    def update(self, question: Question, *, focused: bool, selected: set[str]) -> None:
        self._text.update(_format_question(question, focused=focused, selected=selected))


class ProjectRow(ListItem):
    """One row of the project rail."""

    def __init__(self, project: str, open_count: int, *, active: bool) -> None:
        super().__init__(id=f"proj-{project_label(project)}")
        self.project = project
        marker = ">" if active else " "
        self._text = Static(f"{marker} {project_label(project)}  {open_count}", markup=False)

    def compose(self) -> ComposeResult:
        yield self._text


class QAUIApp(App[int]):
    """Human answering surface for the qaui question inbox."""

    CSS = """
    #body {
        height: 1fr;
    }
    #project-rail {
        width: 24;
        border-right: solid $panel;
    }
    #main {
        width: 1fr;
    }
    #question-list {
        height: 1fr;
    }
    #answer-input {
        display: none;
    }
    #empty-state {
        display: none;
        padding: 1;
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
        Binding("s", "skip", "Skip"),
        Binding("c", "clear_focused", "Clear"),
        Binding("i", "toggle_free_text", "FreeText"),
        Binding("y", "confirm_yes", "Yes"),
        Binding("n", "confirm_no", "No"),
        Binding("[", "prev_project", "PrevProj"),
        Binding("]", "next_project", "NextProj"),
        Binding("r", "refresh_view", "Refresh"),
        Binding("q", "quit_app", "Quit"),
        Binding("1", "select_choice(1)", "1", show=True),
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
        self.scoped_project = project
        self.current_project: str | None = project
        self.questions: list[Question] = []
        self.focused_key: str | None = None
        self.multi_selected: set[str] = set()
        self.free_text_mode = False
        self.last_cursor: tuple[int, str] = (-1, "")
        self._rebuilding = False

    # ---- layout -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            if self.scoped_project is None:
                yield ListView(id="project-rail")
            with Vertical(id="main"):
                yield ListView(id="question-list")
                yield Static("inbox empty — waiting for questions", id="empty-state")
                yield Input(id="answer-input", placeholder="free text — enter to confirm")
        yield Static(id="status-bar", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        if self.scoped_project is None:
            rows = self.store.projects()
            if self.current_project is None and rows:
                self.current_project = rows[0]["project"]
        await self._reload(force=True)
        self.query_one("#question-list", ListView).focus()
        self.set_interval(POLL_INTERVAL, self._poll)

    # ---- data loading ---------------------------------------------------

    async def _reload(self, *, force: bool = False) -> None:
        cursor = self.store.cursor()
        if not force and cursor == self.last_cursor:
            return
        self.last_cursor = cursor
        self.questions = self.store.tree(
            project=self.current_project,
            status="open",
            all_projects=self.current_project is None,
        )
        await self._rebuild_project_rail()
        await self._rebuild_question_list()
        self._rebuild_status_bar()

    async def _poll(self) -> None:
        await self._reload()

    async def action_refresh_view(self) -> None:
        await self._reload(force=True)

    # ---- rendering --------------------------------------------------------

    async def _rebuild_project_rail(self) -> None:
        if self.scoped_project is not None:
            return
        try:
            rail = self.query_one("#project-rail", ListView)
        except Exception:
            return
        rows = self.store.projects()
        prior_index = rail.index
        await rail.clear()
        for r in rows:
            await rail.append(
                ProjectRow(r["project"], r["open_count"], active=r["project"] == self.current_project)
            )
        for i, r in enumerate(rows):
            if r["project"] == self.current_project:
                rail.index = i
                return
        if prior_index is not None and rows:
            rail.index = min(prior_index, len(rows) - 1)

    async def _rebuild_question_list(self) -> None:
        listview = self.query_one("#question-list", ListView)
        empty_state = self.query_one("#empty-state", Static)
        prior_key = self.focused_key
        self._rebuilding = True
        try:
            await listview.clear()
            for q in self.questions:
                focused = q.key == prior_key
                selected = self.multi_selected if focused else set()
                await listview.append(QuestionRow(q, focused=focused, selected=selected))
            empty_state.display = not self.questions
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
            if prior_key != self.focused_key:
                self.multi_selected = set()
        finally:
            self._rebuilding = False

    def _rebuild_status_bar(self) -> None:
        bar = self.query_one("#status-bar", Static)
        rows = self.store.projects()
        open_total = sum(r["open_count"] for r in rows)
        proj_total = len(rows)
        bar.update(f"{open_total} open / {proj_total} projects")

    def _current_question(self) -> Question | None:
        for q in self.questions:
            if q.key == self.focused_key:
                return q
        return None

    def _redraw_focused_row(self) -> None:
        q = self._current_question()
        if q is None:
            return
        try:
            row = self.query_one(f"#row-{q.key}", QuestionRow)
        except Exception:
            return
        row.update(q, focused=True, selected=self.multi_selected)

    # ---- focus / navigation ------------------------------------------------

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "question-list" or self._rebuilding:
            return
        item = event.item
        if item is None:
            # Fires as a side effect of clearing the list during a rebuild;
            # it does not represent a real navigation change.
            return
        new_key = getattr(item, "key", None)
        if new_key == self.focused_key:
            return
        self.focused_key = new_key
        self.multi_selected = set()
        self.free_text_mode = False
        self._hide_input()
        await self._rebuild_question_list()
        q = self._current_question()
        if q is not None and q.kind == "text":
            self._focus_input()

    def action_focus_next(self) -> None:
        listview = self.query_one("#question-list", ListView)
        listview.focus()
        listview.action_cursor_down()

    def action_focus_prev(self) -> None:
        listview = self.query_one("#question-list", ListView)
        listview.focus()
        listview.action_cursor_up()

    async def action_prev_project(self) -> None:
        await self._switch_project(-1)

    async def action_next_project(self) -> None:
        await self._switch_project(1)

    async def _switch_project(self, step: int) -> None:
        if self.scoped_project is not None:
            return
        rows = self.store.projects()
        if not rows:
            return
        names = [r["project"] for r in rows]
        try:
            idx = names.index(self.current_project)
        except ValueError:
            idx = 0
        self.current_project = names[(idx + step) % len(names)]
        self.focused_key = None
        self.multi_selected = set()
        self.free_text_mode = False
        self._hide_input()
        await self._reload(force=True)

    # ---- input handling -----------------------------------------------

    def _focus_input(self) -> None:
        inp = self.query_one("#answer-input", Input)
        inp.display = True
        inp.focus()

    def _hide_input(self) -> None:
        inp = self.query_one("#answer-input", Input)
        inp.value = ""
        inp.display = False

    def _pending_text(self) -> str | None:
        inp = self.query_one("#answer-input", Input)
        value = inp.value.strip()
        return value or None

    def action_toggle_free_text(self) -> None:
        q = self._current_question()
        if q is None or not q.allow_free or q.kind == "text":
            return
        self.free_text_mode = not self.free_text_mode
        if self.free_text_mode:
            self._focus_input()
        else:
            self._hide_input()
            self.query_one("#question-list", ListView).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        q = self._current_question()
        if q is None:
            return
        if q.kind == "text":
            await self._submit_answer(q, selected=[], text=event.value.strip() or None)
        else:
            # Free-text supplement entered; return to the list so the human
            # can finish the answer with a choice/confirm/select key.
            self.free_text_mode = False
            inp = self.query_one("#answer-input", Input)
            inp.display = False
            self.query_one("#question-list", ListView).focus()

    # ---- answering ----------------------------------------------------

    async def action_select_choice(self, n: int) -> None:
        q = self._current_question()
        if q is None or q.kind not in ("choice", "multi"):
            return
        if n < 1 or n > len(q.choices):
            return
        label = q.choices[n - 1].label
        if q.kind == "choice":
            await self._submit_answer(q, selected=[label], text=self._pending_text())
        else:
            if label in self.multi_selected:
                self.multi_selected.discard(label)
            else:
                self.multi_selected.add(label)
            self._redraw_focused_row()

    async def action_submit(self) -> None:
        q = self._current_question()
        if q is None:
            return
        if q.kind == "multi":
            await self._submit_answer(q, selected=sorted(self.multi_selected), text=self._pending_text())
        elif q.kind == "text":
            self._focus_input()

    async def action_confirm_yes(self) -> None:
        await self._confirm(0)

    async def action_confirm_no(self) -> None:
        await self._confirm(1)

    async def _confirm(self, index: int) -> None:
        q = self._current_question()
        if q is None or q.kind != "confirm":
            return
        labels = [c.label for c in q.choices] or ["yes", "no"]
        label = labels[index] if index < len(labels) else labels[-1]
        await self._submit_answer(q, selected=[label], text=self._pending_text())

    async def action_skip(self) -> None:
        q = self._current_question()
        if q is None:
            return
        await self._submit_answer(q, selected=[], text=None, skipped=True)

    async def action_clear_focused(self) -> None:
        q = self._current_question()
        if q is None:
            return
        self.store.clear(keys=[q.key], all_projects=True)
        await self._advance_after(q.key)

    async def _submit_answer(
        self, q: Question, *, selected: list[str], text: str | None, skipped: bool = False
    ) -> None:
        try:
            self.store.answer(q.key, selected=selected, text=text, skipped=skipped)
        except KeyError:
            pass
        await self._advance_after(q.key)

    async def _advance_after(self, answered_key: str) -> None:
        old_index = 0
        for i, q in enumerate(self.questions):
            if q.key == answered_key:
                old_index = i
                break
        self.multi_selected = set()
        self.free_text_mode = False
        self._hide_input()
        self.questions = self.store.tree(
            project=self.current_project,
            status="open",
            all_projects=self.current_project is None,
        )
        self.last_cursor = self.store.cursor()
        if self.questions:
            next_index = min(old_index, len(self.questions) - 1)
            self.focused_key = self.questions[next_index].key
        else:
            self.focused_key = None
        await self._rebuild_project_rail()
        await self._rebuild_question_list()
        self._rebuild_status_bar()
        q = self._current_question()
        if q is not None and q.kind == "text":
            self._focus_input()
        else:
            self.query_one("#question-list", ListView).focus()

    # ---- misc -----------------------------------------------------------

    def action_quit_app(self) -> None:
        self.exit(0)


def run_tui(store: Store, project: str | None = None) -> int:
    """Run the interactive Textual answering app. Returns a process exit code."""
    app = QAUIApp(store, project=project)
    result = app.run()
    return int(result) if isinstance(result, int) else 0
