"""Lead + workers: the boss at the top with the board beside it, one named desk per
worker facing the boss, and the lounge, review zone and door along the bottom.
Designed by Tom (see idea.md, "Lead + workers layout").

Offices smaller than FULL_WIDTH × FULL_HEIGHT get a compact version: the desks are
one-row name tags, the board is left out, and the bottom zones are two rows high.
"""

from __future__ import annotations

from tomville.core.shapes.base import (
    MIN_HEIGHT,
    MIN_WIDTH,
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

DESK_W, DESK_H = 10, 3
BOSS_W, BOSS_H = 12, 3
DESK_GAP = 4
MIN_DESKS = 3  # always show a few desks, so empty ones wait for new workers
MAX_DESK_W, MAX_GAP = 16, 16  # on big screens the desks grow and spread, up to here

TAG_GAP = 2
TAG_PITCH = 3  # a tag row, its seat row and one free row


class LeadShape:
    name = "lead"

    def layout(self, width: int, height: int, lead: str | None, workers: list[str]) -> OfficeMap:
        if too_small(width, height):
            return too_small_map(width, height)
        if is_compact(width, height):
            return _compact(width, height, lead, workers)
        return best_fit(_full(width, height, lead, workers), lambda: _compact(width, height, lead, workers), workers)


def _full(width: int, height: int, lead: str | None, workers: list[str]) -> OfficeMap:
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

    bottom_zones(c, zones, compact=False)
    bottom = height - 2

    # Worker desks in rows below the boss, each with its name, seat below. On wide
    # screens the desks grow a little and spread out instead of huddling.
    desk_w = max(DESK_W, min(MAX_DESK_W, width // 12))
    per_row = max(1, (width - 4 + DESK_GAP) // (desk_w + DESK_GAP))
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
        gap = max(DESK_GAP, min(MAX_GAP, (width - 4 - in_row * desk_w) // (in_row + 1)))
        row_w = in_row * desk_w + (in_row - 1) * gap
        x = (width - row_w) // 2 + col * (desk_w + gap)
        desk = Rect(x, y, desk_w, DESK_H)
        c.box(desk, label=name)
        key = name or f"_{i}"
        desks[key] = desk
        seats[key] = (desk.cx, desk.y + desk.h)

    return OfficeMap(width, height, c.rows(), zones, desks, seats)


def _compact(width: int, height: int, lead: str | None, workers: list[str]) -> OfficeMap:
    """Small screens: name tags instead of boxed desks, no board."""
    c = Canvas(width, height)
    c.walls()
    zones: dict[str, Rect] = {}
    desks: dict[str, Rect] = {}
    seats: dict[str, tuple[int, int]] = {}
    bottom_zones(c, zones, compact=True)

    boss = Rect((width - 6) // 2, 2, 6, 1)
    tag(c, boss, "BOSS")
    zones["boss_desk"] = boss
    boss_name = lead or ""
    desks[boss_name] = boss
    seats[boss_name] = (boss.cx, boss.y - 1)

    # Tag rows below the boss, as many as fit above the walkway over the bottom zones.
    first_y, last_y = boss.y + 2, zones["lounge"].y - 3
    n_rows = (last_y - first_y) // TAG_PITCH + 1 if last_y >= first_y else 0
    room = width - 2
    n_desks = max(len(workers), MIN_DESKS)
    tw = tag_widths(workers, room, TAG_GAP)
    per_row = max(1, min(n_desks, (room + TAG_GAP) // (tw + TAG_GAP)))
    used_rows = max(0, min(n_rows, -(-n_desks // per_row)))
    top = first_y + ((last_y - first_y) - (used_rows - 1) * TAG_PITCH) // 2 if used_rows else first_y
    names = (workers + [""] * (n_desks - len(workers)))[: used_rows * per_row]
    for i, name in enumerate(names):
        row, col = divmod(i, per_row)
        in_row = min(per_row, len(names) - row * per_row)
        gap = max(1, min(6, (room - in_row * tw) // (in_row + 1)))
        x = (width - (in_row * tw + (in_row - 1) * gap)) // 2 + col * (tw + gap)
        desk = Rect(x, top + row * TAG_PITCH, tw, 1)
        tag(c, desk, name)
        key = name or f"_{i}"
        desks[key] = desk
        seats[key] = (desk.cx, desk.y + 1)

    return OfficeMap(width, height, c.rows(), zones, desks, seats)


__all__ = ["LeadShape", "MIN_DESKS", "MIN_HEIGHT", "MIN_WIDTH"]
