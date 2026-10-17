"""Pipeline: stations in a row joined by a conveyor belt, planner → coder → tester.

Each stage is an agent at its own station; a card rides the belt from one
station to the next on each handoff and drops into DONE after the last stage.
Agents that aren't stages wait in the lounge. The board hangs on the wall and
the lounge, review zone and door run along the bottom, as in the lead office.
"""

from __future__ import annotations

from tomville.core.shapes.base import (
    Canvas,
    OfficeMap,
    Rect,
    best_fit,
    bottom_zones,
    is_compact,
    tag,
    tag_widths,
    too_small,
    too_small_map,
)

STATION_W, STATION_H = 10, 3
BELT = "═"
ARROW = "▶"


class PipelineShape:
    name = "pipeline"

    def __init__(self, stages: list[str] | tuple[str, ...] = ()) -> None:
        self.stages = list(stages)

    def order(self, workers: list[str]) -> list[str]:
        """The stages, left to right: the configured ones, else every worker in turn."""
        return self.stages or list(workers)

    def layout(self, width: int, height: int, lead: str | None, workers: list[str]) -> OfficeMap:
        if too_small(width, height):
            return too_small_map(width, height)
        if is_compact(width, height):
            return self._compact(width, height, workers)
        stages = self.order(workers)
        return best_fit(self._full(width, height, workers), lambda: self._compact(width, height, workers), stages)

    def _full(self, width: int, height: int, workers: list[str]) -> OfficeMap:
        c = Canvas(width, height)
        c.walls()
        zones: dict[str, Rect] = {}
        desks: dict[str, Rect] = {}
        seats: dict[str, tuple[int, int]] = {}

        board_w = min(30, max(20, (width - 4) // 2 - 2))
        board = Rect(2, 1, board_w, 5)
        c.box(board, title="BOARD")
        c.text(board.x + 2, board.y + 1, "Todo   Doing  Review"[: board.w - 3])
        zones["board"] = board
        zones["board_cards"] = Rect(board.x + 1, board.y + 2, board.w - 2, board.h - 3)

        bottom_zones(c, zones, compact=False)
        bottom = height - 2

        # Stations and the DONE box share one row; the belt runs under their seats.
        stages = self.order(workers)
        boxes = stages + ["_done"]
        gap = max(2, (width - 4 - len(boxes) * STATION_W) // max(1, len(boxes)))
        row_w = len(boxes) * STATION_W + (len(boxes) - 1) * gap
        if row_w > width - 4:  # too many stages for one row: keep what fits
            fit = max(1, (width - 4 + gap) // (STATION_W + gap))
            boxes = stages[: fit - 1] + ["_done"]
            row_w = len(boxes) * STATION_W + (len(boxes) - 1) * gap
        top = board.y + board.h + 2
        y = top + max(0, (bottom - 7 - top - STATION_H) // 2)
        belt_y = y + STATION_H + 2
        x0 = (width - row_w) // 2
        for i, name in enumerate(boxes):
            box = Rect(x0 + i * (STATION_W + gap), y, STATION_W, STATION_H)
            c.box(box, label="DONE" if name == "_done" else name)
            desks[name] = box
            zones[f"belt:{name}"] = Rect(box.x, belt_y, box.w, 1)
            if name != "_done":
                seats[name] = (box.cx, box.y + box.h)
        self._belt(c, zones, desks, boxes, x0, row_w, belt_y)
        return OfficeMap(width, height, c.rows(), zones, desks, seats)

    def _compact(self, width: int, height: int, workers: list[str]) -> OfficeMap:
        """Small screens: name tags for stations, no board.

        Neighbouring stations sit on alternate seat rows so their names don't run
        into each other; the belt runs under both.
        """
        c = Canvas(width, height)
        c.walls()
        zones: dict[str, Rect] = {}
        desks: dict[str, Rect] = {}
        seats: dict[str, tuple[int, int]] = {}
        bottom_zones(c, zones, compact=True)

        stages = self.order(workers)
        room, min_w, gap = width - 2, 5, 1
        fit = max(1, (room + gap) // (min_w + gap))  # boxes that fit in one row, DONE included
        boxes = stages[: fit - 1] + ["_done"]
        tw = tag_widths([("DONE" if n == "_done" else n) for n in boxes], room, gap)
        gap = max(1, min(6, (room - len(boxes) * tw) // (len(boxes) + 1)))
        row_w = len(boxes) * tw + (len(boxes) - 1) * gap
        free = zones["lounge"].y - 2  # last free row: keep a walkway over the bottom zones
        y = 1 + max(0, (free - 4) // 2)
        belt_y = y + 3
        x0 = (width - row_w) // 2
        for i, name in enumerate(boxes):
            box = Rect(x0 + i * (tw + gap), y, tw, 1)
            tag(c, box, "DONE" if name == "_done" else name)
            desks[name] = box
            zones[f"belt:{name}"] = Rect(box.x, belt_y, box.w, 1)
            if name != "_done":
                seats[name] = (box.cx, box.y + 1 + i % 2)
        self._belt(c, zones, desks, boxes, x0, row_w, belt_y)
        return OfficeMap(width, height, c.rows(), zones, desks, seats)

    @staticmethod
    def _belt(c: Canvas, zones, desks, boxes, x0: int, row_w: int, belt_y: int) -> None:
        zones["done"] = desks["_done"]
        zones["belt"] = Rect(x0, belt_y, row_w, 1)
        for x in range(x0, x0 + row_w):
            c.put(x, belt_y, BELT)
        for left, right in zip(boxes, boxes[1:]):
            c.put((desks[left].x + desks[left].w + desks[right].x) // 2, belt_y, ARROW)
