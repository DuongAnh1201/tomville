import asyncio

import pytest

from tomville import __version__
from tomville.cli import main
from tomville.tui.app import TomvilleApp
from tomville.tui.office import OfficeView


def test_version(capsys):
    with pytest.raises(SystemExit) as exit:
        main(["--version"])
    assert exit.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_office_opens_and_q_quits(tmp_path):
    async def run():
        app = TomvilleApp(project=tmp_path, live=False)
        async with app.run_test(size=(140, 40)) as pilot:
            office = app.query_one(OfficeView)
            await pilot.pause()
            assert "BOSS" in office.office.text()
            assert not app.query_one("#main").has_class("portrait")
            await pilot.press("q")
        return app

    app = asyncio.run(run())
    assert app.return_code == 0


def test_portrait_layout(tmp_path):
    async def run():
        app = TomvilleApp(project=tmp_path, live=False)
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.pause()
            return app.query_one("#main").has_class("portrait")

    assert asyncio.run(run())


def test_live_panels_with_offline_sources(tmp_path, monkeypatch):
    from dataclasses import replace
    from tomville.core import events
    from tomville.core.models import Agent, Status
    from tomville.core.settings import ReaderSettings
    from tomville.tui.app import TeamPanel, BoardPanel, EventsPanel

    async def run():
        monkeypatch.setenv('HERDR_SOCKET_PATH', str(tmp_path / 'missing.sock'))
        agent = Agent('codex1', 'codex', Status.WORKING, 'w4:p1')
        current = [agent]
        async def snapshot():
            return current
        monkeypatch.setattr(events, 'agent_list', snapshot)
        path = tmp_path / 'TASKS.md'
        path.write_text('| id | title | status | agent |\n| T1 | [red]literal | doing | codex1 |\n')
        app = TomvilleApp(project=tmp_path, settings=ReaderSettings(source='tasks-md', poll_seconds=.02))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(.15)
            assert 'codex1' in str(app.query_one(TeamPanel).render())
            assert '[red]literal' in str(app.query_one(BoardPanel).query_one('Static').render())
            current[:] = [replace(agent, status=Status.BLOCKED)]
            await pilot.pause(.1)
            assert 'blocked' in str(app.query_one(TeamPanel).render())
            path.unlink()
            await pilot.pause(.1)
            assert 'offline since' in str(app.query_one(BoardPanel).query_one('Static').render())
            assert 'T1' in str(app.query_one(BoardPanel).query_one('Static').render())
            await pilot.press('g')
            assert app.reader.settings.check_seconds == 120
            assert app.query_one(EventsPanel).lines
    asyncio.run(run())


def test_f_cycles_frame_rate_and_events_reach_the_world(tmp_path):
    from tomville.core.models import Agent, AgentAppeared, Status

    async def run():
        app = TomvilleApp(project=tmp_path, fps=10, live=False)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f")
            fps = app.fps
            app.handle_event(AgentAppeared(Agent("codex1", "codex", Status.WORKING, "w1:p1")))
            await pilot.pause(0.5)
            return fps, "codex1" in app.world.pets, "codex1 appeared" in str(app.query_one("EventsPanel").lines)

    assert asyncio.run(run()) == (15, True, True)


def test_start_up_snapshot_places_pets_without_handover(tmp_path, monkeypatch):
    from tomville.core import events
    from tomville.core.models import Agent, Status
    from tomville.core.settings import ReaderSettings

    async def run():
        monkeypatch.setenv('HERDR_SOCKET_PATH', str(tmp_path / 'missing.sock'))
        team = [Agent('claude', 'claude', Status.WORKING, 'w1:p1'), Agent('codex1', 'codex', Status.WORKING, 'w4:p1'), Agent('claude2', 'claude', Status.WORKING, 'w5:p1')]

        async def snapshot():
            return team

        monkeypatch.setattr(events, 'agent_list', snapshot)
        (tmp_path / 'TASKS.md').write_text('| id | title | status | agent |\n| -- | -- | -- | -- |\n| T1 | a | todo | codex1 |\n| T2 | b | todo | claude2 |\n')
        app = TomvilleApp(project=tmp_path, settings=ReaderSettings(source='tasks-md', poll_seconds=.02))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(.3)
            world = app.world
            seats = world.office.seats
            assert {n: world.pets[n].cell for n in team_names(team)} == {n: seats[n] for n in team_names(team)}
            assert not any(p.script or p.bubbles for p in world.pets.values())
            assert set(world.cards) == {'T1', 'T2'}

    def team_names(team):
        return [a.name for a in team]

    asyncio.run(run())


def _rows(app):
    from tomville.tui.office import OfficeView

    return app.query_one(OfficeView).render().plain.split("\n")


