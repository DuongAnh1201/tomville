"""Both team shapes at every screen size: nothing is lost on small or large offices."""

import random

import pytest

from tomville.core.models import Agent, Status
from tomville.core.shapes import LeadShape
from tomville.core.shapes.base import MIN_HEIGHT, MIN_WIDTH, WALL
from tomville.core.shapes.pipeline import PipelineShape
from tomville.core.sprites import Sprites
from tomville.core.world import World
from tomville.tui.office import OfficeView

# Office areas measured by the demo on real screens (issue #28), plus the extremes.
SIZES = [(30, 10), (40, 10), (60, 12), (80, 14), (64, 28), (112, 42), (164, 58), (250, 70), (40, 16), (40, 18), (60, 20)]
STAGES = ["planner", "coder", "tester"]
TEAMS = {
    "lead": (LeadShape(), "claude", ["claude", "codex1", "claude2", "codex2"]),
    "pipeline": (PipelineShape(STAGES), None, STAGES + ["helper"]),
}


def world_for(team, width, height, status=Status.WORKING):
    shape, lead, names = TEAMS[team]
    world = World(shape, lead=lead, rng=random.Random(1))
    world.resize(width, height)
    world.load([Agent(n, "claude" if n == lead else "codex", status, f"p-{n}") for n in names], [])
    return world


def overlap(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


@pytest.mark.parametrize("team", TEAMS)
@pytest.mark.parametrize("size", SIZES)
def test_office_fits_the_screen(team, size):
    width, height = size
    world = world_for(team, width, height)
    office = world.office
    assert "too small" not in office.text()
    assert len(office.rows) == height and all(len(r) == width for r in office.rows)

    # Every seat, and every pet and its name drawn there, is inside the walls.
    stages = TEAMS[team][2][:3] if team == "pipeline" else None
    for name, (x, y) in office.seats.items():
        assert 0 < x < width - 2 and 0 < y < height - 1, (name, x, y)
    for app in world.appearances():
        assert app.name in office.seats or team == "pipeline" and app.name not in STAGES
        label_w = len(app.label)
        assert 1 <= app.x and app.x + 1 <= width - 2, app
        assert 1 <= app.label_x and app.label_x + label_w <= width - 1, app
        assert 1 <= app.y <= height - 2, app
    if stages:
        assert all(world.pets[s].cell == office.seats[s] for s in stages)
    else:
        assert all(world.pets[n].cell == office.seats[n] for n in ("claude", "codex1", "claude2"))

    # Desks do not overlap each other, the walls or the bottom zones.
    desks = list(office.desks.items())
    for i, (name_a, a) in enumerate(desks):
        assert a.x >= 1 and a.x + a.w <= width - 1 and a.y >= 1 and a.y + a.h <= height - 1, name_a
        for name_b, b in desks[i + 1 :]:
            assert not overlap(a, b), (name_a, name_b)
        for zone in ("lounge", "review"):
            assert not overlap(a, office.zones[zone]), (name_a, zone)
        assert a.y + a.h <= office.zones["lounge"].y, name_a

    # The door is in the right wall and every pet can walk to it and to the lounge.
    door = office.zones["door"]
    assert door.x == width - 1 and 0 < door.y and door.y + door.h < height
    assert office.rows[door.y][door.x] != WALL
    for pet in world.pets.values():
        assert world._find_path(pet.cell, (door.x, door.y)) is not None, pet.name
        assert world._find_path(pet.cell, (office.zones["lounge"].x + 1, office.zones["lounge"].y)) is not None, pet.name


@pytest.mark.parametrize("team", TEAMS)
def test_too_small_says_the_minimum(team):
    shape = TEAMS[team][0]
    for size in ((MIN_WIDTH - 1, 20), (60, MIN_HEIGHT - 1), (20, 5)):
        text = shape.layout(*size, TEAMS[team][1], ["a"]).text()
        assert "too small" in text.lower()
    shape.layout(1, 1, None, [])  # tiny windows only need to not crash
    assert "need 30 × 10" in shape.layout(MIN_WIDTH - 1, 20, None, []).text()


@pytest.mark.parametrize("team", TEAMS)
def test_layout_follows_the_size_live(team):
    world = world_for(team, 130, 40)
    big = dict(world.office.desks)
    world.resize(30, 10)
    assert world.office.width == 30 and "BOARD" not in world.office.text()
    assert all(world.pets[n].cell == world.office.seats[n] for n in world.office.seats if n in world.pets)
    world.resize(130, 40)
    assert world.office.desks == big and "BOARD" in world.office.text()


@pytest.mark.parametrize("team", TEAMS)
def test_big_screens_do_not_leave_the_team_huddled(team):
    office = world_for(team, 250, 70).office
    xs = [d.x for n, d in office.desks.items() if n != ""]
    assert max(xs) - min(xs) > 250 // 4  # spread over at least a quarter of the width


@pytest.mark.parametrize("team", TEAMS)
@pytest.mark.parametrize("size", [(30, 10), (80, 14), (250, 70)])
def test_every_pet_and_name_is_drawn(team, size, monkeypatch):
    world = world_for(team, *size)

    class Size:
        width, height = size

    view = OfficeView(world, Sprites("ascii"))
    monkeypatch.setattr(OfficeView, "size", property(lambda self: Size))
    text = view.render().plain
    for name in TEAMS[team][2]:
        assert name in text, name
