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
        app = TomvilleApp(project=tmp_path)
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
        app = TomvilleApp(project=tmp_path)
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.pause()
            return app.query_one("#main").has_class("portrait")

    assert asyncio.run(run())
