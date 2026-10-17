"""The team-shape plug-in interface and the office map it produces.

A shape draws the static office (walls, desks, zones) and says where each agent
sits. Pets, cards and bubbles are drawn on top by the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

WALL = "▓"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


@dataclass
class OfficeMap:
    """The static office: text rows plus named places the world model uses."""

    width: int
    height: int
    rows: list[str]
    # Named areas: "board", "boss_desk", "lounge", "review", "door", ...
    zones: dict[str, Rect] = field(default_factory=dict)
    # Desk per agent name; empty desks are keyed "" + index, e.g. "_2".
    desks: dict[str, Rect] = field(default_factory=dict)
    # Where each agent's pet sits at its desk: name -> (x, y).
    seats: dict[str, tuple[int, int]] = field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(self.rows)


class TeamShape(Protocol):
    name: str  # "lead" or "pipeline", as in `[team] shape`

    def layout(self, width: int, height: int, lead: str | None, workers: list[str]) -> OfficeMap:
        """Draw the office for this team at this size (in terminal cells)."""
        ...


class Canvas:
    """A fixed-size grid of single-width characters to draw an office on."""

    def __init__(self, width: int, height: int, fill: str = " ") -> None:
        self.width = width
        self.height = height
        self.cells = [[fill] * width for _ in range(height)]

    def put(self, x: int, y: int, ch: str) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cells[y][x] = ch

    def text(self, x: int, y: int, s: str) -> None:
        for i, ch in enumerate(s):
            self.put(x + i, y, ch)

    def walls(self) -> None:
        for x in range(self.width):
            self.put(x, 0, WALL)
            self.put(x, self.height - 1, WALL)
        for y in range(self.height):
            self.put(0, y, WALL)
            self.put(self.width - 1, y, WALL)

    def box(self, r: Rect, label: str = "", title: str = "") -> None:
        """A box-drawing rectangle; `title` sits on the top edge, `label` in the middle."""
        right, bottom = r.x + r.w - 1, r.y + r.h - 1
        for x in range(r.x + 1, right):
            self.put(x, r.y, "─")
            self.put(x, bottom, "─")
        for y in range(r.y + 1, bottom):
            self.put(r.x, y, "│")
            self.put(right, y, "│")
        self.put(r.x, r.y, "┌")
        self.put(right, r.y, "┐")
        self.put(r.x, bottom, "└")
        self.put(right, bottom, "┘")
        if title:
            self.text(r.x + 2, r.y, f" {title} "[: r.w - 3])
        if label:
            label = label[: r.w - 2]
            self.text(r.x + (r.w - len(label)) // 2, r.cy, label)

    def rows(self) -> list[str]:
        return ["".join(row) for row in self.cells]
