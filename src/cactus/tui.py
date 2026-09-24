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
- Let a human ask an agent to rewrite a row (`e`) and withdraw that request
  (`u`) before the agent addresses it.
"""

from __future__ import annotations

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

# How many lines of command output the card shows; the rest spills to a file.
RUN_TAIL = 12

# `confirm` is built at render time from the row's own choice labels — see
# `_confirm_hint` — because a review answers pass/fail and a run approve/deny,
# and a fixed yes/no hint would lie about what the keys send.
HINTS = {
    "choice": "1-9 pick   i type   s skip (answers)   c clear",
    "multi": "1-9 toggle   enter submit   i type   s skip (answers)   c clear",
    "text": "enter to type   esc back to list   s skip (answers)   c clear",
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
    """A row can be poked only when it has an owner and herdr pane and session
    stamps: the default transport prompts a herdr pane, so a row posted outside
    herdr has nowhere for the nudge to land, and the footer should not offer it."""
    return bool(q.agent and q.pane and q.session)


def _confirm_hint(q: Question) -> str:
    """Confirm-row hint built from the row's own labels, not a fixed yes/no."""
    labels = [c.label for c in q.choices] or ["yes", "no"]
    keys = ["y/1", "n/2"]
    picks = [f"{key} {label}" for key, label in zip(keys, labels)]
    return "   ".join([*picks, "i type", "s skip (answers)", "c clear"])


