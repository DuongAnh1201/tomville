import asyncio
import random
from datetime import datetime, timezone

from tomville.core.models import Agent, AgentStatusChanged, Card, CardChanged, Column, Message, MessageSent, Status
from tomville.core.settings import OfficeSettings
from tomville.core.shapes import PipelineShape
from tomville.core.shapes.pipeline_play import GUESS_SECONDS
from tomville.core.world import World

STAGES = ("planner", "coder", "tester")


def make(stages=STAGES, extra=()):
    world = World(shape=PipelineShape(stages), lead=None, rng=random.Random(1))
    world.resize(110, 28)
    world.load([Agent(n, "codex", Status.IDLE, f"p-{n}") for n in (*stages, *extra)], [])
    return world


def belt(world, stage):
    r = world.office.zones[f"belt:{stage}"]
    return (r.cx, r.y)


def settle(world, seconds=20):
    for _ in range(int(seconds * 10)):
        world.tick(0.1)


def send(world, sender, to, text="next"):
    world.apply(MessageSent(Message(datetime.now(timezone.utc), sender, to, text, "send")))


def status(world, name, new):
    world.apply(AgentStatusChanged(name, world.pets[name].status, new))


def test_stations_in_stage_order_with_done_and_belt():
    office = PipelineShape(STAGES).layout(110, 28, None, ["tester", "planner", "coder", "extra"])
    xs = [office.desks[s].x for s in STAGES]
    assert xs == sorted(xs) and office.desks["_done"].x > xs[-1]
    assert "extra" not in office.desks  # not a stage: waits in the lounge
    row = office.rows[office.zones["belt"].y]
    assert "═" in row and row.count("▶") == len(STAGES)
    assert all(office.zones[f"belt:{s}"].y == office.zones["belt"].y for s in (*STAGES, "_done"))


def test_without_stages_every_worker_is_a_stage():
    office = PipelineShape().layout(110, 28, None, ["a", "b"])
    assert [n for n in office.desks if not n.startswith("_")] == ["a", "b"]


def test_too_many_stages_keep_what_fits():
    office = PipelineShape([f"s{i}" for i in range(20)]).layout(80, 24, None, [])
    assert "_done" in office.desks
    assert all(r.x + r.w <= 79 for r in office.desks.values())


def test_logged_handoff_moves_the_card_along_the_belt():
    world = make()
    world.cards["#12"] = Card("#12", "t", Column.DOING, "planner")
    send(world, "planner", "coder", "your turn")
    assert world.parcels["#12"].cell == belt(world, "planner")
    settle(world)
    assert world.parcels["#12"].cell == belt(world, "coder")


def test_card_label_falls_back_to_the_issue_in_the_text():
    world = make()
    send(world, "coder", "tester", "please test #7")
    assert "#7" in world.parcels


def test_message_that_skips_a_stage_is_not_a_handoff():
    world = make()
    send(world, "planner", "tester", "#9")
    assert world.parcels == {}


def test_unlogged_handoff_is_guessed_and_marked():
    world = make()
    status(world, "planner", Status.DONE)
    settle(world, 5)
    status(world, "coder", Status.WORKING)
    assert world.parcels  # the card moved anyway
    assert world.appearance(world.pets["coder"]).bubble == "? handoff"


def test_no_guess_when_the_handoff_was_logged():
    world = make()
    send(world, "planner", "coder", "#3")
    status(world, "planner", Status.DONE)
    status(world, "coder", Status.WORKING)
    assert world.appearance(world.pets["coder"]).bubble != "? handoff"


def test_no_guess_after_the_window():
    world = make()
    status(world, "planner", Status.DONE)
    settle(world, GUESS_SECONDS + 5)
    status(world, "coder", Status.WORKING)
    assert world.parcels == {}


def test_last_stage_done_drops_the_card_into_done():
    world = make()
    send(world, "coder", "tester", "#5")
    settle(world)
    status(world, "tester", Status.DONE)
    settle(world)
    assert world.parcels["#5"].cell == belt(world, "_done")


def test_closed_issue_moves_its_card_to_done():
    world = make()
    send(world, "planner", "coder", "#8")
    settle(world)
    world.apply(CardChanged(Card("#8", "t", Column.DONE), Column.DOING))
    settle(world)
    assert world.parcels["#8"].cell == belt(world, "_done")


def test_app_draws_the_belt_and_cards(tmp_path):
    from tomville.tui.app import TomvilleApp
    from tomville.tui.office import OfficeView

    settings = OfficeSettings(source="tasks-md", team="pipeline", stages=STAGES)

    async def run():
        app = TomvilleApp(project=tmp_path, settings=settings, live=False)
        async with app.run_test(size=(140, 40)) as pilot:
            app.load_snapshot([Agent(n, "codex", Status.IDLE, f"p-{n}") for n in STAGES], [])
            await pilot.pause()
            app.handle_event(MessageSent(Message(datetime.now(timezone.utc), "planner", "coder", "#12", "send")))
            await pilot.pause()
            return str(app.query_one(OfficeView).render())

    text = asyncio.run(run())
    assert "planner" in text and "DONE" in text and "═" in text and "[#12]" in text
