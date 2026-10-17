"""What happens in the lead + workers office: the handover and "ready for review".

Step by step as in README.md: a card assigned to a worker sends the boss to the
worker's desk ("#12 is yours"); the boss walks back and the worker says
"checking issues…"; when the card moves to Doing the worker says "on it: #12".
A worker that finishes walks to the boss desk ("#12 ready for review") and then
on to the review zone; a closed issue makes the boss say "merged ✓".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tomville.core.models import Card, Column, Status
from tomville.core.script import call, say, wait, walk

if TYPE_CHECKING:
    from tomville.core.world import Pet, World


class LeadPlay:
    def on_card(self, world: World, card: Card, prev: Card | None) -> None:
        if card.agent and card.column is Column.TODO and (prev is None or prev.agent != card.agent):
            self._handover(world, card)
        elif card.agent and card.column is Column.DOING and (prev is None or prev.column is not Column.DOING):
            world.say(card.agent, f"on it: {card.id}")
        elif card.column is Column.DONE and (prev is None or prev.column is not Column.DONE) and world.lead:
            world.say(world.lead, "merged ✓")

    def on_status(self, world: World, pet: Pet, old: Status, new: Status) -> None:
        office = world.office
        if new is not Status.DONE or world.is_lead(pet) or office is None:
            return
        boss = office.zones.get("boss_desk")
        if boss is None:
            return
        steps = [walk((boss.cx, boss.y + boss.h))]
        task = _task_for_review(world, pet.name)
        steps += [say(f"{task} ready for review" if task else "done"), wait()]
        world.run(pet.name, steps)

    def on_message(self, world: World, sender: str | None, to: str, text: str) -> None:
        pass  # the envelope walk (World) is all a message does here

    def _handover(self, world: World, card: Card) -> None:
        office, lead, worker = world.office, world.lead, card.agent
        desk = office.desks.get(worker) if office else None
        if desk is None or lead is None or worker == lead or lead not in world.pets or worker not in world.pets:
            return
        seat = office.seats[lead]
        world.run(
            lead,
            [
                walk((desk.cx, desk.y - 1)),
                say(f"{card.id} is yours"),
                wait(),
                call(lambda: world.say(worker, "checking issues…")),
                walk(seat),
            ],
        )


def _task_for_review(world: World, name: str) -> str | None:
    for card in world.cards.values():
        if card.agent == name and card.column in (Column.DOING, Column.REVIEW):
            return card.id
    return None
