import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile

import pytest

from tomville.core import events
from tomville.core.board.base import BoardUnavailable
from tomville.core.board.github import GitHubBoard, cards_from_issues
from tomville.core.board.tasks_md import TasksMarkdownBoard
from tomville.core.events import EventReader, parse_agents
from tomville.core.models import Agent, AgentAppeared, AgentLeft, AgentStatusChanged, BoardOffline, BoardOnline, CardChanged, CardRemoved, Column, Status
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
    async def run(socket):
        monkeypatch.setenv('HERDR_SOCKET_PATH', str(socket))
        agent = parse_agents(json.loads((FIXTURES / 'herdr_agent_list.json').read_text()))[0]
        calls = 0
        blocked, polled = asyncio.Event(), asyncio.Event()
        handlers = []
        async def snapshot():
            nonlocal calls
            calls += 1
            if calls >= 3:  # initial, reconciled, then disconnect fallback
                polled.set()
            return [agent]
        monkeypatch.setattr(events, 'agent_list', snapshot)
        def emit(event):
            if isinstance(event, AgentStatusChanged) and event.new == Status.BLOCKED:
                blocked.set()
        async def serve(reader, writer):
            try:
                request = json.loads(await asyncio.wait_for(reader.readline(), 2))
                assert {'type': 'pane.agent_status_changed', 'pane_id': agent.pane_id} in request['params']['subscriptions']
                # Stop accepting before disconnecting, so the reader must poll
                # instead of racing another connection against test cleanup.
                server.close()
                writer.write(b'{"id":"tomville","result":{"type":"subscription_started"}}\n')
                writer.write((json.dumps({'event': 'pane.agent_status_changed', 'data': {'pane_id': agent.pane_id, 'agent_status': 'blocked'}}) + '\n').encode())
                await asyncio.wait_for(writer.drain(), 2)
            finally:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), 2)
        def connected(reader, writer):
            handlers.append(asyncio.create_task(serve(reader, writer)))
        server = await asyncio.wait_for(asyncio.start_unix_server(connected, path=str(socket)), 2)
        reader = EventReader(tmp_path, ReaderSettings(poll_seconds=.01))
        task = asyncio.create_task(reader._agents(emit))
        try:
            await asyncio.wait_for(blocked.wait(), 2)
            await asyncio.wait_for(polled.wait(), 2)
            assert calls >= 3
            assert not task.done()
        finally:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
            finally:
                server.close()
                await asyncio.wait_for(server.wait_closed(), 2)
                # Observe handler failures and finish all clients before the loop closes.
                await asyncio.wait_for(asyncio.gather(*handlers), 2)
    # Short folder: macOS limits socket paths to 104 bytes. Remove it on failure too.
    with tempfile.TemporaryDirectory(prefix='tmv', dir='/tmp') as directory:
        asyncio.run(asyncio.wait_for(run(Path(directory) / 'herdr.sock'), 10))


@pytest.mark.parametrize('stage', ['connect', 'subscribe'])
def test_socket_cancellation_when_operation_completes(tmp_path, monkeypatch, stage):
    """Force the Python 3.11 wait_for completion/cancellation race, without a socket."""
    async def run():
        agent = parse_agents(json.loads((FIXTURES / 'herdr_agent_list.json').read_text()))[0]
        async def snapshot():
            return [agent]
        monkeypatch.setattr(events, 'agent_list', snapshot)
        task = None
        class Writer:
            closed = False
            def write(self, data):
                pass
            async def drain(self):
                pass
            def close(self):
                self.closed = True
            async def wait_closed(self):
                pass
        class Reader:
            reads = 0
            async def readline(self):
                self.reads += 1
                if self.reads == 1:
                    # Cancel in the same loop turn as a successful acknowledgement.
                    if stage == 'subscribe':
                        task.cancel()
                    return b'{"result":{}}\n'
                return await asyncio.wait_for(asyncio.Event().wait(), 2)
        writer = Writer()
        async def connect(path):
            if stage == 'connect':
                task.cancel()
            return Reader(), writer
        monkeypatch.setattr(asyncio, 'open_unix_connection', connect)
        reader = EventReader(tmp_path, ReaderSettings(poll_seconds=.01))
        task = asyncio.create_task(reader._agents(lambda event: None))
        try:
            # shield lets the deadline fail the assertion without issuing the
            # second cancellation that would hide a swallowed first cancellation.
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), .5)
            assert task.cancelled()
            assert writer.closed
        finally:
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
    asyncio.run(asyncio.wait_for(run(), 5))


