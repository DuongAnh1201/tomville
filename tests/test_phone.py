"""Telegram in the office: 📱 from the door, replies to tom, approvals (#59)."""

import asyncio
import random
from datetime import datetime, timezone

from tomville.core.models import Agent, Message, MessageSent, Status
from tomville.core.shapes import LeadShape
from tomville.core.sprites import Sprites
from tomville.core.world import World
from tomville.tui.app import EventsPanel, TomvilleApp
from tomville.tui.office import OfficeView

NAMES = ["claude", "codex1", "secretary"]


def make(still=False):
    world = World(LeadShape(), lead="claude", rng=random.Random(1), still=still)
    world.resize(100, 30)
    world.load([Agent(n, "claude", Status.IDLE, f"p-{n}") for n in NAMES], [])
    return world


def sent(sender, to, text, via):
    return MessageSent(Message(datetime.now(timezone.utc), sender, to, text, via))


def bubble(world, name):
    return world.pets[name].bubbles[0][0] if world.pets[name].bubbles else None


def test_a_phone_message_walks_in_from_the_door_to_the_target():
    world = make()
    door = world._door_cell()
    world.apply(sent("tom", "codex1", "run the tests again", "telegram"))
    (x, y, label), = world.parcel_cells()
    assert label == "📱" and (x, y) == door
    assert bubble(world, "codex1") == "📱 run the tests again"
    for _ in range(200):
        world.tick(0.1)
        if not world.parcels:
            break
    assert not world.parcels  # delivered, then gone
    assert "tom" not in world.pets  # tom has no pet


def test_a_phone_message_to_the_lead_reaches_the_lead_desk():
    world = make(still=True)
    world.apply(sent("tom", "claude", "start issue #12", "telegram"))
    world.tick(0.1)
    (x, y, _), = world.parcel_cells()
    assert (x, y) == world._front_of_desk("claude")


def test_a_reply_to_tom_is_the_senders_bubble_and_no_walk():
    world = make()
    world.apply(sent("claude", "tom", "<b>done</b>\nPR #5", "telegram"))
    assert bubble(world, "claude") == "📱 → tom: done PR #5"
    assert not world.parcels and not world.pets["claude"].script


def test_approvals_show_a_tick_or_a_cross_over_the_agent():
    world = make()
    world.apply(sent("tom", "codex1", "✅ approved by Tom\nRun: uv run pytest", "telegram-approval"))
    world.apply(sent("tom", "secretary", "❌ declined\nRun: rm -rf x", "telegram-approval"))
    assert bubble(world, "codex1") == "✅" and bubble(world, "secretary") == "❌"


def test_errors_and_unknown_targets_do_nothing():
    world = make()
    world.apply(sent("tomville", "codex1", "couldn't reach codex1", "telegram-error"))
    world.apply(sent("tom", "ghost", "hello", "telegram"))
    assert bubble(world, "codex1") is None and not world.parcels


def test_the_envelope_is_drawn_over_the_map(monkeypatch):
    world = make(still=True)
    world.apply(sent("tom", "codex1", "hi", "telegram"))
    world.tick(0.1)
    monkeypatch.setattr(OfficeView, "size", property(lambda self: type("S", (), {"width": 100, "height": 30})()))
    assert "[📱]" in OfficeView(world, Sprites("ascii")).render().plain


def test_the_events_panel_shows_the_phone(tmp_path):
    async def run():
        app = TomvilleApp(project=tmp_path, live=False)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app.handle_event(sent("tom", "codex1", "run the tests", "telegram"))
            app.handle_event(sent("claude", "tom", "<i>all green</i>", "telegram"))
            return str(app.query_one(EventsPanel).lines)

    lines = asyncio.run(run())
    assert "📱 tom → codex1: run the tests" in lines and "📱 claude → tom: all green" in lines
