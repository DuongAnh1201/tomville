"""Offline Bot API and permission-panel fixture replay; no herdr/network calls."""
import copy
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tomville.core import telegram as tg
from tomville.core.messages import send as send_message
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
    agents = [{'name': name, 'agent': spec.kind, 'pane_id': 'pane-' + name}
              for name, spec in settings.agents.items()]
    monkeypatch.setattr(tg.team, 'herdr', Mock(return_value={'agents': agents}))
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
    tg.messages.send.assert_called_once_with(bridge.project, 'claude', 'hello lead', sender='tom', via='telegram', target='pane-claude', prompt_prefix='📱 Tom (Telegram): ')
    bridge.handle(message('/codex_1 test'))
    assert tg.messages.send.call_args.args[1:3] == ('codex-1', 'test')
    assert tg.messages.send.call_args.kwargs['prompt_prefix'] == '📱 Tom (Telegram): '
    bridge.handle(message('/status_agent test'))
    assert tg.messages.send.call_args.args[1] == 'status'
    count = tg.messages.send.call_count
    for update in API['getUpdates']['result'][1:4]:
        bridge.handle(update)
    assert tg.messages.send.call_count == count
    bridge.settings.team = 'pipeline'
    bridge.handle(message('plain text'))
    assert 'haven&#x27;t done Telegram for the pipeline team yet' in bridge.bot.send.call_args.args[1]


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


@pytest.mark.parametrize('name', ['claude', 'codex-1'])
def test_blocked_never_issues_screen_approval_buttons(bridge, monkeypatch, name):
    herdr = Mock(side_effect=AssertionError('no screen reading or keys'))
    monkeypatch.setattr(tg.team, 'herdr', herdr)
    bridge.blocked(dict(live_agent(), name=name))
    assert 'answer in its pane' in bridge.bot.send.call_args.args[1]
    assert 'reply_markup' not in bridge.bot.send.call_args.kwargs
    herdr.assert_not_called()


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


def test_runtime_backoff_caps_at_sixty(bridge, monkeypatch, capsys):
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
    original_sleep = asyncio.sleep
    async def sleep(delay):
        if delay >= 2:
            delays.append(delay)
        await original_sleep(0)
    bridge.bot.call.side_effect = call
    monkeypatch.setattr(events, 'EventReader', Reader)
    monkeypatch.setattr(tg.asyncio, 'sleep', sleep)
    with pytest.raises(Finished):
        asyncio.run(tg._run(bridge))
    assert delays == [2, 4, 8, 16, 32, 60, 60]
    assert capsys.readouterr().err.count('Telegram: poll failed: fixture connection failure') == 7
    records = [json.loads(line) for line in (bridge.project / '.tomville/messages.jsonl').read_text().splitlines()]
    assert len(records) == 7 and all(r['via'] == 'telegram-error' for r in records)


def test_routes_to_recorded_unnamed_lead_pane(bridge, monkeypatch):
    agents = json.loads((FIXTURES / 'herdr_named_agents.json').read_text())['result']['agents']
    lead = agents[0]
    assert not lead.get('name')
    tg.team.save_state(bridge.project, {'agents': {}, 'lead_pane': lead['pane_id']})
    monkeypatch.setattr(tg.team, 'herdr', Mock(return_value={'agents': agents}))
    bridge.handle(message('hello unnamed lead'))
    tg.messages.send.assert_called_once_with(bridge.project, 'claude', 'hello unnamed lead', sender='tom', via='telegram', target=lead['pane_id'], prompt_prefix='📱 Tom (Telegram): ')
    assert 'Sent to <b>claude</b>' in bridge.bot.send.call_args.args[1]


def test_agent_command_resolves_live_pane_and_keeps_log_name(bridge, monkeypatch):
    import subprocess
    agents = json.loads((FIXTURES / 'herdr_named_agents.json').read_text())['result']['agents']
    worker = next(a for a in agents if a.get('name') == 'codex1')
    bridge.routes['codex_1'] = 'codex1'
    monkeypatch.setattr(tg.team, 'herdr', Mock(return_value={'agents': agents}))
    # Use the actual send boundary with a fake subprocess, checking both command and log.
    monkeypatch.setattr(tg.messages, 'send', send_message)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, 'sent', ''))
    monkeypatch.setattr(tg.messages.subprocess, 'run', run)
    bridge.handle(message('/codex_1 run tests'))
    assert run.call_args.args[0] == ['herdr', 'agent', 'prompt', worker['pane_id'], '📱 Tom (Telegram): run tests']
    log = json.loads((bridge.project / '.tomville/messages.jsonl').read_text())
    assert (log['from'], log['to'], log['via'], log['text']) == ('tom', 'codex1', 'telegram', 'run tests')


