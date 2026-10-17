"""Lead + workers: the boss at the top with the board beside it, one named desk per
worker facing the boss, and the lounge, review zone and door along the bottom.
Designed by Tom (see idea.md, "Lead + workers layout").
"""

from __future__ import annotations

from tomville.core.shapes.base import Canvas, OfficeMap, Rect

MIN_WIDTH = 40
MIN_HEIGHT = 16

DESK_W, DESK_H = 10, 3
BOSS_W, BOSS_H = 12, 3
DESK_GAP = 4
MIN_DESKS = 3  # always show a few desks, so empty ones wait for new workers


class LeadShape:
    name = "lead"

    def layout(self, width: int, height: int, lead: str | None, workers: list[str]) -> OfficeMap:
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return _too_small(width, height)

        c = Canvas(width, height)
        c.walls()
        zones: dict[str, Rect] = {}
        desks: dict[str, Rect] = {}
        seats: dict[str, tuple[int, int]] = {}

        # Board on the wall, top left.
        board_w = min(30, max(20, (width - 4) // 2 - 2))
        board = Rect(2, 1, board_w, 5)
        c.box(board, title="BOARD")
        c.text(board.x + 2, board.y + 1, "Todo   Doing  Review"[: board.w - 3])
        zones["board"] = board
        zones["board_cards"] = Rect(board.x + 1, board.y + 2, board.w - 2, board.h - 3)

        # Boss desk, top, centred in the space right of the board. The boss sits
        # behind it (above), facing the workers.
        left, right = board.x + board.w + 2, width - 2
        boss = Rect(left + max(0, (right - left - BOSS_W) // 2), 2, BOSS_W, BOSS_H)
        c.box(boss, label="BOSS")
        zones["boss_desk"] = boss
        boss_name = lead or ""
        desks[boss_name] = boss
        seats[boss_name] = (boss.cx, boss.y - 1)

        # Bottom row: lounge, review zone and the door in the right wall.
        bottom = height - 2
        zones["lounge"] = Rect(1, bottom - 2, 18, 3)
        c.text(3, bottom, "LOUNGE")
        zones["review"] = Rect(width // 2 - 6, bottom - 2, 12, 3)
        c.text(width // 2 - 3, bottom, "REVIEW")
        zones["door"] = Rect(width - 1, bottom - 1, 1, 2)
        c.put(width - 1, bottom - 1, " ")
        c.put(width - 1, bottom, " ")
        c.text(width - 7, bottom, "DOOR")

        # Worker desks in rows below the boss, each with its name, seat below.
        per_row = max(1, (width - 4 + DESK_GAP) // (DESK_W + DESK_GAP))
        n_desks = max(len(workers), MIN_DESKS)
        first_y = max(board.y + board.h + 2, boss.y + boss.h + 3)
        last_y = bottom - 4 - DESK_H  # keep a walkway above the bottom zones
        n_rows = min(-(-n_desks // per_row), (last_y - first_y) // (DESK_H + 2) + 1)
        rows_h = n_rows * (DESK_H + 2) - 2
        top = first_y + max(0, (last_y + DESK_H - first_y - rows_h) // 2)
        names = workers + [""] * (n_desks - len(workers))
        for i, name in enumerate(names):
            row, col = divmod(i, per_row)
            y = top + row * (DESK_H + 2)
            if y > last_y:
                break  # no room: extra workers stand in the lounge
            in_row = min(per_row, n_desks - row * per_row)
            row_w = in_row * DESK_W + (in_row - 1) * DESK_GAP
            x = (width - row_w) // 2 + col * (DESK_W + DESK_GAP)
            desk = Rect(x, y, DESK_W, DESK_H)
            c.box(desk, label=name)
            key = name or f"_{i}"
            desks[key] = desk
            seats[key] = (desk.cx, desk.y + desk.h)

        return OfficeMap(width, height, c.rows(), zones, desks, seats)


def _too_small(width: int, height: int) -> OfficeMap:
    c = Canvas(max(width, 1), max(height, 1))
    msg = f"Window too small: need {MIN_WIDTH} × {MIN_HEIGHT}"
    c.text(max(0, (width - len(msg)) // 2), height // 2, msg[:width])
    return OfficeMap(width, height, c.rows())
