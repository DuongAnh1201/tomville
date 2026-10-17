import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from tomville.core import events
from tomville.core.board.base import BoardUnavailable
from tomville.core.board.github import GitHubBoard, cards_from_issues
from tomville.core.board.tasks_md import TasksMarkdownBoard
from tomville.core.events import EventReader, parse_agents
from tomville.core.models import AgentAppeared, AgentLeft, AgentStatusChanged, BoardOffline, BoardOnline, CardChanged, CardRemoved, Column, Status
from tomville.core.settings import ReaderSettings, load_reader_settings

FIXTURES = Path(__file__).parent / 'fixtures'


def test_recorded_agents_and_lifecycle(tmp_path):
    agents = parse_agents(json.loads((FIXTURES / 'herdr_named_agents.json').read_text()))
    codex = next(a for a in agents if a.name == 'codex1')
    assert codex.kind == 'codex'
    reader = EventReader(tmp_path)
    assert reader.update_agents([codex]) == [AgentAppeared(codex)]
    blocked = replace(codex, status=Status.BLOCKED)
    assert reader.update_agents([blocked]) == [AgentStatusChanged(codex.name, codex.status, Status.BLOCKED)]
    assert reader.update_agents([blocked]) == []
    assert reader.update_agents([]) == [AgentLeft(codex.name)]


def test_github_recording_conditional_cache_and_pagination(tmp_path, monkeypatch):
    issues = json.loads((FIXTURES / 'github_issues.json').read_text())
    assert not any(c.id == '#10' for c in cards_from_issues(issues))
    assert next(c for c in cards_from_issues(issues) if c.id == '#9').column == Column.DONE
    board = GitHubBoard(tmp_path, 'owner/repo')
    responses = iter([
        'HTTP/2.0 200 OK\nETag: "one"\nLink: <https://api.github.com/page2>; rel="next"\n\n' + json.dumps(issues),
        'HTTP/2.0 200 OK\nETag: "two"\n\n[]',
        'HTTP/2.0 304 Not Modified\n\n',
        'HTTP/2.0 304 Not Modified\n\n',
    ])
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        raw = next(responses)
        return subprocess.CompletedProcess(args, 1 if '304' in raw else 0, raw, '')
    monkeypatch.setattr(subprocess, 'run', run)
    assert board.fetch() == board.fetch()
    assert 'If-None-Match: "one"' in commands[2]
    assert 'If-None-Match: "two"' in commands[3]


def test_offline_retains_cards_and_recovers(tmp_path):
    board = TasksMarkdownBoard(tmp_path / 'TASKS.md')
    board.path.write_text('| id | title | status | agent |\n| -- | -- | -- | -- |\n| T1 | Fix login | todo | codex1 |\n')
    reader = EventReader(tmp_path, board=board)
    assert isinstance(reader.update_board()[0], CardChanged)
    initial = reader.cards.copy()
    board.path.unlink()
    assert isinstance(reader.update_board()[0], BoardOffline)
    assert reader.update_board() == []
    assert reader.cards == initial
    board.path.write_text('| id | title | status | agent |\n| T1 | Fix login | review | codex1 |\n')
    result = reader.update_board()
    assert isinstance(result[0], BoardOnline)
    assert result[1].old_column == Column.TODO
    assert result[1].card.column == Column.REVIEW
    assert reader.update_board() == []
    board.path.write_text('')
    assert reader.update_board() == [CardRemoved('T1')]


def test_settings_precedence_and_validation(tmp_path, monkeypatch):
    config = tmp_path / 'settings.toml'
    config.write_text('[board]\nsource="tasks-md"\ncheck_seconds=30\n')
    monkeypatch.setenv('TOMVILLE_BOARD_CHECK', '120')
    assert load_reader_settings(tmp_path, config=config).check_seconds == 120
    result = load_reader_settings(tmp_path, config=config, check_seconds=15)
    assert result.source == 'tasks-md' and result.check_seconds == 15
    for value in (0, 9, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            ReaderSettings(check_seconds=value)


def test_socket_status_and_disconnect_polling(tmp_path, monkeypatch):
    async def run():
        socket = tmp_path / 'herdr.sock'
        monkeypatch.setenv('HERDR_SOCKET_PATH', str(socket))
        agent = parse_agents(json.loads((FIXTURES / 'herdr_agent_list.json').read_text()))[0]
        calls = 0
        subscribed = asyncio.Event()
        received = []
        async def snapshot():
            nonlocal calls
            calls += 1
            return [agent]
        monkeypatch.setattr(events, 'agent_list', snapshot)
        async def serve(reader, writer):
            try:
                request = json.loads(await reader.readline())
                assert {'type': 'pane.agent_status_changed', 'pane_id': agent.pane_id} in request['params']['subscriptions']
                writer.write(b'{"id":"tomville","result":{"type":"subscription_started"}}\n')
                writer.write((json.dumps({'event': 'pane.agent_status_changed', 'data': {'pane_id': agent.pane_id, 'agent_status': 'blocked'}}) + '\n').encode())
                await writer.drain()
                subscribed.set()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_unix_server(serve, path=str(socket))
        reader = EventReader(tmp_path, ReaderSettings(poll_seconds=.01))
        task = asyncio.create_task(reader._agents(received.append))
        try:
            await asyncio.wait_for(subscribed.wait(), 2)
            server.close()
            await server.wait_closed()
            await asyncio.sleep(.06)
            assert any(isinstance(e, AgentStatusChanged) and e.new == Status.BLOCKED for e in received)
            assert calls >= 3  # initial, reconciled, and fallback snapshots
            assert not task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()
    asyncio.run(run())
