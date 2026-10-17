"""The team-shape plug-in interface and the office map it produces.

A shape draws the static office (walls, desks, zones) and says where each agent
sits. Pets, cards and bubbles are drawn on top by the renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

WALL = "▓"

# Offices at least FULL_WIDTH × FULL_HEIGHT get the full layout (boxed desks, board on
# the wall); smaller ones down to MIN_WIDTH × MIN_HEIGHT get the compact one (name tags
# for desks, no board). Below that there is no room to draw an office.
FULL_WIDTH, FULL_HEIGHT = 40, 18
MIN_WIDTH, MIN_HEIGHT = 30, 10


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


def too_small(width: int, height: int) -> bool:
    return width < MIN_WIDTH or height < MIN_HEIGHT


def is_compact(width: int, height: int) -> bool:
    return width < FULL_WIDTH or height < FULL_HEIGHT


def too_small_map(width: int, height: int) -> OfficeMap:
    c = Canvas(max(width, 1), max(height, 1))
    for i, msg in enumerate(("Window too small", f"need {MIN_WIDTH} × {MIN_HEIGHT} cells")):
        c.text(max(0, (width - len(msg)) // 2), max(0, height // 2 - 1 + i), msg[:width])
    return OfficeMap(width, height, c.rows())


def bottom_zones(c: Canvas, zones: dict[str, Rect], compact: bool) -> None:
    """The lounge, review zone and door along the bottom (the door in the right wall)."""
    width, height = c.width, c.height
    bottom = height - 2
    rows = 2 if compact else 3
    lounge_w, review_w = (min(10, (width - 2) // 3), 8) if compact else (18, 12)
    zones["lounge"] = Rect(1, bottom - rows + 1, lounge_w, rows)
    c.text(2 if compact else 3, bottom, "LOUNGE"[: lounge_w - 1] if compact else "LOUNGE")
    zones["review"] = Rect(width // 2 - review_w // 2, bottom - rows + 1, review_w, rows)
    c.text(width // 2 - 3 + (1 if compact else 0), bottom, "REVIEW"[: review_w])
    zones["door"] = Rect(width - 1, bottom - 1, 1, 2)
    c.put(width - 1, bottom - 1, " ")
    c.put(width - 1, bottom, " ")
    c.text(width - 7 if not compact else width - 6, bottom, "DOOR")


def tag(c: Canvas, r: Rect, name: str) -> None:
    """A one-row desk: the name in brackets, cut to fit; empty desks are `[    ]`."""
    c.text(r.x, r.y, f"[{name[: r.w - 2]:^{r.w - 2}}]")


def tag_widths(names: list[str], room: int, gap: int, longest: int = 9) -> int:
    """One tag width for all `names` in a row of `room` cells: as wide as the longest name wants, shrunk to fit."""
    want = max([len(n) for n in names] + [4]) + 2
    return max(5, min(want, longest, (room - (len(names) - 1) * gap) // max(1, len(names))))


def best_fit(full: OfficeMap, compact: Callable[[], OfficeMap], names: list[str]) -> OfficeMap:
    """The full office, unless the compact one gives more of `names` a seat."""
    seated = sum(n in full.seats for n in names)
    if seated == len(names):
        return full
    small = compact()
    return small if sum(n in small.seats for n in names) > seated else full
