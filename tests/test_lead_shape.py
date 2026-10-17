from tomville.core.shapes import LeadShape
from tomville.core.shapes.lead import MIN_DESKS


def layout(w=128, h=30, lead="claude", workers=("codex1", "claude2")):
    return LeadShape().layout(w, h, lead, list(workers))


def test_every_row_fills_the_width():
    m = layout()
    assert len(m.rows) == 30
    assert all(len(r) == 128 for r in m.rows)


def test_named_desks_and_empty_desk():
    m = layout()
    assert {"claude", "codex1", "claude2"} <= m.desks.keys()
    assert len(m.desks) == 1 + MIN_DESKS  # boss + two workers + one empty
    text = m.text()
    assert "codex1" in text and "claude2" in text and "BOSS" in text and "BOARD" in text


def test_boss_sits_above_workers_and_board_beside_boss():
    m = layout()
    boss_y = m.seats["claude"][1]
    assert all(m.seats[w][1] > boss_y for w in ("codex1", "claude2"))
    assert m.zones["board"].y <= m.zones["boss_desk"].y
    assert m.zones["board"].x + m.zones["board"].w <= m.zones["boss_desk"].x


def test_zones_and_seats_inside_the_office():
    m = layout()
    for name in ("lounge", "review", "door", "board", "boss_desk"):
        r = m.zones[name]
        assert 0 <= r.x and r.x + r.w <= m.width and 0 <= r.y and r.y + r.h <= m.height, name
    for x, y in m.seats.values():
        assert 0 < x < m.width - 1 and 0 < y < m.height - 1


def test_desks_do_not_overlap_bottom_zones():
    m = layout(h=20, workers=[f"w{i}" for i in range(12)])
    lounge_top = m.zones["lounge"].y
    assert all(d.y + d.h <= lounge_top for d in m.desks.values())


def test_too_small_window():
    m = layout(w=29, h=9)
    assert "too small" in m.text() and "need 30 × 10" in m.text()
