"""Pipeline: stations in a row joined by a conveyor belt, planner → coder → tester.

Each stage is an agent at its own station; a card rides the belt from one
station to the next on each handoff and drops into DONE after the last stage.
Agents that aren't stages wait in the lounge. The board hangs on the wall and
the lounge, review zone and door run along the bottom, as in the lead office.
"""

from __future__ import annotations

from tomville.core.shapes.base import Canvas, OfficeMap, Rect
from tomville.core.shapes.lead import MIN_HEIGHT, MIN_WIDTH, _too_small

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
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return _too_small(width, height)

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

        bottom = height - 2
        zones["lounge"] = Rect(1, bottom - 2, 18, 3)
        c.text(3, bottom, "LOUNGE")
        zones["review"] = Rect(width // 2 - 6, bottom - 2, 12, 3)
        c.text(width // 2 - 3, bottom, "REVIEW")
        zones["door"] = Rect(width - 1, bottom - 1, 1, 2)
        c.put(width - 1, bottom - 1, " ")
        c.put(width - 1, bottom, " ")
        c.text(width - 7, bottom, "DOOR")

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
        zones["done"] = desks["_done"]
        zones["belt"] = Rect(x0, belt_y, row_w, 1)
        for x in range(x0, x0 + row_w):
            c.put(x, belt_y, BELT)
        for left, right in zip(boxes, boxes[1:]):
            c.put((desks[left].x + desks[left].w + desks[right].x) // 2, belt_y, ARROW)

        return OfficeMap(width, height, c.rows(), zones, desks, seats)
