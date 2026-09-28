"""
field.py — pachinko physics for the TUI's answer strip.

Responsibilities:
- Hold the grid of settled cells and the one block currently falling.
- Drop a block into a column and step it down one row at a time.
- Decide when a falling block anchors: floor, or beside a settled cell,
  including the two "reverse pawn" diagonals below it.
- Render the grid as a styled rich.text.Text for the TUI to display.

In-memory only: no persistence, no store, no Textual import.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text

DEFAULT_ROWS = 6


@dataclass
class Field:
    rows: int = DEFAULT_ROWS
    cells: set[tuple[int, int]] = field(default_factory=set)
    falling: tuple[int, int] | None = None

    def drop(self, x: int) -> None:
        """Start a block falling in column x, at the top row.

        Ignored if a block is already falling, or the top of that column is
        already occupied.
        """
        if self.falling is not None:
            return
        top = (x, self.rows - 1)
        if top in self.cells:
            return
        self.falling = top

    def anchored(self, x: int, y: int) -> bool:
        """True if (x, y) touches the floor or a settled neighbour.

        The five neighbours checked are directly below, either side, and the
        two diagonals below (a reverse pawn's capture squares) — so a block
        anchors beside a structure, not only when blocked from straight below.
        """
        if y == 0:
            return True
        neighbours = ((x, y - 1), (x - 1, y), (x + 1, y), (x - 1, y - 1), (x + 1, y - 1))
        return any(n in self.cells for n in neighbours)

    def step(self) -> bool:
        """Advance the falling block one row down.

        Returns True while still falling, False once it anchored (or there
        was none). The anchor check runs at the current position, before any
        move, so a block anchors the moment it is beside a structure.
        """
        if self.falling is None:
            return False
        x, y = self.falling
        if self.anchored(x, y):
            self.cells.add((x, y))
            self.falling = None
            return False
        self.falling = (x, y - 1)
        return True

    def render(self, width: int) -> Text:
        """Render the grid, row rows-1 (top) first, as a styled Text block.

        Settled cells are green, the falling block bright_green. Cells at or
        past `width` are kept in `cells` but not drawn.
        """
        width = max(width, 1)
        lines = []
        for y in range(self.rows - 1, -1, -1):
            chars = []
            for x in range(width):
                filled = (x, y) in self.cells or self.falling == (x, y)
                chars.append("█" if filled else " ")
            lines.append("".join(chars))
        text = Text("\n".join(lines))
        line_len = width + 1  # each row plus its trailing newline
        for cx, cy in self.cells:
            if cx >= width:
                continue
            row_index = self.rows - 1 - cy
            pos = row_index * line_len + cx
            text.stylize("green", pos, pos + 1)
        if self.falling is not None:
            fx, fy = self.falling
            if fx < width:
                row_index = self.rows - 1 - fy
                pos = row_index * line_len + fx
                text.stylize("bright_green", pos, pos + 1)
        return text