@pytest.mark.parametrize('failure', ['missing', 'ambiguous', 'renamed', 'terminal', 'kind', 'send', 'send-json'])
def test_failed_delivery_is_explained_and_logged(bridge, monkeypatch, capsys, failure):
    agent = dict(name='claude', agent='claude', pane_id='lead', terminal_id='term')
    agents = [agent]
    if failure in ('renamed', 'terminal', 'kind'):
        tg.team.save_state(bridge.project, {'agents': {}, 'lead_pane': 'lead', 'lead_terminal': 'term', 'lead_kind': 'claude'})
        agent[{'renamed': 'name', 'terminal': 'terminal_id', 'kind': 'agent'}[failure]] = 'replacement'
    elif failure == 'missing':
        # An unnamed kind is deliberately not treated as a valid name.
        agents = [dict(agent, name=None)]
    elif failure == 'ambiguous':
        agents.append(dict(agent, pane_id='other'))
    else:
        error = 'agent not found' if failure == 'send' else json.dumps({'id': 'cli:agent:prompt', 'error': {'code': 'not_found', 'message': 'agent target claude not found'}})
        tg.messages.send.side_effect = OSError(error)
    monkeypatch.setattr(tg.team, 'herdr', Mock(return_value={'agents': agents}))
    bridge.handle(message('do work'))
    reply = bridge.bot.send.call_args.args[1]
    assert "couldn&#x27;t reach claude" in reply
    if failure not in ('send', 'send-json'):
        tg.messages.send.assert_not_called()
    if failure == 'send-json':
        assert 'agent target claude not found' in reply and 'cli:agent:prompt' not in reply
    record = json.loads((bridge.project / '.tomville/messages.jsonl').read_text())
    assert record['to'] == 'claude' and record['via'] == 'telegram-error'
    assert "couldn't reach claude" in record['text']
    output = capsys.readouterr().err
    assert 'Telegram:' in output and 'T' in output[:20] and '+00:00' in output


def test_error_reply_failure_is_also_logged_with_token_redacted(bridge, monkeypatch, capsys):
    bridge.bot.token = '123:fake-private'
    monkeypatch.setattr(tg.team, 'herdr', Mock(side_effect=OSError('agent not found 123:fake-private')))
    bridge.bot.send.side_effect = OSError('https://api.telegram.org/bot123:fake-private/sendMessage timed out')
    bridge.handle(message('do work'))
    records = [json.loads(line) for line in (bridge.project / '.tomville/messages.jsonl').read_text().splitlines()]
    assert len(records) == 2
    assert 'failure reply' in records[-1]['text']
    assert '123:fake-private' not in json.dumps(records) + capsys.readouterr().err


def test_http_error_preserves_short_reason_without_token():
    from urllib.error import HTTPError
    error = HTTPError('https://api.telegram.org/bot123:fake/sendMessage', 403, 'Forbidden', {}, io.BytesIO(json.dumps({'ok': False, 'error_code': 403, 'description': 'Forbidden: bot blocked 123:fake'}).encode()))
    bot = tg.Bot('123:fake', Mock(side_effect=error))
    with pytest.raises(OSError, match='403.*Forbidden: bot blocked') as exc:
        bot.call('sendMessage')
    assert '123:fake' not in str(exc.value)


