"""Offline Bot API and permission-panel fixture replay; no herdr/network calls."""
import copy
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tomville.core import telegram as tg
from tomville.core.settings import settings_from_data, load_settings
from tomville.core.ville import write_ville

FIXTURES = Path(__file__).parent / 'fixtures'
API = json.loads((FIXTURES / 'telegram.json').read_text())


@pytest.fixture
def ville(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    data = {'team': {'shape': 'lead', 'lead': 'claude'}, 'board': {'source': 'tasks-md'},
            'agents': {'claude': {'kind': 'claude'}, 'codex-1': {'kind': 'codex'}, 'status': {'kind': 'claude'}},
            'telegram': {'enabled': True, 'id': 'fixture123', 'bot': '@fixture_bot', 'approvals': True, 'from': ['lead']}}
    write_ville(tmp_path, data)
    settings = settings_from_data(data)
    config = dict(token='123:fake', chat_id=42, offset=0, paused=False)
    tg.save_config('fixture123', config)
    return tmp_path, settings, config


@pytest.fixture
def bridge(ville, monkeypatch):
    project, settings, config = ville
    bot = Mock()
    bot.send.return_value = {'message_id': 70}
    b = tg.Bridge(project, settings, bot, config, clock=lambda: 100)
    monkeypatch.setattr(tg.messages, 'send', Mock())
    monkeypatch.setattr(tg.team, 'herdr', Mock(side_effect=AssertionError('unexpected herdr')))
    return b


def test_api_client():
    for method in ('getMe', 'sendMessage', 'getUpdates', 'error'):
        opener = Mock(return_value=io.BytesIO(json.dumps(API[method]).encode()))
        bot = tg.Bot('123:fake', opener)
        if method == 'error':
            with pytest.raises(OSError, match='401'):
                bot.call(method)
        else:
            assert bot.call(method) == API[method]['result']
    bot = tg.Bot('123:private', Mock(side_effect=OSError('URL contains 123:private')))
    with pytest.raises(OSError) as error:
        bot.call('getMe')
    assert '123:private' not in str(error.value)


def test_storage_and_validation(ville):
    project, settings, config = ville
    assert tg.load_config(settings) == config
    assert tg.config_path('fixture123').stat().st_mode & 0o777 == 0o600
    for table in ({'token': '123:fake'}, {'enabled': 'true'}, {'from': 'lead'}, {'id': '../../outside'}):
        with pytest.raises(ValueError):
            settings_from_data({'telegram': table})
    assert tg.health(settings) == (True, '@fixture_bot (paired)')
    tg.config_path('fixture123').unlink()
    assert not tg.health(settings)[0]
    assert tg.health(settings_from_data({})) == (True, 'not set up (optional)')


def test_pairing(ville, monkeypatch):
    project, settings, _ = ville
    settings.telegram['enabled'] = False
    bot = Mock(token='123:fake')
    bot.call.side_effect = [API['getMe']['result'], True,
        [*API['getUpdates']['result'][1:4], {'update_id': 20, 'message': dict(API['getUpdates']['result'][0]['message'], text='000007')}]]
    monkeypatch.setattr(tg.secrets, 'randbelow', lambda n: 7)
    tg.setup(project, settings, lambda q, d: 'lead' if q.startswith('Who') else d,
             hidden=lambda p: '123:fake', show=lambda s: None, bot_factory=lambda t: bot)
    paired = load_settings(project)
    assert tg.load_config(paired)['chat_id'] == 42
    assert tg.load_config(paired)['offset'] == 21
    assert not paired.telegram['approvals']
    assert 'token' not in (project / '.tomville/ville.toml').read_text()
    bot.send.assert_called_once_with(42, 'Paired ✅')


def test_pairing_timeout(ville):
    project, settings, _ = ville
    settings.telegram['enabled'] = False
    clock = iter([0, 301])
    bot = Mock(token='123:fake')
    bot.call.side_effect = [API['getMe']['result'], True]
    with pytest.raises(ValueError, match='expired'):
        tg.setup(project, settings, lambda q,d:d, hidden=lambda p:'123:fake', show=lambda s:None,
                 bot_factory=lambda t:bot, clock=lambda:next(clock))


def message(text):
    value = copy.deepcopy(API['getUpdates']['result'][0])
    value['message']['text'] = text
    return value


def test_routing_and_rejections(bridge):
    bridge.handle(message('hello lead'))
    tg.messages.send.assert_called_once_with(bridge.project, 'claude', 'hello lead', sender='tom', via='telegram')
    bridge.handle(message('/codex_1 test'))
    assert tg.messages.send.call_args.args[1:3] == ('codex-1', 'test')
    bridge.handle(message('/status_agent test'))
    assert tg.messages.send.call_args.args[1] == 'status'
    count = tg.messages.send.call_count
    for update in API['getUpdates']['result'][1:4]:
        bridge.handle(update)
    assert tg.messages.send.call_count == count
    bridge.settings.team = 'pipeline'
    bridge.handle(message('plain text'))
    assert 'needs a lead' in bridge.bot.send.call_args.args[1]


def test_builtins_pause(bridge):
    bridge.snapshot = lambda: {'agents': [{'name': 'claude', 'status': 'blocked'}], 'cards': [{'id': '#1', 'column': 'review', 'title': '<test>'}]}
    for command in ('help', 'start', 'status', 'board', 'pending', 'pause'):
        bridge.handle(message('/' + command))
    assert tg.load_config(bridge.settings)['paused']
    bridge.handle(message('do work'))
    tg.messages.send.assert_not_called()
    bridge.handle(message('/resume'))
    assert not tg.load_config(bridge.settings)['paused']
    bridge.handle(message('do work'))
    tg.messages.send.assert_called_once()


def test_chunking():
    text = '<b>' + '🐱&amp;&lt;' * 1800 + '</b>\n<i>done</i>'
    parts = tg.chunks(text)
    assert len(parts) > 2
    assert all(len(p) <= 4096 for p in parts)
    assert all(p.count('<b>') == p.count('</b>') for p in parts)
    assert ''.join(parts).replace('</b><b>', '') == text
    with pytest.raises(ValueError):
        tg.chunks('<b>unclosed')


def live_agent(kind='claude'):
    return {'name': 'claude', 'agent': kind, 'agent_status': 'blocked', 'pane_id': 'w1:p1', 'terminal_id': 'term1'}


@pytest.mark.parametrize('kind,yes,no', [('claude', '1', '3'), ('codex', 'y', 'esc')])
def test_permission_parser(kind, yes, no):
    screen = (FIXTURES / f'telegram_{kind}_permission.txt').read_text()
    question = tg.parse_question(kind, screen)
    assert (question.yes, question.no) == (yes, no)
    assert 'uv run pytest' in question.text and '/root/project' in question.text
    assert tg.parse_question('other', screen) is None
    assert tg.parse_question(kind, 'Do something? yes/no') is None


@pytest.mark.parametrize('choice,key', [('yes', '1'), ('no', '3')])
def test_approval(bridge, monkeypatch, choice, key):
    agent = live_agent()
    screen = (FIXTURES / 'telegram_claude_permission.txt').read_text()
    monkeypatch.setattr(tg.team, 'herdr', Mock(return_value={'agents': [agent]}))
    monkeypatch.setattr(tg.team, 'run_command', Mock(return_value=screen))
    bridge.blocked(dict(agent, status='blocked'))
    token = next(iter(bridge.pending))
    callback = copy.deepcopy(API['getUpdates']['result'][-1]['callback_query'])
    callback['data'] = token + ':' + choice
    bridge.callback(callback)
    assert any(call.args[1:] == ('agent', 'send-keys', 'w1:p1', key) for call in tg.team.herdr.call_args_list)
    assert 'telegram-approval' in (bridge.project / '.tomville/messages.jsonl').read_text()
    count = tg.team.herdr.call_count
    bridge.callback(callback)
    assert tg.team.herdr.call_count == count


@pytest.mark.parametrize('change', ['expired', 'text', 'pane', 'terminal', 'agent', 'wrong_chat', 'paused', 'unknown'])
def test_approval_refused(bridge, monkeypatch, change):
    agent = live_agent()
    screen = (FIXTURES / 'telegram_claude_permission.txt').read_text()
    herdr = Mock(return_value={'agents': [agent]})
    monkeypatch.setattr(tg.team, 'herdr', herdr)
    read = Mock(return_value=screen)
    monkeypatch.setattr(tg.team, 'run_command', read)
    if change == 'unknown':
        read.return_value = 'unknown screen'
    bridge.blocked(dict(agent, status='blocked'))
    if change == 'unknown':
        assert not bridge.pending
        assert 'answer in its pane' in bridge.bot.send.call_args.args[1]
        return
    callback = copy.deepcopy(API['getUpdates']['result'][-1]['callback_query'])
    callback['data'] = next(iter(bridge.pending)) + ':yes'
    if change == 'expired':
        bridge.clock = lambda: 701
    elif change == 'text':
        read.return_value = screen.replace('pytest', 'other command')
    elif change in ('pane', 'terminal', 'agent'):
        field = {'pane': 'pane_id', 'terminal': 'terminal_id', 'agent': 'name'}[change]
        herdr.return_value = {'agents': [dict(agent, **{field: 'different'})]}
    elif change == 'wrong_chat':
        callback['from']['id'] = 99
    elif change == 'paused':
        bridge.config['paused'] = True
    bridge.callback(callback)
    assert all('send-keys' not in call.args for call in herdr.call_args_list)


def test_reply_and_off(ville, monkeypatch):
    project, settings, _ = ville
    bot = Mock()
    monkeypatch.setattr(tg.messages, 'sender_name', lambda: 'codex-1')
    with pytest.raises(ValueError, match='not allowed'):
        tg.reply(project, settings, 'hello', bot_factory=lambda t:bot)
    monkeypatch.setattr(tg.messages, 'sender_name', lambda: 'claude')
    tg.reply(project, settings, '<b>hello</b>', bot_factory=lambda t:bot)
    assert bot.send.call_args.args[0] == 42
    monkeypatch.setattr(tg.team, 'load_state', lambda p: {'agents': {}})
    assert not tg.off(project, settings, lambda q:False)
    assert tg.config_path('fixture123').exists()
    assert tg.off(project, settings, lambda q:True)
    assert not tg.config_path('fixture123').exists()
    assert not load_settings(project).telegram['enabled']


def test_command_collision(ville):
    _, settings, _ = ville
    settings.agents = dict.fromkeys(['status', 'status-agent', 'a-b', 'a_b'])
    commands = tg.agent_commands(settings)
    assert len(commands) == 4
    assert 'status_agent' in commands
    assert all(len(c) <= 32 for c in commands)


def test_lock(ville):
    with tg.run_lock('fixture123'):
        with pytest.raises(ValueError, match='already running'):
            with tg.run_lock('fixture123'):
                pass


def test_two_villes_and_global_settings_do_not_share_link(ville, monkeypatch):
    project, settings, config = ville
    global_file = project / 'global.toml'
    global_file.write_text('[telegram]\nenabled = true\nid = "fixture123"\n')
    other = project / 'other'
    other.mkdir()
    assert not load_settings(other, config=global_file).telegram['enabled']
    tg.save_config('different123', dict(config, chat_id=99))
    tg.off(project, settings, lambda q:True)
    assert tg.config_path('different123').exists()


def test_stop_tab_rechecks_identity(ville, monkeypatch):
    project, settings, _ = ville
    tg.team.save_state(project, {'agents': {}, 'telegram': {'pane': 'p1', 'terminal': 't1', 'tab': 'tab1'}})
    herdr = Mock(return_value={'panes': [{'pane_id': 'p1', 'terminal_id': 'replacement'}]})
    monkeypatch.setattr(tg.team, 'herdr', herdr)
    with pytest.raises(OSError, match='identity changed'):
        tg.off(project, settings, lambda q:True)
    assert tg.config_path('fixture123').exists()
    assert load_settings(project).telegram['enabled']
    herdr.return_value = {'panes': [{'pane_id': 'p1', 'terminal_id': 't1'}]}
    tg.off(project, settings, lambda q:True)
    assert any(c.args[1:] == ('tab', 'close', 'tab1') for c in herdr.call_args_list)


def test_async_runtime_replays_poll_and_live_events(bridge, monkeypatch):
    import asyncio
    from tomville.core import events
    from tomville.core.models import Agent, Status, AgentStatusChanged, Card, Column, CardChanged
    emitted = []
    class Reader:
        agents = {'p1': Agent('claude', 'claude', Status.BLOCKED, 'p1')}
        cards = {}
        def __init__(self, *args):
            pass
        async def run(self, emit):
            # Initial state only calls snapshot; it must never ping.
            self.snapshot(list(self.agents.values()), [])
            emit(AgentStatusChanged('claude', Status.WORKING, Status.BLOCKED))
            emit(CardChanged(Card('#1', 'Review', Column.REVIEW), Column.DOING))
            emit(CardChanged(Card('#1', 'Done', Column.DONE), Column.REVIEW))
            while len(emitted) < 3:
                await asyncio.sleep(0)
            await asyncio.sleep(.01)
    bridge.blocked = lambda agent: emitted.append(agent['name'])
    bridge.bot.send.side_effect = lambda chat, text, **kw: emitted.append('review') if '→ review' in text else emitted.append('done') if '→ done' in text else {'message_id': 70}
    # Simulate a completed long poll without using the network.
    bridge.bot.call.side_effect = lambda method, **kw: [] if method == 'getUpdates' else True
    monkeypatch.setattr(events, 'EventReader', Reader)
    asyncio.run(tg._run(bridge))
    assert emitted == ['claude', 'review', 'done']
    assert any(c.args[0] == 'setMyCommands' for c in bridge.bot.call.call_args_list)


def test_cli_telegram_status_and_pause(ville, capsys):
    from tomville.cli import main
    project, settings, _ = ville
    assert main(['-C', str(project), 'telegram', 'status']) == 0
    assert 'paired' in capsys.readouterr().out
    assert main(['-C', str(project), 'telegram', 'pause']) == 0
    assert tg.load_config(settings)['paused']
    assert main(['-C', str(project), 'telegram', 'resume']) == 0
    assert not tg.load_config(settings)['paused']


def test_send_records_explicit_sender_and_transport(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(tg.messages.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, 'sent', ''))
    monkeypatch.setattr(tg.messages, 'sender_name', lambda: pytest.fail('sender lookup not needed'))
    tg.messages.send(tmp_path, 'claude', 'hello', sender='tom', via='telegram')
    entry = json.loads((tmp_path / '.tomville/messages.jsonl').read_text())
    assert (entry['from'], entry['to'], entry['via']) == ('tom', 'claude', 'telegram')


def test_runtime_persists_offset_before_forwarding(bridge, monkeypatch):
    import asyncio
    from tomville.core import events
    delivered = []
    class Finished(Exception):
        pass
    class Reader:
        agents, cards = {}, {}
        def __init__(self, *args):
            pass
        async def run(self, emit):
            await asyncio.Event().wait()
    polls = 0
    def call(method, **kw):
        nonlocal polls
        if method == 'getUpdates':
            polls += 1
            if polls == 1:
                return [message('hello')]
            raise Finished()
        return True
    bridge.bot.call.side_effect = call
    def send(*args, **kw):
        delivered.append(tg.load_config(bridge.settings)['offset'])
    monkeypatch.setattr(tg.messages, 'send', send)
    monkeypatch.setattr(events, 'EventReader', Reader)
    with pytest.raises(Finished):
        asyncio.run(tg._run(bridge))
    assert delivered == [11]


def test_runtime_backoff_caps_at_sixty(bridge, monkeypatch):
    import asyncio
    from tomville.core import events
    delays = []
    class Finished(Exception):
        pass
    class Reader:
        agents, cards = {}, {}
        def __init__(self, *args):
            pass
        async def run(self, emit):
            await asyncio.Event().wait()
    def call(method, **kw):
        if len(delays) == 7:
            raise Finished()
        raise OSError('fixture connection failure')
    async def sleep(delay):
        delays.append(delay)
    bridge.bot.call.side_effect = call
    monkeypatch.setattr(events, 'EventReader', Reader)
    monkeypatch.setattr(tg.asyncio, 'sleep', sleep)
    with pytest.raises(Finished):
        asyncio.run(tg._run(bridge))
    assert delays == [2, 4, 8, 16, 32, 60, 60]
