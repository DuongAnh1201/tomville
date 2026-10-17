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
            assert '[red]literal' in str(app.query_one(BoardPanel).render())
            current[:] = [replace(agent, status=Status.BLOCKED)]
            await pilot.pause(.1)
            assert 'blocked' in str(app.query_one(TeamPanel).render())
            path.unlink()
            await pilot.pause(.1)
            assert 'offline since' in str(app.query_one(BoardPanel).render())
            assert 'T1' in str(app.query_one(BoardPanel).render())
            await pilot.press('g')
            assert app.reader.settings.check_seconds == 120
            assert app.query_one(EventsPanel).lines
    asyncio.run(run())
