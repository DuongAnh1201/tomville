"""The world model: where each pet is, where it is going and what it says.

It turns events into targets and moves pets cell by cell around walls. It draws
nothing and never calls herdr or GitHub, so it runs with fake events in tests.
Speed is in cells per second, so changing the frame rate never changes how fast
pets walk. What a team shape adds on top (the lead's handover, "ready for
review") lives in a `Play`, one per shape, see `core/shapes/lead_play.py`.
"""

from __future__ import annotations

import random
import re
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Protocol

from rich.cells import cell_len

from tomville.core.models import (
    Agent,
    AgentAppeared,
    AgentLeft,
    AgentStatusChanged,
    Card,
    CardChanged,
    CardRemoved,
    Message,
    MessageSent,
    Column,
    Event,
    Status,
)
from tomville.core.script import Step, say, wait, walk
from tomville.core.shapes import PLAYS, LeadShape, OfficeMap, Rect, TeamShape
from tomville.core.shapes.base import WALL

Cell = tuple[int, int]

WALK_SPEED = 8.0  # cells per second
WANDER_SPEED = 1.5
WANDER_TRIES = 8  # random lounge spots tried before staying put
TILE = 2  # cells per sprite, as in sprites.py
BUBBLE_SECONDS = 3.0
PHONE_STAY = 2.0  # seconds the 📱 envelope stays at the desk
SLEEP_AFTER = 60.0  # seconds idle before a pet sleeps
BLINK_HZ = 2.0
BOARD_COLUMN_W = 7  # the wall board headings "Todo   Doing  Review" are 7 cells apart
BELT_SPEED = 6.0  # cells per second for cards riding the pipeline belt
MAX_BUBBLE = 28  # characters
LABEL_MARK = 5  # cells kept free after a name for its mark (" #123", " ❗", " z z")


@dataclass
class Pet:
    name: str
    kind: str
    status: Status
    x: float
    y: float
    path: list[Cell] = field(default_factory=list)
    speed: float = WALK_SPEED
    home: Cell | None = None  # where the status sends it; None = stay put
    leaving: bool = False
    script: list[Step] = field(default_factory=list)
    bubbles: list[list] = field(default_factory=list)  # [text, seconds left]; first shows
    idle_for: float = 0.0
    wander_in: float = 2.0

    @property
    def cell(self) -> Cell:
        return round(self.x), round(self.y)

    @property
    def sleeping(self) -> bool:
        return self.status is Status.IDLE and self.idle_for >= SLEEP_AFTER and not self.path


@dataclass(frozen=True)
class Appearance:
    """What the renderer needs for one pet this frame."""

    name: str
    kind: str
    status: Status
    x: int
    y: int  # already includes the jump of a blocked pet
    mark: str  # shown after the name: "❗", "?", "z z", a task id, or ""
    bubble: str | None
    moving: bool = False
    label_x: int = 0  # where the name starts: right of the sprite, or left of it near the wall
    label_y: int | None = None  # its row, when not the sprite's own (name under or over it)

    @property
    def label(self) -> str:
        return f"{self.name} {self.mark}" if self.mark else self.name


@dataclass
class Parcel:
    """A card moving through the office on its own, like one riding a belt."""

    label: str
    x: float
    y: float
    path: list[Cell] = field(default_factory=list)
    stay: float | None = None  # seconds it stays after arriving; None: until removed

    @property
    def cell(self) -> Cell:
        return round(self.x), round(self.y)


class Play(Protocol):
    """What a team shape adds to the world. The hooks may start scripts."""

    def on_status(self, world: World, pet: Pet, old: Status, new: Status) -> None: ...

    def on_card(self, world: World, card: Card, prev: Card | None) -> None: ...

    def on_message(self, world: World, sender: str | None, to: str, text: str) -> None: ...


class NullPlay:
    def on_status(self, world, pet, old, new) -> None:
        pass

    def on_card(self, world, card, prev) -> None:
        pass

    def on_message(self, world, sender, to, text) -> None:
        pass


