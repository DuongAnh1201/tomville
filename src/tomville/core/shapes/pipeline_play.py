"""What happens in the pipeline office: cards ride the belt from stage to stage.

A handoff is stage N passing work to stage N+1. Tomville knows about it in two ways:

- **Logged:** stage N sends stage N+1 a message (`tmv send` or the Claude hook).
  The card moves at once.
- **Guessed:** with no message, stage N turning `done` and stage N+1 turning
  `working` within GUESS_SECONDS is taken as a handoff. The card moves too, and
  the receiver shows "?", so the office never claims more than it knows.

When the last stage is done, its card drops into DONE.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tomville.core.models import Card, Column, Status

if TYPE_CHECKING:
    from tomville.core.world import Pet, World

GUESS_SECONDS = 30.0
NO_CARD = "✉"


class PipelinePlay:
    def __init__(self) -> None:
        self.done_at: dict[str, float] = {}  # stage -> world time it last turned done
        self.logged_at: dict[str, float] = {}  # receiver -> world time of its last logged handoff

    # --- hooks ------------------------------------------------------------

    def on_message(self, world: World, sender: str | None, to: str, text: str) -> None:
        stages = _stages(world)
        if sender in stages and to in stages and stages.index(to) == stages.index(sender) + 1:
            self.logged_at[to] = world.time
            self._handoff(world, sender, to, _card_label(world, sender, text))

    def on_status(self, world: World, pet: Pet, old: Status, new: Status) -> None:
        stages = _stages(world)
        if pet.name not in stages:
            return
        i = stages.index(pet.name)
        if new is Status.DONE:
            self.done_at[pet.name] = world.time
            if i == len(stages) - 1:
                label = self._label_at(world, pet.name)
                if label:
                    self._to_done(world, label)
        elif new is Status.WORKING and i > 0:
            prev = stages[i - 1]
            recent_done = world.time - self.done_at.get(prev, float("-inf")) <= GUESS_SECONDS
            recent_log = world.time - self.logged_at.get(pet.name, float("-inf")) <= GUESS_SECONDS
            if recent_done and not recent_log:
                self._handoff(world, prev, pet.name, self._label_at(world, prev) or NO_CARD)
                world.say(pet.name, "? handoff")

    def on_card(self, world: World, card: Card, prev: Card | None) -> None:
        if card.column is Column.DONE and card.id in world.parcels:
            self._to_done(world, card.id)

    # --- moves ------------------------------------------------------------

    def _handoff(self, world: World, sender: str, to: str, label: str) -> None:
        office = world.office
        if office is None:
            return
        start, goal = office.zones.get(f"belt:{sender}"), office.zones.get(f"belt:{to}")
        if start is None or goal is None:
            return
        world.move_parcel(label, (goal.cx, goal.y), start=(start.cx, start.y))

    def _to_done(self, world: World, label: str) -> None:
        office = world.office
        belt = office.zones.get("belt:_done") if office else None
        if belt is not None:
            world.move_parcel(label, (belt.cx, belt.y))

    def _label_at(self, world: World, stage: str) -> str | None:
        """The card resting at `stage`'s spot on the belt, else that stage's task."""
        office = world.office
        spot = office.zones.get(f"belt:{stage}") if office else None
        if spot is not None:
            for label, parcel in world.parcels.items():
                if not parcel.path and parcel.cell == (spot.cx, spot.y):
                    return label
        return world.task_of(stage)


def _stages(world: World) -> list[str]:
    office = world.office
    if office is None:
        return []
    return [name for name in office.desks if not name.startswith("_")]


def _card_label(world: World, sender: str, text: str) -> str:
    """Which card a message hands over: the sender's task, a "#12" in the text, or ✉."""
    task = world.task_of(sender)
    if task:
        return task
    found = re.search(r"#\d+", text)
    return found.group(0) if found else NO_CARD