def test_ipv6_stall_falls_back_and_future_calls_prefer_ipv4(monkeypatch):
    import socket
    import ssl
    addresses = [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443, 0, 0)),
                 (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::2', 443, 0, 0)),
                 (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    monkeypatch.setattr(tg.socket, 'getaddrinfo', lambda *args, **kw: addresses.copy())
    sockets = []
    class Socket:
        def __init__(self, family, *args):
            self.family, self.timeouts, self.closed = family, [], False
            sockets.append(self)
        def settimeout(self, timeout):
            self.timeouts.append(timeout)
        def connect(self, endpoint):
            if self.family == socket.AF_INET6:
                raise TimeoutError('IPv6 stalled')
        def close(self):
            self.closed = True
    monkeypatch.setattr(tg.socket, 'socket', Socket)
    handler = tg.TelegramHTTPSHandler()
    def do_open(factory, request, **kwargs):
        connection = factory('api.telegram.org', timeout=request.timeout, **kwargs)
        assert connection.host == 'api.telegram.org'
        assert connection._context.check_hostname and connection._context.verify_mode == ssl.CERT_REQUIRED
        connection._create_connection((connection.host, connection.port), connection.timeout, connection.source_address)
        return io.BytesIO(json.dumps(API['sendMessage']).encode())
    monkeypatch.setattr(handler, 'do_open', do_open)
    def opener(request, timeout):
        request.timeout = timeout
        return handler.https_open(request)
    bot = tg.Bot('123:fake', opener)
    bot.call('sendMessage', chat_id=42, text='one')
    bot.call('sendMessage', chat_id=42, text='two')
    assert [sock.family for sock in sockets] == [socket.AF_INET6, socket.AF_INET, socket.AF_INET]
    assert sockets[0].timeouts == [1] and sockets[0].closed
    assert sockets[1].timeouts == [40, 40]  # preserve long-poll read timeout
    assert handler.prefer_ipv4


def test_default_bot_uses_its_own_fallback_opener(monkeypatch):
    opener = Mock()
    build = Mock(return_value=opener)
    monkeypatch.setattr(tg.urllib.request, 'build_opener', build)
    bot = tg.Bot('123:fake')
    assert isinstance(build.call_args.args[0], tg.TelegramHTTPSHandler)
    assert bot.opener == opener.open


def test_unnamed_worker_resolves_by_recorded_terminal(bridge, monkeypatch):
    agents = json.loads((FIXTURES / 'herdr_named_agents.json').read_text())['result']['agents']
    worker = next(a for a in agents if a.get('name') == 'codex1')
    worker.pop('name')
    tg.team.save_state(bridge.project, {'agents': {'codex-1': {'pane': worker['pane_id'], 'terminal': worker['terminal_id'], 'kind': 'codex'}}})
    monkeypatch.setattr(tg.team, 'herdr', Mock(return_value={'agents': agents}))
    bridge.handle(message('/codex_1 hello'))
    assert tg.messages.send.call_args.kwargs['target'] == worker['pane_id']


def test_notification_error_is_timestamped_and_logged(bridge, monkeypatch, capsys):
    import asyncio
    from tomville.core import events
    from tomville.core.models import Card, CardChanged, Column
    async def run():
        reported = asyncio.Event()
        class Reader:
            agents, cards = {}, {}
            def __init__(self, *args):
                pass
            async def run(self, emit):
                emit(CardChanged(Card('#1', 'Review', Column.REVIEW), Column.DOING))
                await asyncio.wait_for(reported.wait(), 2)
        original = bridge.error
        def report(*args, **kwargs):
            result = original(*args, **kwargs)
            reported.set()
            return result
        monkeypatch.setattr(bridge, 'error', report)
        monkeypatch.setattr(events, 'EventReader', Reader)
        bridge.bot.call.side_effect = lambda method, **kw: [] if method == 'getUpdates' else True
        bridge.bot.send.side_effect = OSError('network unreachable')
        await asyncio.wait_for(tg._run(bridge), 3)
    asyncio.run(asyncio.wait_for(run(), 5))
    assert 'notification failed: network unreachable' in capsys.readouterr().err
    assert 'notification failed: network unreachable' in (bridge.project / '.tomville/messages.jsonl').read_text()


def test_healthy_ipv6_and_ipv6_only_remain_usable(monkeypatch):
    import socket
    endpoint = ('::1', 443, 0, 0)
    monkeypatch.setattr(tg.socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', endpoint)])
    sock = Mock()
    monkeypatch.setattr(tg.socket, 'socket', Mock(return_value=sock))
    handler = tg.TelegramHTTPSHandler()
    assert handler.connect(('api.telegram.org', 443), 40) == sock
    sock.connect.assert_called_once_with(endpoint)
    assert sock.settimeout.call_args_list[0].args == (1,)
    assert sock.settimeout.call_args_list[1].args == (40,)
    assert not handler.prefer_ipv4
    sock.close.assert_not_called()


def test_connect_closes_all_failed_sockets(monkeypatch):
    import socket
    addresses = [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443, 0, 0)),
                 (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    monkeypatch.setattr(tg.socket, 'getaddrinfo', lambda *a, **kw: addresses.copy())
    sockets = [Mock(), Mock()]
    sockets[0].connect.side_effect = TimeoutError('IPv6 timed out')
    sockets[1].connect.side_effect = OSError('IPv4 unreachable')
    monkeypatch.setattr(tg.socket, 'socket', Mock(side_effect=sockets))
    with pytest.raises(OSError, match='IPv4 unreachable'):
        tg.TelegramHTTPSHandler().connect(('api.telegram.org', 443), 40)
    assert all(sock.close.call_count == 1 for sock in sockets)


def test_plain_phone_prefix_is_delivered_but_not_added_to_log(bridge, monkeypatch):
    import subprocess
    bridge.target_pane = Mock(return_value='lead-pane')
    monkeypatch.setattr(tg.messages, 'send', send_message)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, 'sent', ''))
    monkeypatch.setattr(tg.messages.subprocess, 'run', run)
    bridge.handle(message('Please check this\nand report back'))
    assert run.call_args.args[0] == ['herdr', 'agent', 'prompt', 'lead-pane',
                                  '📱 Tom (Telegram): Please check this\nand report back']
    entry = json.loads((bridge.project / '.tomville/messages.jsonl').read_text())
    assert entry['text'] == 'Please check this\nand report back'
    assert (entry['from'], entry['to'], entry['via']) == ('tom', 'claude', 'telegram')
