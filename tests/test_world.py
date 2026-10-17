import random

from tomville.core.models import (
    Agent,
    AgentAppeared,
    AgentLeft,
    AgentStatusChanged,
    Card,
    CardChanged,
    Column,
    Status,
)
from tomville.core.shapes.base import Canvas, OfficeMap, Rect
from tomville.core.world import BUBBLE_SECONDS, SLEEP_AFTER, WALK_SPEED, World


def agent(name, status=Status.IDLE, kind="codex"):
    return Agent(name=name, kind=kind, status=status, pane_id=f"p-{name}")


def make(*agents, w=128, h=30):
    world = World(lead="claude", rng=random.Random(1))
    world.resize(w, h)
    world.load(list(agents), [])
    return world


def run(world, seconds, dt=0.1, watch=None):
    for _ in range(round(seconds / dt)):
        world.tick(dt)
        if watch:
            watch()


def status(world, name, new):
    world.apply(AgentStatusChanged(name, world.pets[name].status, new))


def card(id_, column, agent=None):
    return Card(id=id_, title="t", column=column, agent=agent)


def seat(world, name):
    return world.office.seats[name]


def test_load_puts_pets_at_their_places():
    w = make(agent("claude", Status.WORKING, "claude"), agent("codex1", Status.WORKING), agent("codex2"))
    assert w.pets["claude"].cell == seat(w, "claude")
    assert w.pets["codex1"].cell == seat(w, "codex1")
    assert w.office.zones["lounge"].contains(*w.pets["codex2"].cell)


def test_new_agent_walks_in_from_the_door_to_its_desk():
    w = make()
    w.apply(AgentAppeared(agent("codex1", Status.WORKING)))
    door = w.office.zones["door"]
    assert w.pets["codex1"].cell == (door.x, door.y)
    run(w, 20)
    assert w.pets["codex1"].cell == seat(w, "codex1")


def test_pets_never_enter_walls_or_desks():
    w = make()
    w.apply(AgentAppeared(agent("codex1", Status.WORKING)))
    w.apply(AgentAppeared(agent("codex2", Status.WORKING)))
    seen = []
    run(w, 20, dt=0.05, watch=lambda: seen.extend(p.cell for p in w.pets.values()))
    assert seen and not (set(seen) & w._blocked)


def test_speed_does_not_depend_on_frame_rate():
    def after(dt):
        w = make()
        w.apply(AgentAppeared(agent("codex1", Status.WORKING)))
        run(w, 1.0, dt=dt)
        p = w.pets["codex1"]
        return p.x, p.y

    (x1, y1), (x2, y2) = after(0.2), after(0.02)
    assert abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01
    door = make().office.zones["door"]
    assert abs(x1 - door.x) + abs(y1 - door.y) > WALK_SPEED - 1  # about 8 cells in 1 s


def test_blocked_stays_and_jumps_with_a_mark():
    w = make(agent("codex1", Status.WORKING))
    where = w.pets["codex1"].cell
    status(w, "codex1", Status.BLOCKED)
    marks, ys = set(), set()
    for _ in range(20):
        w.tick(0.1)
        a = w.appearance(w.pets["codex1"])
        marks.add(a.mark)
        ys.add(a.y)
    assert w.pets["codex1"].cell == where
    assert marks == {"❗", ""}  # blinks
    assert len(ys) == 2  # jumps


def test_unknown_stands_still_with_a_question_mark():
    w = make(agent("codex1", Status.WORKING))
    where = w.pets["codex1"].cell
    status(w, "codex1", Status.UNKNOWN)
    run(w, 3)
    assert w.pets["codex1"].cell == where
    assert w.appearance(w.pets["codex1"]).mark == "?"


def test_agent_that_exits_walks_out_the_door():
    w = make(agent("codex1", Status.WORKING))
    w.apply(AgentLeft("codex1"))
    assert "codex1" in w.pets
    run(w, 20)
    assert "codex1" not in w.pets
    assert "codex1" not in w.office.desks.keys() - {"_0"}


def test_idle_goes_to_lounge_wanders_then_sleeps():
    w = make(agent("codex1", Status.WORKING))
    status(w, "codex1", Status.IDLE)
    run(w, 10)
    lounge = w.office.zones["lounge"]
    assert lounge.contains(*w.pets["codex1"].cell)
    run(w, SLEEP_AFTER)
    assert w.appearance(w.pets["codex1"]).mark == "z z"
    status(w, "codex1", Status.WORKING)
    assert w.appearance(w.pets["codex1"]).mark != "z z"


def test_done_worker_goes_to_boss_desk_then_review():
    w = make(agent("claude", Status.WORKING, "claude"), agent("codex1", Status.WORKING))
    w.apply(CardChanged(card("#12", Column.DOING, "codex1"), None))
    status(w, "codex1", Status.DONE)
    boss = w.office.zones["boss_desk"]
    shown, spots = [], []

    def watch():
        p = w.pets["codex1"]
        spots.append(p.cell)
        if p.bubbles:
            shown.append(p.bubbles[0][0])

    run(w, 15, watch=watch)
    assert "#12 ready for review" in shown
    assert (boss.cx, boss.y + boss.h) in spots
    assert w.office.zones["review"].contains(*w.pets["codex1"].cell)