def _verdict_repr(a: Answer) -> str:
    """One answer from the log, as a short label for the verdicts line."""
    if a.selected:
        return ", ".join(a.selected)
    if a.text:
        text = a.text.strip()
        return text if len(text) <= 24 else text[:23] + "…"
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

    if q.kind in ("choice", "multi"):
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
        label = "answer" if q.kind == "text" else "free text"
        lines.append(f"{label}: {pending}")
        if q.kind != "text":
            lines.append("enter submits this text alone, or pick above to send both")

    lines.append("")
    if q.status == "elaborate":
        # Stopped accepting answers — the pick/type/skip hints above would
        # promise a key that check_action already refuses.
        hint = "awaiting rewrite by the agent — no answers accepted"
        extras = ["c clear", "u withdraw request"]
        if _pokeable(q):
            extras.append("p poke")
    else:
        hint = _confirm_hint(q) if q.kind == "confirm" else HINTS.get(q.kind, "")
        extras = []
        if q.review is not None and q.review.run_cmd:
            extras.append("C copy   R run")
        if _pokeable(q):
            extras.append("p poke")
        if q.act == "plan" and q.steps:
            extras.append("1-9 toggle step")
        if q.act == "seen":
            extras.append("d dismiss")
        if run_output:
            extras.append("O open full output")
        if q.status in ("open", "live"):
            extras.append("e elaborate")
    lines.append("   ".join([hint, *extras]).strip())
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
            shape = "yes / no"
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
    #rail {
        width: 32;
        border-right: solid $panel;
    }
    #project-head {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text;
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
        Binding("[", "prev_project", "PrevProj"),
        Binding("]", "next_project", "NextProj"),
        Binding("u", "undo", "Undo"),
        Binding("e", "elaborate", "Elaborate"),
        Binding("p", "poke", "Poke"),
        Binding("C", "copy_command", "Copy"),
        Binding("R", "run_command", "Run"),
        Binding("O", "open_output", "Output"),
        Binding("d", "dismiss", "Dismiss"),
        Binding("r", "refresh_view", "Refresh"),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+c", "quit_app", "Quit", show=False),
        Binding("1", "select_choice(1)", "1-9 pick", show=True),
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
        with Horizontal(id="body"):
            with Vertical(id="rail"):
                yield Static(id="project-head", markup=False)
                yield RailList(id="rail-list")
            with Vertical(id="main"):
                yield Static(id="card", markup=False)
                yield Input(id="answer-input", placeholder="free text — enter to confirm")
                yield Static("inbox empty — waiting for questions", id="empty-state")
        yield Static(id="status-bar", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        if self.scoped_project is None:
            live = self._live_projects()
            if self.current_project is None and live:
                self.current_project = live[0]
        self.query_one("#card", Static).border_title = "answering"
        await self._reload(force=True)
        self.query_one("#rail-list", ListView).focus()
        self._sync_input_focus()
        # The footer's first read of check_action lands before the first row is
        # focused; re-ask once the screen has settled.
        self.call_after_refresh(self.refresh_bindings)
        self.set_interval(POLL_INTERVAL, self._poll)

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
        head.update(f"{label}  {counts}{switch}")

    def _live_projects_rows(self) -> list[dict[str, Any]]:
        return [
            r for r in self.store.projects()
            if (r["open_count"] > 0 or r["live_count"] > 0)
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
        self.refresh_bindings()

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
        if action in ("refresh_view", "quit_app"):
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
                "clear_focused", "undo", "poke", "refresh_view", "quit_app",
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
            return q.act == "seen"
        if action == "poke":
            return _pokeable(q)
        if action == "undo":
            return bool(self.undo_stack)
        if action == "elaborate":
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

        Always spills — unlike a plain review run, a `run` row's result has to
        outlive this process for `get --json`/`feed`/the monitor to read it
        back, not just the card's tail.
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
            self.store.answer(key, project=project, selected=["approve"], text=None)
        except Exception as exc:
            self.flash = f"{key}: result not recorded: {exc}"
        if self.focused_key == key:
            self._rebuild_card()
            self.flash = f"{key}: approved, exit {exit_code}"
            self._rebuild_status_bar()

    def _append_output(self, key: str, line: str) -> None:
        self.run_output.setdefault(key, []).append(line)
        if self.focused_key == key:
            self._rebuild_card()

    def _finish_output(self, key: str) -> None:
        tail = self.run_output.get(key) or []
        last = tail[-1] if tail else ""
        self.run_state[key] = last.strip("— ") if last.startswith("—") else "done"
        if self.focused_key == key:
            self._rebuild_card()
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
        """Dismiss a seen row — it wanted acknowledgement, not an answer."""
        q = self._current_question()
        if q is None:
            return
        if q.act != "seen":
            self.flash = f"{q.key} is act={q.act}, not a dismissable notice"
            self._rebuild_status_bar()
            return
        await self._submit_answer(q, selected=[], text=None, skipped=True, label="dismissed")

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
                poke(q.agent, timeout=5.0)
            except PokeError as exc:
                self.flash = f"poke failed: {exc}"
            else:
                self.flash = f"poked {q.agent}"
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
        if isinstance(event, events.Key) and not self.free_text_mode and not self.elaborating:
            self._clear_flash()
        await super().on_event(event)

    async def on_key(self, event: events.Key) -> None:
        """Catch keys check_action disables, so a press still gets a one-line answer.

        The footer hides `u` when the undo stack is empty — a key that cannot
        do anything should not be advertised — but that same gate stops the
        binding from firing, so the press would otherwise land in silence.
        This runs after bindings, so an enabled `u`/`y`/`n` never reaches here.
        """
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
                self.flash = f"y/n only answer a confirm row — {q.key} is {q.kind}"
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

    def action_focus_next(self) -> None:
        self._clear_flash()
        listview = self.query_one("#rail-list", ListView)
        listview.focus()
        listview.action_cursor_down()

    def action_focus_prev(self) -> None:
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
            self._focus_input()
            return
        self.free_text_mode = not self.free_text_mode
        if self.free_text_mode:
            inp = self.query_one("#answer-input", Input)
            inp.value = self.pending_text
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
            idx = n - 1
            step = next((st for st in plan.steps if st.idx == idx), None)
            if step is None:
                self.flash = f"{plan.key} has no step {n}"
            else:
                self.store.set_step_done(plan.key, idx, not step.done, project=plan.project)
                self.flash = f"step {n} {'done' if not step.done else 'reopened'}"
            await self.action_refresh_view()
            self._rebuild_status_bar()
            return
        q = self._current_question()
        if q is None or q.kind not in ("choice", "multi", "confirm"):
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

    async def action_submit(self) -> None:
        q = self._current_question()
        if q is None:
            return
        if q.act == "plan":
            await self._submit_plan(q)
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
        """Enter on a plan row records typed text as a verdict; it never closes the row.

        `typed` carries the Input widget's own value when this fires from
        `on_input_submitted` (the row wasn't focused there yet, so the pending
        draft cannot be trusted); the rail's enter falls back to the draft.
        Closing is `c`'s job — see the CLAUDE.md invariant this file keeps.
        """
        text = (typed if typed is not None else self.pending_text).strip()
        if text:
            try:
                self.store.answer(q.key, project=q.project, selected=[], text=text, skipped=False)
            except (KeyError, ValueError) as exc:
                await self._refuse(exc)
                return
            self._push_undo(q.key, "noted", [], text, project=q.project)
            self.pending_text = ""
            self.free_text_mode = False
            self._hide_input()
            self.flash = "noted"
            self._redraw_active()
            self._rebuild_status_bar()
            self.query_one("#rail-list", ListView).focus()
            return
        open_count = sum(1 for st in q.steps if not st.done)
        self.flash = (
            f"{open_count} step{'' if open_count == 1 else 's'} open — i to type" if open_count
            else "all steps done — c to clear"
        )
        self._rebuild_status_bar()

    def _pick_hint(self, q: Question) -> str:
        """What enter means with no draft on a choice/confirm row, in its own keys."""
        if q.kind == "confirm":
            n = len(q.choices) or 2
            return f"pick with y/n or 1-{n}"
        n = len(q.choices)
        return f"pick with 1-{n}" if n > 1 else "pick with 1"

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
            {"key": key, "project": project, "label": label,
             "selected": list(selected), "text": text or ""}
        )

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
            try:
                self.store.reopen(entry["key"], project=entry["project"])
            except KeyError:
                # Purged out from under us; the next entry down is still good.
                continue
            self.drafts[entry["key"]] = entry["text"]
            if not entry["text"]:
                self.drafts.pop(entry["key"], None)
            self.focused_key = entry["key"]
            self.multi_selected = set(entry["selected"])
            self.free_text_mode = False
            self._hide_input()
            self.current_project = entry["project"] \
                if self.scoped_project is None else self.current_project
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