def test_demo_shows_three_animated_pets_and_s_switches_style_without_shifting_the_map(tmp_path):
    from rich.cells import cell_len

    from tomville.core.settings import OfficeSettings
    from tomville.core.sprites import load_frames

    async def run():
        app = TomvilleApp(project=tmp_path, settings=OfficeSettings(demo=True), live=False, fps=30)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.3)
            assert set(app.world.pets) == {"claude", "codex1", "codex2"}
            app._frame_timer.stop()  # same moment in both renders: blocked pets jump and blink
            emoji = _rows(app)
            await pilot.press("s")
            ascii_ = _rows(app)
            return app.sprites.style, emoji, ascii_

    style, emoji, ascii_ = asyncio.run(run())
    assert style == "ascii"
    text, plain = "".join(emoji), "".join(ascii_)
    assert any(f in text for f in load_frames("cat", "emoji")) and any(f in text for f in load_frames("dog", "emoji"))
    assert any(f in plain for f in load_frames("cat", "ascii")) and any(f in plain for f in load_frames("dog", "ascii"))
    assert len(emoji) == len(ascii_)
    for a, b in zip(emoji, ascii_):
        assert cell_len(a) == cell_len(b)
        for pet in ("cat", "dog", "sheep"):
            for f in load_frames(pet, "emoji"):
                a = a.replace(f, "  ")
            for f in load_frames(pet, "ascii"):
                b = b.replace(f, "  ")
        assert a == b


def test_working_pet_animates():
    from tomville.core.models import Agent, Status
    from tomville.core.world import World
    from tomville.core.sprites import Sprites
    from tomville.tui.office import OfficeView

    world = World()
    world.resize(128, 30)
    world.load([Agent("claude", "claude", Status.WORKING, "p1"), Agent("codex1", "codex", Status.IDLE, "p2")], [])
    view = OfficeView(world, Sprites())
    seen = set()
    for _ in range(12):
        world.tick(0.1)
        seen.add(tuple(view._overlays()[world.pets["claude"].cell[1]][0][1:2]))
    assert len(seen) == 2  # both frames of the cat


def test_cli_rejects_bad_pets(capsys):
    for args in (["--pet", "codex1"], ["--pet", "codex1=fox"]):
        with pytest.raises(SystemExit) as exit:
            main(args)
        assert exit.value.code == 2
    err = capsys.readouterr().err
    assert "AGENT=PET" in err and "unknown pet" in err


def test_short_screen_keeps_latest_events_visible_and_board_scrollable(tmp_path):
    from rich.text import Text
    from tomville.core.settings import OfficeSettings
    from tomville.tui.app import BoardPanel, EventsPanel

    async def run():
        app = TomvilleApp(project=tmp_path, settings=OfficeSettings(demo=True), live=False)
        async with app.run_test(size=(140, 24)) as pilot:
            board = app.query_one(BoardPanel)
            log = app.query_one(EventsPanel)
            board.update(Text('\n'.join(f'#{i} task' for i in range(30))))
            for i in range(20):
                log.write(f'event {i}')
            await pilot.pause()
            assert log.content_size.height >= 4
            assert log.region.bottom <= app.query_one('#sidebar').region.bottom
            visible = '\n'.join(log.render_line(y).text for y in range(log.content_size.height))
            assert 'event 19' in visible
            assert board.max_scroll_y > 0
            board.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            assert board.scroll_y > 0

    asyncio.run(run())


@pytest.mark.parametrize('size', [(40, 16), (60, 20), (80, 24), (100, 30), (148, 44), (200, 60), (50, 70), (70, 90)])
def test_layout_size_matrix_and_sidebar_toggle(tmp_path, size):
    from tomville.core.settings import OfficeSettings
    from tomville.tui.app import EventsPanel

    async def run():
        app = TomvilleApp(project=tmp_path, settings=OfficeSettings(demo=True), live=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            office = app.query_one(OfficeView)
            sidebar = app.query_one('#sidebar')
            assert app.query_one('#main').has_class('portrait') == (size[1] * 2 > size[0])
            assert office.size.width >= 30 and office.size.height >= 10
            if sidebar.display:
                assert app.query_one(EventsPanel).content_size.height >= 4
                if size[1] * 2 > size[0]:
                    assert office.size.height >= (size[1] - 2) * 2 / 3
            shown = sidebar.display
            await pilot.press('t')
            assert sidebar.display != shown
            if sidebar.display:
                assert app.query_one(EventsPanel).content_size.height >= 4
                assert sidebar.region.x >= 0 and sidebar.region.right <= size[0]
            assert office.size.width >= 30 and office.size.height >= 10
            await pilot.press('t')
            assert sidebar.display == shown

    asyncio.run(run())


def test_layout_resize_and_forced_orientation(tmp_path):
    from tomville.core.settings import OfficeSettings

    async def run():
        app = TomvilleApp(project=tmp_path, settings=OfficeSettings(), live=False)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert not app.query_one('#main').has_class('portrait')
            await pilot.resize_terminal(50, 70)
            assert app.query_one('#main').has_class('portrait')
            await pilot.resize_terminal(40, 16)
            assert not app.query_one('#sidebar').display
            await pilot.resize_terminal(148, 44)
            assert app.query_one('#sidebar').display
            app.settings.layout = 'portrait'
            app._apply_layout(148, 44)
            assert app.query_one('#main').has_class('portrait')
            app.settings.layout = 'landscape'
            await pilot.resize_terminal(50, 70)
            assert not app.query_one('#main').has_class('portrait')

    asyncio.run(run())