def test_handover_bubbles_appear_in_order_and_boss_returns():
    w = make(agent("claude", Status.WORKING, "claude"), agent("codex1", Status.IDLE))
    w.apply(CardChanged(card("#12", Column.TODO, "codex1"), None))
    desk = w.office.desks["codex1"]
    log, boss_spots = [], []

    def watch():
        for p in w.pets.values():
            if p.bubbles and (p.name, p.bubbles[0][0]) not in log:
                log.append((p.name, p.bubbles[0][0]))
        boss_spots.append(w.pets["claude"].cell)

    run(w, 12, watch=watch)
    w.apply(CardChanged(card("#12", Column.DOING, "codex1"), card("#12", Column.TODO, "codex1")))
    run(w, 1, watch=watch)
    assert log == [("claude", "#12 is yours"), ("codex1", "checking issues…"), ("codex1", "on it: #12")]
    assert (desk.cx, desk.y - 1) in boss_spots
    run(w, 10)
    assert w.pets["claude"].cell == seat(w, "claude")


def test_loaded_cards_do_not_start_handovers():
    w = World(lead="claude", rng=random.Random(1))
    w.resize(128, 30)
    w.load([agent("claude", Status.WORKING, "claude"), agent("codex1")], [card("#3", Column.TODO, "codex1")])
    assert not w.pets["claude"].script


def test_closed_issue_makes_the_boss_say_merged():
    w = make(agent("claude", Status.WORKING, "claude"))
    w.apply(CardChanged(card("#12", Column.DONE, "codex1"), card("#12", Column.REVIEW, "codex1")))
    assert w.pets["claude"].bubbles[0][0] == "merged ✓"


def test_bubbles_last_a_few_seconds_one_after_another():
    w = make(agent("codex1", Status.WORKING))
    w.say("codex1", "one")
    w.say("codex1", "two")
    run(w, BUBBLE_SECONDS - 0.5)
    assert w.pets["codex1"].bubbles[0][0] == "one"
    run(w, 1)
    assert w.pets["codex1"].bubbles[0][0] == "two"
    run(w, BUBBLE_SECONDS)
    assert not w.pets["codex1"].bubbles


def test_bubble_never_covers_another_pets_name():
    names = ["codex1", "codex2", "codex3"]
    w = make(agent("claude", Status.WORKING, "claude"), *[agent(n, Status.WORKING) for n in names])
    for n in ["claude", *names]:
        w.say(n, "a fairly long thing to say")
        rect = w.bubble_rect(n)
        assert rect is not None
        for a in w.appearances():
            if a.name != n:
                other = Rect(a.x + 2, a.y, len(a.label), 1)
                assert not (
                    rect.x < other.x + other.w and other.x < rect.x + rect.w and rect.y == other.y
                ), (n, a.name)


class RowShape:
    """A made-up shape: one desk per worker in a row, to show shapes plug in."""

    name = "row"

    def layout(self, width, height, lead, workers):
        c = Canvas(width, height)
        c.walls()
        desks, seats = {}, {}
        for i, n in enumerate(workers):
            r = Rect(3 + i * 12, 3, 10, 3)
            c.box(r, label=n)
            desks[n] = r
            seats[n] = (r.cx, 7)
        zones = {"lounge": Rect(2, height - 4, 10, 3), "door": Rect(width - 1, height - 3, 1, 2)}
        for y in (height - 3, height - 2):
            c.put(width - 1, y, " ")
        return OfficeMap(width, height, c.rows(), zones, desks, seats)


def test_another_shape_plugs_in_without_changing_the_core():
    w = World(RowShape(), lead=None, rng=random.Random(1))
    w.resize(80, 20)
    w.load([agent("a", Status.WORKING), agent("b", Status.WORKING)], [])
    assert w.pets["a"].cell == w.office.seats["a"]
    w.apply(AgentAppeared(agent("c", Status.WORKING)))
    run(w, 10)
    assert w.pets["c"].cell == w.office.seats["c"]
    w.apply(CardChanged(card("#1", Column.TODO, "c"), None))  # no play: nothing happens
    assert not any(p.script for p in w.pets.values())


def test_blocked_and_unknown_pets_start_at_their_desk():
    w = make(agent("codex1", Status.UNKNOWN), agent("codex2", Status.BLOCKED))
    assert w.pets["codex1"].cell == seat(w, "codex1")
    assert w.pets["codex2"].cell == seat(w, "codex2")


def test_still_mode_jumps_instead_of_walking():
    world = World(lead="claude", rng=random.Random(1), still=True)
    world.resize(128, 30)
    world.load([agent("claude"), agent("codex1")], [])
    world.apply(AgentStatusChanged("codex1", Status.IDLE, Status.WORKING))
    world.tick(0.1)  # one frame is enough: no walking
    assert world.pets["codex1"].cell == world.office.seats["codex1"]


def test_still_comes_from_settings():
    from tomville.core.settings import OfficeSettings
    from tomville.tui.app import make_world

    assert make_world(OfficeSettings(still=True)).still
    assert not make_world(OfficeSettings()).still


def test_blocked_pet_never_jumps_onto_a_desk_or_wall():
    names = ["codex1", "codex2", "codex3"]
    w = make(agent("claude", Status.BLOCKED, "claude"), *[agent(n, Status.BLOCKED) for n in names])
    for _ in range(40):  # two full jump cycles
        w.tick(0.1)
        for a in w.appearances():
            assert (a.x, a.y) not in w._blocked and (a.x + 1, a.y) not in w._blocked, a
    # A worker has room above its seat and jumps; the boss has a wall above and
    # its desk below, so it stays put.
    rows = {n: set() for n in ["claude", *names]}
    for _ in range(20):
        w.tick(0.1)
        for a in w.appearances():
            rows[a.name].add(a.y)
    assert len(rows["codex1"]) == 2
    assert rows["claude"] == {w.pets["claude"].cell[1]}


def test_jump_stays_put_when_there_is_no_room():
    w = make(agent("codex1", Status.BLOCKED))
    w._blocked |= {(x, y) for x in range(128) for y in range(30)}  # boxed in
    assert w._jump_to(10, 10) == 10
