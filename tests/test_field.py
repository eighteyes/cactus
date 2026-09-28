"""
test_field.py — Field physics: drop, step, anchoring.

Responsibilities:
- A dropped block falls to the floor on an empty field.
- A block anchors on top of a settled cell, and beside one (including the
  reverse-pawn diagonal below).
- Dropping onto an occupied top cell is a no-op.
"""

from __future__ import annotations

from cactus.field import Field


def run_to_anchor(f: Field) -> None:
    while f.step():
        pass


def test_drop_on_empty_field_anchors_at_floor() -> None:
    f = Field(rows=6)
    f.drop(2)
    run_to_anchor(f)
    assert (2, 0) in f.cells
    assert f.falling is None


def test_drop_above_settled_cell_anchors_one_up() -> None:
    f = Field(rows=6, cells={(2, 0)})
    f.drop(2)
    run_to_anchor(f)
    assert (2, 1) in f.cells


def test_drop_left_of_settled_cell_anchors_on_diagonal() -> None:
    f = Field(rows=6, cells={(5, 0)})
    f.drop(4)
    run_to_anchor(f)
    assert (4, 1) in f.cells
    assert (4, 0) not in f.cells


def test_drop_beside_tall_column_anchors_one_above_its_top() -> None:
    f = Field(rows=6, cells={(5, 0), (5, 1), (5, 2)})
    f.drop(4)
    run_to_anchor(f)
    assert (4, 3) in f.cells


def test_drop_onto_occupied_top_cell_is_ignored() -> None:
    f = Field(rows=3, cells={(1, 2)})
    f.drop(1)
    assert f.falling is None