def test_first_state_goes_to_snapshot_not_events(tmp_path):
    board = TasksMarkdownBoard(tmp_path / 'TASKS.md')
    board.path.write_text('| id | title | status | agent |\n| -- | -- | -- | -- |\n| T1 | Fix login | todo | codex1 |\n')
    reader = EventReader(tmp_path, board=board)
    emitted, snapshots = [], []
    reader.snapshot = lambda agents, cards: snapshots.append((agents, cards))
    codex = Agent('codex1', 'codex', Status.WORKING, 'w4:p1')
    reader._emit('agents', reader.update_agents([codex]), emitted.append)
    reader._emit('board', reader.update_board(), emitted.append)
    assert emitted == []
    assert [a.name for a in snapshots[-1][0]] == ['codex1'] and [c.id for c in snapshots[-1][1]] == ['T1']
    reader._emit('agents', reader.update_agents([replace(codex, status=Status.IDLE)]), emitted.append)
    assert emitted == [AgentStatusChanged('codex1', Status.WORKING, Status.IDLE)]


def test_new_pane_named_like_its_kind_does_not_replace_the_lead(tmp_path):
    def rows(*agents):
        return parse_agents({'result': {'agents': [dict(pane_id=p, agent='claude', agent_status=s, **({'name': n} if n else {})) for p, s, n in agents]}})

    reader = EventReader(tmp_path)
    reader.update_agents(rows(('p2', 'working', None)))
    # herdr shows the new pane before `agent start secretary` names it.
    appeared = reader.update_agents(rows(('p2', 'working', None), ('p7', 'idle', None)))
    assert [e.agent.name for e in appeared] == ['claude@p7']
    named = reader.update_agents(rows(('p2', 'working', None), ('p7', 'idle', 'secretary')))
    assert [type(e) for e in named] == [AgentLeft, AgentAppeared]
    assert named[0].name == 'claude@p7' and named[1].agent.name == 'secretary'
    assert sorted(a.name for a in reader.agents.values()) == ['claude', 'secretary']


def test_agents_table_in_the_ville(tmp_path):
    from tomville.core.settings import AgentSpec, settings_from_data

    settings = settings_from_data({
        'team': {'shape': 'lead', 'lead': 'claude'},
        'agents': {
            'claude': {'kind': 'claude', 'model': 'claude-opus-5-5', 'place': 'here'},
            'codex1': {'kind': 'codex'},
            'secretary': {'kind': 'claude', 'model': 'claude-haiku-5-5', 'place': 'tab', 'role': 'secretary', 'email': 'tom@example.com'},
        },
        'start_timeout': 90,
    })
    assert list(settings.agents) == ['claude', 'codex1', 'secretary']
    assert settings.agents['codex1'] == AgentSpec('codex1', 'codex')
    assert settings.agents['codex1'].place == 'worktree' and settings.agents['codex1'].worktree_branch == 'codex1'
    assert settings.agents['secretary'].role == 'secretary'
    assert settings.start_timeout == 90
    assert settings_from_data({}).agents == {} and settings_from_data({}).start_timeout == 120


@pytest.mark.parametrize('agents', [
    {'codex1': {}},
    {'codex1': {'kind': 'codex', 'place': 'moon'}},
    {'codex1': {'kind': 'codex', 'role': 'boss'}},
    {'codex1': {'kind': 'codex', 'colour': 'red'}},
    {'codex1': 'codex'},
])
def test_agents_table_rejects_bad_values(agents):
    from tomville.core.settings import settings_from_data

    with pytest.raises((ValueError, TypeError)):
        settings_from_data({'agents': agents})
