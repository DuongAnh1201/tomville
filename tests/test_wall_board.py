"""The cards on the office wall board (#62)."""

import random

import pytest

from tomville.core.models import Agent, Card, CardChanged, Column, Status
from tomville.core.shapes import LeadShape
from tomville.core.world import World
from tomville.core.sprites import Sprites
from tomville.tui.office import OfficeView

NAMES = ["claude", "codex1", "claude2"]


def make(cards, size=(80, 24)):
    world = World(LeadShape(), lead="claude", rng=random.Random(1), still=True)
    world.resize(*size)
    world.load([Agent(n, "claude", Status.IDLE, f"p-{n}") for n in NAMES], cards)
    return world


def render(world, monkeypatch):
    monkeypatch.setattr(OfficeView, "size", property(lambda self: type("S", (), {"width": world.office.width, "height": world.office.height})()))
    return OfficeView(world, Sprites("ascii")).render().plain.split("\n")


def card(n, column, agent=None):
    return Card(f"#{n}", f"task {n}", column, agent)


def test_cards_sit_under_their_headings(monkeypatch):
    world = make([card(58, Column.DOING, "codex1"), card(59, Column.TODO), card(61, Column.TODO), card(7, Column.REVIEW), card(3, Column.DONE)])
    rows = render(world, monkeypatch)
    zone = world.office.zones["board_cards"]
    heading = rows[zone.y - 1]
    for text, column in (("Todo", 0), ("Doing", 1), ("Review", 2)):
        x = heading.index(text)
        assert rows[zone.y][x:x + 3] in {"#59", "#58", "#7 "}
    assert "#59" in rows[zone.y] and "#61" in rows[zone.y + 1]
    assert rows[zone.y][heading.index("Doing"):].startswith("#58")
    assert rows[zone.y][heading.index("Review"):].startswith("#7")
    assert "#3" not in "".join(rows[zone.y:zone.y + zone.h])


def test_overflow_shows_the_rest_as_a_count(monkeypatch):
    world = make([card(n, Column.TODO) for n in range(10, 15)])
    cells = world.board_cells()
    zone = world.office.zones["board_cards"]
    assert [t for _, _, t, _ in cells] == ["#10", "+4"][: zone.h] or zone.h > 2
    assert cells[-1][2] == f"+{5 - (zone.h - 1)}"
    assert len(cells) == zone.h


def test_a_card_moves_column_on_the_wall():
    world = make([card(5, Column.TODO, "codex1")])
    x_todo = world.board_cells()[0][0]
    world.apply(CardChanged(card(5, Column.DOING, "codex1"), Column.TODO))
    assert world.board_cells()[0][0] > x_todo


def test_card_colour_follows_the_agent(monkeypatch):
    world = make([card(1, Column.TODO, "codex1"), card(2, Column.DOING, "claude2"), card(3, Column.REVIEW)])
    monkeypatch.setattr(OfficeView, "size", property(lambda self: type("S", (), {"width": 80, "height": 24})()))
    view = OfficeView(world, Sprites("ascii"))
    styles = {t: s for y, row in view._overlays().items() for x, t, s in row if t.startswith("#")}
    assert styles["#1"] != styles["#2"] and "bold" in styles["#1"] and styles["#3"] == "dim"


@pytest.mark.parametrize("size", [(30, 10), (40, 10), (60, 12), (80, 24), (112, 42)])
def test_cards_stay_inside_the_board(size):
    world = make([card(n, Column(c)) for n, c in zip(range(100, 130), ["todo", "doing", "review"] * 10)], size)
    zone = world.office.zones.get("board_cards")
    for x, y, text, _ in world.board_cells():
        assert zone and zone.x <= x and x + len(text) <= zone.x + zone.w and zone.y <= y < zone.y + zone.h