class World:
    def __init__(
        self,
        shape: TeamShape | None = None,
        lead: str | None = "claude",
        rng: random.Random | None = None,
        still: bool = False,
    ) -> None:
        self.shape = shape or LeadShape()
        self.lead = lead
        self.still = still  # --still: no walking; pets and cards jump to where they go
        self.rng = rng or random.Random()
        play = PLAYS.get(self.shape.name)
        self.play: Play = play() if play else NullPlay()
        self.pets: dict[str, Pet] = {}
        self.cards: dict[str, Card] = {}
        self.parcels: dict[str, Parcel] = {}
        self.office: OfficeMap | None = None
        self.size: Cell = (0, 0)
        self.time = 0.0
        self._blocked: set[Cell] = set()
        self._workers: list[str] = []

    # --- setup and events -------------------------------------------------

    def resize(self, width: int, height: int) -> None:
        """Draw the office at a new size; pets jump to where they belong."""
        if (width, height) == self.size and self.office is not None:
            return
        self.size = (width, height)
        self._relayout(snap=True)

    def load(self, agents: list[Agent], cards: list[Card]) -> None:
        """Start-up state: pets start at their places, no handovers for old cards.

        Can be called once per source (agents, then cards): it only adds what is
        missing and never moves a pet that is already here.
        """
        self.cards.update({c.id: c for c in cards})
        fresh = [a for a in agents if a.name not in self.pets]
        for agent in fresh:
            self.pets[agent.name] = self._new_pet(agent)
        if fresh:
            self._relayout(snap=True)

    def apply(self, event: Event) -> None:
        if isinstance(event, AgentAppeared):
            self._appeared(event.agent)
        elif isinstance(event, AgentStatusChanged):
            self._status_changed(event)
        elif isinstance(event, AgentLeft):
            self._left(event.name)
        elif isinstance(event, CardChanged):
            prev = self.cards.get(event.card.id)
            self.cards[event.card.id] = event.card
            self.play.on_card(self, event.card, prev)
        elif isinstance(event, CardRemoved):
            self.cards.pop(event.id, None)
        elif isinstance(event, MessageSent) and event.message.via.startswith("telegram"):
            self._phone_message(event.message)
        elif isinstance(event, MessageSent):
            m = event.message
            self._message(m.sender, m.to, m.text)
            self.play.on_message(self, m.sender, m.to, m.text)

    def _appeared(self, agent: Agent) -> None:
        if agent.name in self.pets:
            return
        door = self._door_cell()
        pet = self._new_pet(agent)
        if door:
            pet.x, pet.y = door
        self.pets[agent.name] = pet
        self._relayout(snap=False)

    def _status_changed(self, event: AgentStatusChanged) -> None:
        pet = self.pets.get(event.name)
        if pet is None or pet.leaving:
            return
        pet.status = event.new
        pet.idle_for = 0.0
        if not self.is_lead(pet):
            pet.script.clear()
        self._retarget(pet, force=True)
        self.play.on_status(self, pet, event.old, event.new)

    def _left(self, name: str) -> None:
        pet = self.pets.get(name)
        if pet is None or pet.leaving:
            return
        pet.leaving = True
        pet.script.clear()
        door = self._door_cell()
        if door is None or not self._walk(pet, door):
            del self.pets[name]
        else:
            self._relayout(snap=False)

    def _phone_message(self, m: Message) -> None:
        """Tom's phone: 📱 comes in at the door; a reply or an approval shows as a bubble."""
        text = re.sub(r"<[^>]+>", "", m.text).strip().replace("\n", " ")
        if m.via == "telegram-approval":
            self.say(m.to, "❌" if text.startswith("❌") else "✅")
        elif m.via == "telegram" and m.sender == "tom":
            door = self._door_cell()
            spot = self._front_of_desk(m.to) or (self.pets[m.to].cell if m.to in self.pets else None)
            if door and spot:
                key = f"📱{len(self.parcels)}-{self.time}"
                self.parcels[key] = Parcel("📱", *door, stay=PHONE_STAY)
                self.move_parcel(key, spot)
            self.say(m.to, f"📱 {text}")
        elif m.via == "telegram" and m.to == "tom" and m.sender:
            self.say(m.sender, f"📱 → tom: {text}")

    def _message(self, sender: str | None, to: str, text: str) -> None:
        """The envelope walk: the sender carries ✉ to the receiver's desk and walks back.

        With an unknown sender (a guessed handoff) the receiver just shows "? ✉ …".
        """
        note = f"✉ {text}"
        if sender is None or sender not in self.pets or sender == to or self.office is None:
            if to in self.pets:
                self.say(to, f"? {note}")
            return
        spot = self._front_of_desk(to)
        if spot is None:
            self.say(sender, note)
            return
        self.run(sender, [walk(spot), say(note), wait(), walk(self.office.seats.get(sender, spot))])

    def _front_of_desk(self, name: str) -> Cell | None:
        """Where a visitor stands to talk to `name`: across the desk from its seat."""
        office = self.office
        desk = office.desks.get(name) if office else None
        seat = office.seats.get(name) if office else None
        if desk is None or seat is None:
            return None
        # The seat is on one side of the desk; the visitor stands on the other.
        return (desk.cx, desk.y - 1) if seat[1] >= desk.y + desk.h else (desk.cx, desk.y + desk.h)

    def _new_pet(self, agent: Agent) -> Pet:
        return Pet(agent.name, agent.kind, agent.status, 0.0, 0.0)

    # --- queries ----------------------------------------------------------

    def is_lead(self, pet: Pet) -> bool:
        return pet.name == self.lead

    def task_of(self, name: str) -> str | None:
        """The id of the card this agent is working on, if any."""
        for card in self.cards.values():
            if card.agent == name and card.column is Column.DOING:
                return card.id
        return None

    def board_cells(self) -> list[tuple[int, int, str, str | None]]:
        """(x, y, text, agent) for the cards on the wall board, under Todo / Doing / Review.

        Done cards stay off the wall. A column with more cards than rows shows the
        ones that fit and `+N` in its last row.
        """
        zone = self.office.zones.get("board_cards") if self.office else None
        if zone is None or zone.h < 1:
            return []
        cells = []
        for i, column in enumerate((Column.TODO, Column.DOING, Column.REVIEW)):
            x = zone.x + 1 + i * BOARD_COLUMN_W
            width = min(BOARD_COLUMN_W - 1, zone.x + zone.w - x)
            cards = sorted((c for c in self.cards.values() if c.column is column), key=lambda c: (len(c.id), c.id))
            if width < 1 or not cards:
                continue
            shown = cards if len(cards) <= zone.h else cards[: zone.h - 1]
            for row, card in enumerate(shown):
                cells.append((x, zone.y + row, card.id[:width], card.agent))
            if len(shown) < len(cards):
                cells.append((x, zone.y + len(shown), f"+{len(cards) - len(shown)}"[:width], None))
        return cells

    def appearances(self) -> list[Appearance]:
        return self._place_labels([self.appearance(p) for p in self.pets.values()])

    def _place_labels(self, apps: list[Appearance]) -> list[Appearance]:
        """Choose, for each name, the spot next to its sprite where it fits.

        Right of the sprite is the default. A name moves to the left near the right
        wall or when its neighbour is in the way, so names stay inside the walls and
        never cover a sprite or another name. Room is kept for the mark after the
        name (a task id, ❗, z z) when there is any; a very tight row gives that up.
        """
        o = self.office
        if o is None:
            return apps
        taken = [Rect(a.x, a.y, 2, 1) for a in apps]
        out = []
        for a in apps:
            w = cell_len(a.label)
            options = []
            for dy in (0, 1, -1):  # beside the sprite, else under or over it
                for room in (cell_len(a.name) + LABEL_MARK, cell_len(a.name)):
                    options.append((Rect(a.x + 2, a.y + dy, room, 1), a.x + 2, a.y + dy))
                    options.append((Rect(a.x - 1 - room, a.y + dy, room, 1), a.x - 1 - w, a.y + dy))
                    if dy:
                        options.append((Rect(a.x, a.y + dy, room, 1), a.x, a.y + dy))
            for rect, x, y in options:
                if 1 <= rect.y <= o.height - 2 and rect.x >= 1 and rect.x + rect.w <= o.width - 1 and not any(_overlap(rect, t) for t in taken):
                    taken.append(rect)
                    out.append(replace(a, label_x=max(1, x), label_y=y))
                    break
            else:
                out.append(a)
        return out

    def appearance(self, pet: Pet) -> Appearance:
        x, y = pet.cell
        mark = ""
        if pet.status is Status.BLOCKED:
            blink_on = int(self.time * BLINK_HZ * 2) % 2 == 0
            if blink_on:
                mark = "❗"
            if int(self.time * BLINK_HZ) % 2 == 0:
                y = self._jump_to(x, y)
        elif pet.status is Status.UNKNOWN:
            mark = "?"
        elif pet.sleeping:
            mark = "z z"
        elif pet.status is Status.WORKING:
            mark = self.task_of(pet.name) or ""
        bubble = pet.bubbles[0][0] if pet.bubbles else None
        return Appearance(pet.name, pet.kind, pet.status, x, y, mark, bubble, bool(pet.path), x + 2)

    def _jump_to(self, x: int, y: int) -> int:
        """Where a blocked pet at (x, y) is drawn while it jumps: up, else down, else here.

        The sprite is 2 cells wide and must not land on a wall or a desk.
        """
        for ny in (y - 1, y + 1):
            if all(self._inside((nx, ny)) and (nx, ny) not in self._blocked for nx in (x, x + 1)):
                return ny
        return y

    def bubble_rect(self, name: str) -> Rect | None:
        """Where `name`'s bubble goes: inside the office, over no pet and no name."""
        pet = self.pets.get(name)
        if pet is None or not pet.bubbles or self.office is None:
            return None
        apps = self.appearances()
        me = next(a for a in apps if a.name == name)
        taken = [Rect(a.x, a.y, 2, 1) for a in apps]  # a sprite is 2 cells wide
        taken += [_label_rect(a) for a in apps if a.name != name]
        taken.append(_label_rect(me))
        text = f" {me.bubble[:MAX_BUBBLE]} "
        w, o = len(text), self.office
        for dy in (-1, -2, -3, 0, 1, 2, 3):
            for x0 in (me.x - w // 2, me.x - w, me.x + 1):
                x0 = max(1, min(x0, o.width - 1 - w))
                r = Rect(x0, me.y + dy, w, 1)
                if r.y < 1 or r.y > o.height - 2:
                    continue
                if not any(_overlap(r, t) for t in taken):
                    return r
        return None

    # --- time -------------------------------------------------------------

    def move_parcel(self, label: str, goal: Cell, start: Cell | None = None) -> None:
        """Send a card to `goal` in a straight line (along x, then y), from `start` if new."""
        parcel = self.parcels.get(label)
        if parcel is None:
            sx, sy = start or goal
            parcel = self.parcels[label] = Parcel(label, sx, sy)
        x, y = parcel.cell
        gx, gy = goal
        step = 1 if gx >= x else -1
        path = [(cx, y) for cx in range(x + step, gx + step, step)] if gx != x else []
        step = 1 if gy >= y else -1
        path += [(gx, cy) for cy in range(y + step, gy + step, step)] if gy != y else []
        parcel.path = path

    def parcel_cells(self) -> list[tuple[int, int, str]]:
        return [(*p.cell, p.label) for p in self.parcels.values()]

    def tick(self, dt: float) -> None:
        self.time += dt
        for key, parcel in list(self.parcels.items()):
            if parcel.stay is not None and not parcel.path:
                parcel.stay -= dt
                if parcel.stay <= 0:
                    del self.parcels[key]
                    continue
            if self.still and parcel.path:
                parcel.x, parcel.y = parcel.path[-1]
                parcel.path.clear()
            budget = BELT_SPEED * dt
            while parcel.path and budget > 0:
                tx, ty = parcel.path[0]
                d = abs(tx - parcel.x) + abs(ty - parcel.y)
                if d <= budget:
                    parcel.x, parcel.y = tx, ty
                    parcel.path.pop(0)
                    budget -= d
                else:
                    parcel.x += (tx - parcel.x) / d * budget
                    parcel.y += (ty - parcel.y) / d * budget
                    budget = 0
        for pet in list(self.pets.values()):
            self._bubble_time(pet, dt)
            self._move(pet, dt)
            if pet.leaving and not pet.path:
                del self.pets[pet.name]
                self._relayout(snap=False)
                continue
            self._run_script(pet)
            self._idle(pet, dt)

    def _bubble_time(self, pet: Pet, dt: float) -> None:
        if pet.bubbles:
            pet.bubbles[0][1] -= dt
            if pet.bubbles[0][1] <= 0:
                pet.bubbles.pop(0)

    def _move(self, pet: Pet, dt: float) -> None:
        if self.still and pet.path:
            pet.x, pet.y = pet.path[-1]
            pet.path.clear()
            return
        budget = pet.speed * dt
        while budget > 0 and pet.path:
            tx, ty = pet.path[0]
            dx, dy = tx - pet.x, ty - pet.y
            dist = abs(dx) + abs(dy)
            if dist <= budget:
                pet.x, pet.y = tx, ty
                pet.path.pop(0)
                budget -= dist
            else:
                pet.x += dx / dist * budget
                pet.y += dy / dist * budget
                budget = 0

    def _run_script(self, pet: Pet) -> None:
        had = bool(pet.script)
        while pet.script:
            step = pet.script[0]
            if step.kind == "walk":
                if not step.started:
                    step.started = True
                    if not self._walk(pet, step.arg):
                        pet.script.pop(0)
                        continue
                    if pet.path:
                        return
                elif pet.path:
                    return
            elif step.kind == "say":
                self.say(pet.name, step.arg)
            elif step.kind == "wait":
                if pet.bubbles:
                    return
            elif step.kind == "call":
                step.arg()
            pet.script.pop(0)
        if had:
            self._retarget(pet, force=True)

    def _idle(self, pet: Pet, dt: float) -> None:
        if pet.status is not Status.IDLE or pet.script or pet.leaving:
            return
        pet.idle_for += dt
        if pet.path:
            return
        lounge = self.office.zones.get("lounge") if self.office else None
        if self.is_lead(pet) or lounge is None or pet.sleeping:
            return
        pet.wander_in -= dt
        if pet.wander_in <= 0:
            pet.wander_in = self.rng.uniform(2.0, 5.0)
            for _ in range(WANDER_TRIES):
                cell = (
                    self.rng.randrange(lounge.x, lounge.x + lounge.w),
                    self.rng.randrange(lounge.y, lounge.y + lounge.h),
                )
                if self._free_spot(pet, cell) and self._walk(pet, cell):
                    pet.speed = WANDER_SPEED
                    break

    def _free_spot(self, pet: Pet, cell: Cell) -> bool:
        """No other pet stands, or is heading, where its sprite or name would touch
        this pet's sprite and name (one row: sprite, name, then a gap)."""
        mine = Rect(cell[0], cell[1], TILE + cell_len(pet.name) + 2, 1)
        for other in self.pets.values():
            if other is pet or other.leaving:
                continue
            for x, y in [other.cell] + ([other.path[-1]] if other.path else []):
                if _overlap(mine, Rect(x, y, TILE + cell_len(other.name) + 2, 1)):
                    return False
        return True

    def say(self, name: str, text: str) -> None:
        """Queue a bubble: they show one after another, a few seconds each."""
        pet = self.pets.get(name)
        if pet is not None:
            pet.bubbles.append([text, BUBBLE_SECONDS])

    def run(self, name: str, steps: list[Step]) -> None:
        """Give a pet a script; it takes over from the status until it ends."""
        pet = self.pets.get(name)
        if pet is not None and not pet.leaving:
            pet.script.extend(steps)

    # --- places and paths -------------------------------------------------

    def _relayout(self, snap: bool) -> None:
        width, height = self.size
        if width <= 0 or height <= 0:
            return
        workers = [n for n, p in self.pets.items() if n != self.lead and not p.leaving]
        if not snap and self.office is not None and workers == self._workers:
            for pet in self.pets.values():
                self._retarget(pet)
            return
        self._workers = workers
        self.office = self.shape.layout(width, height, self.lead, workers)
        self._blocked = _blocked_cells(self.office)
        for pet in self.pets.values():
            pet.home = None
            if snap:
                pet.path.clear()
                pet.script.clear()
                # Blocked and unknown pets have no target; without a known spot
                # they start at their desk.
                home = self._home(pet) or self.office.seats.get(pet.name)
                if home:
                    pet.x, pet.y = home
                elif pet.cell in self._blocked or not self._inside(pet.cell):
                    pet.x, pet.y = self._door_cell() or (1, 1)
            self._retarget(pet)

    def _inside(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.size[0] and 0 <= cell[1] < self.size[1]

    def _door_cell(self) -> Cell | None:
        door = self.office.zones.get("door") if self.office else None
        return (door.x, door.y) if door else None

    def _zone_of(self, pet: Pet) -> str | None:
        if self.is_lead(pet) or pet.leaving:
            return None
        if pet.status is Status.IDLE:
            return "lounge"
        if pet.status is Status.DONE:
            return "review"
        if pet.status is Status.WORKING and pet.name not in self.office.seats:
            return "lounge"  # no desk for it
        return None

    def _home(self, pet: Pet) -> Cell | None:
        o = self.office
        if o is None or pet.leaving:
            return None
        zone = self._zone_of(pet)
        if zone:
            rect = o.zones.get(zone)
            if rect is None:
                return None
            index = 0
            for p in self.pets.values():
                if p is pet:
                    break
                index += self._zone_of(p) == zone
            cols = max(1, rect.w // 3)
            return rect.x + (index % cols) * 3 + 1, rect.y + (index // cols) % rect.h
        if self.is_lead(pet) or pet.status is Status.WORKING:
            return o.seats.get(pet.name)
        return None  # blocked and unknown stay where they are

    def _retarget(self, pet: Pet, force: bool = False) -> None:
        if pet.script or pet.leaving:
            return
        home = self._home(pet)
        if home is None or (home == pet.home and not force):
            return
        pet.home = home
        if home != pet.cell or pet.path:
            self._walk(pet, home)

    def _walk(self, pet: Pet, goal: Cell) -> bool:
        """Set the pet's path to `goal`; False if there is no way there."""
        path = self._find_path(pet.cell, goal)
        if path is None:
            return False
        # Start with the cell it is leaving, so a pet between cells stays on the grid.
        pet.path = ([pet.cell] if (pet.x, pet.y) != pet.cell else []) + path
        pet.speed = WALK_SPEED
        return True

    def _find_path(self, start: Cell, goal: Cell) -> list[Cell] | None:
        """Shortest walk around walls and desks (4 directions), without `start`."""
        if goal in self._blocked or not self._inside(goal):
            return None
        prev: dict[Cell, Cell | None] = {start: None}
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            if cell == goal:
                break
            x, y = cell
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nxt not in prev and nxt not in self._blocked and self._inside(nxt):
                    prev[nxt] = cell
                    queue.append(nxt)
        if goal not in prev:
            return None
        path: list[Cell] = []
        cell = goal
        while cell != start:
            path.append(cell)
            cell = prev[cell]
        return path[::-1]


def _blocked_cells(office: OfficeMap) -> set[Cell]:
    blocked = {
        (x, y) for y, row in enumerate(office.rows) for x, ch in enumerate(row) if ch == WALL
    }
    rects = list(office.desks.values())
    if "board" in office.zones:
        rects.append(office.zones["board"])
    for r in rects:
        blocked.update((x, y) for y in range(r.y, r.y + r.h) for x in range(r.x, r.x + r.w))
    return blocked


def _label_rect(a: Appearance) -> Rect:
    return Rect(a.label_x, a.y if a.label_y is None else a.label_y, cell_len(a.label), 1)


def _overlap(a: Rect, b: Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


__all__ = ["Appearance", "Pet", "Play", "World"]
