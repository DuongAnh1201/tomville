"""Offline hook contract scenarios, never Claude sessions/herdr/network/tokens."""
import copy
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tomville.cli import main
from tomville.core import approvals as ap, telegram as tg, telegram_approvals as ta, ville
from tomville.core.settings import load_settings

FIXTURES = Path(__file__).parent / 'fixtures'
CONTRACTS = json.loads((FIXTURES / 'claude_hook_contracts.json').read_text())


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path/'global.toml'))
    monkeypatch.setenv('HERDR_ENV', '1')
    monkeypatch.setenv('HERDR_PANE_ID', 'lead-pane')
    monkeypatch.setattr(ap.messages, 'repo_root', lambda p: tmp_path)
    ville.write_ville(tmp_path, {'team': {'lead': 'boss', 'shape': 'lead'},
        'telegram': {'enabled': True, 'approvals': True, 'id': 'fixture78'},
        'agents': {'boss': {'kind': 'claude'}}})
    tg.team.save_state(tmp_path, {'agents': {}, 'lead_pane': 'lead-pane'})
    bot = Mock(token='123:fake')
    counter = iter(range(100, 1000))
    bot.send.side_effect = lambda *a, **kw: {'message_id': next(counter)}
    bridge = tg.Bridge(tmp_path, load_settings(tmp_path), bot, {'chat_id': 42, 'paused': False})
    bridge.approval_clock = lambda: 100
    bridge.target_pane = Mock(return_value='lead-pane')
    monkeypatch.setattr(tg.messages, 'send', Mock())
    monkeypatch.setattr(tg.team, 'herdr', Mock(side_effect=AssertionError('no live herdr')))
    return bridge


def payload(bridge, kind):
    value = copy.deepcopy(CONTRACTS[kind])
    value['cwd'] = str(bridge.project)
    return value


def submit(bridge, kind='permission-request'):
    return ap.submit(bridge.project, bridge.settings, 'lead-pane', kind, payload(bridge, kind), 100)


def read(bridge, data):
    return json.loads(ap.path(bridge.project, data['id']).read_text())


def tap(bridge, data, choice, *, chat=42, sender=42, message_id=None):
    current = read(bridge, data)
    return bridge.handle({'callback_query': {'id': 'callback-fixture', 'from': {'id': sender},
        'data': data['id'] + ':' + choice, 'message': {'message_id': message_id or current['messages'][0]['id'],
        'chat': {'type': 'private', 'id': chat}}}})


def reply(bridge, data, text, question=0):
    current = read(bridge, data)
    bridge.handle({'message': {'from': {'id': 42}, 'chat': {'type': 'private', 'id': 42}, 'text': text,
        'reply_to_message': {'message_id': current['messages'][question]['id']}}})


@pytest.mark.parametrize('choice,behavior', [('allow', 'allow'), ('deny', 'deny'), ('reason', 'deny'), ('timeout', 'deny')])
def test_permission_hook_round_trip(bridge, choice, behavior):
    output = io.StringIO()
    now = [100]
    def sleep(_):
        data = json.loads(next((bridge.project/ap.DIRECTORY).glob('*.json')).read_text())
        ta.scan(bridge)
        if choice == 'reason':
            reply(bridge, data, 'Please run the narrower test first')
        elif choice == 'timeout':
            now[0] = 701
        else:
            tap(bridge, data, choice)
    assert ap.hook('permission-request', io.StringIO(json.dumps(payload(bridge, 'permission-request'))),
                   out=output, sleep=sleep, clock=lambda: now[0]) == 0
    result = json.loads(output.getvalue())['hookSpecificOutput']['decision']
    assert result['behavior'] == behavior
    assert 'updatedPermissions' not in result
    if choice == 'reason': assert 'narrower test' in result['message']
    if choice == 'timeout': assert result['message'] == 'no answer from Tom within 10 minutes'
    log = (bridge.project/'.tomville/messages.jsonl').read_text()
    assert 'telegram-approval' in log
    assert 'uv run pytest' in bridge.bot.send.call_args_list[0].args[1]
    assert str(bridge.project) in bridge.bot.send.call_args_list[0].args[1]


@pytest.mark.parametrize('change', ['worker', 'outside', 'disabled', 'pipeline', 'subagent', 'approvals_off'])
def test_ineligible_sessions_do_nothing(bridge, monkeypatch, change):
    value = payload(bridge, 'permission-request')
    if change == 'worker': monkeypatch.setenv('HERDR_PANE_ID', 'worker-pane')
    elif change == 'outside': monkeypatch.delenv('HERDR_ENV')
    elif change == 'subagent': value['agent_id'] = 'subagent-fixture'
    else:
        ville.update_ville(bridge.project, {'team': {'shape': 'pipeline'}} if change == 'pipeline' else
                           {'telegram': {'enabled': False}} if change == 'disabled' else {'telegram': {'approvals': False}})
    output = io.StringIO()
    ap.hook('permission-request', io.StringIO(json.dumps(value)), out=output)
    assert output.getvalue() == ''
    assert not list((bridge.project/ap.DIRECTORY).glob('*.json'))
    bridge.bot.send.assert_not_called()


@pytest.mark.parametrize('change', ['chat', 'sender', 'message', 'expired', 'paused', 'lead_changed', 'shape', 'approvals_off'])
def test_callbacks_cannot_answer_wrong_or_expired_request(bridge, change):
    data = submit(bridge)
    ta.scan(bridge)
    kw = {}
    if change == 'chat': kw['chat'] = 99
    elif change == 'sender': kw['sender'] = 99
    elif change == 'message': kw['message_id'] = 999
    elif change == 'expired': bridge.approval_clock = lambda: 701
    elif change == 'paused': bridge.config['paused'] = True
    elif change == 'shape': bridge.settings.team = 'pipeline'
    elif change == 'approvals_off': bridge.settings.telegram['approvals'] = False
    else: tg.team.save_state(bridge.project, {'agents': {}, 'lead_pane': 'different'})
    tap(bridge, data, 'allow', **kw)
    assert read(bridge, data)['status'] == 'pending'
    tg.messages.send.assert_not_called()


def test_duplicate_tap_restart_and_late_reply_do_not_reuse_answer(bridge):
    data = submit(bridge)
    ta.scan(bridge)
    sent = bridge.bot.send.call_count
    ta.scan(bridge)
    assert bridge.bot.send.call_count == sent
    tap(bridge, data, 'allow')
    tap(bridge, data, 'deny')
    reply(bridge, data, 'late denial')
    assert read(bridge, data)['answer']['behavior'] == 'allow'
    tg.messages.send.assert_not_called()
    assert (bridge.project/ap.DIRECTORY).stat().st_mode & 0o777 == 0o700
    assert ap.path(bridge.project, data['id']).stat().st_mode & 0o777 == 0o600
    bridge.handle({'callback_query': {'id':'bad','from':{'id':42},'data':'../../bad:allow',
        'message':{'chat':{'id':42,'type':'private'},'message_id':100}}})


def test_questions_single_multi_other_and_hook_answer(bridge):
    output = io.StringIO()
    def sleep(_):
        data = json.loads(next((bridge.project/ap.DIRECTORY).glob('*.json')).read_text())
        ta.scan(bridge)
        tap(bridge, data, 'done')
        assert read(bridge, data)['status'] == 'pending'
        tap(bridge, data, 'q0.0')
        tap(bridge, data, 'q1.0')
        tap(bridge, data, 'q1.1')
        assert read(bridge, data)['selections']['1'] == ['Tests', 'Lint']
        tap(bridge, data, 'other0')
        reply(bridge, data, 'Svelte', question=0)
        tap(bridge, data, 'done')
    ap.hook('ask-user-question', io.StringIO(json.dumps(payload(bridge, 'ask-user-question'))), out=output,
            clock=lambda:100, sleep=sleep)
    result = json.loads(output.getvalue())['hookSpecificOutput']
    assert result['permissionDecision'] == 'allow'
    assert result['updatedInput']['questions'] == payload(bridge,'ask-user-question')['tool_input']['questions']
    assert result['updatedInput']['answers'] == {'Which framework?':'Svelte','Which checks?':'Tests, Lint'}
    assert 'telegram-question' in (bridge.project/'.tomville/messages.jsonl').read_text()


@pytest.mark.parametrize('cancel', [True, False])
def test_question_cancel_and_timeout(bridge, cancel):
    now = [100]
    def sleep(_):
        data = json.loads(next((bridge.project/ap.DIRECTORY).glob('*.json')).read_text())
        ta.scan(bridge)
        if cancel: tap(bridge, data, 'cancel')
        else: now[0] = 701
    output = io.StringIO()
    ap.hook('ask-user-question', io.StringIO(json.dumps(payload(bridge,'ask-user-question'))), out=output,
            clock=lambda:now[0], sleep=sleep)
    result = json.loads(output.getvalue())['hookSpecificOutput']
    assert result['permissionDecision'] == 'deny'
    assert ('cancelled' if cancel else '10 minutes') in result['permissionDecisionReason']


@pytest.mark.parametrize('choice', ['retry', 'leave'])
def test_safety_block_notice_and_retry_is_toms_message(bridge, choice):
    output = io.StringIO()
    ap.hook('permission-denied', io.StringIO(json.dumps(payload(bridge,'permission-denied'))), out=output, clock=lambda:100)
    assert output.getvalue() == ''
    data = json.loads(next((bridge.project/ap.DIRECTORY).glob('*.json')).read_text())
    ta.scan(bridge)
    assert 'blocking it for safety' in bridge.bot.send.call_args.args[1]
    tap(bridge, data, choice)
    tap(bridge, data, choice)
    if choice == 'retry':
        tg.messages.send.assert_called_once()
        assert tg.messages.send.call_args.args[2].startswith('Tom approved: Bash')
        assert tg.messages.send.call_args.kwargs == {'sender':'tom','via':'telegram-approval','target':'lead-pane'}
    else: tg.messages.send.assert_not_called()


@pytest.mark.parametrize('text,expected', [('All done.',False), ('**Proceed?**',True), ('Use `pytest`?',True)])
def test_stop_only_forwards_questions_and_safe_markdown(bridge, text, expected):
    value = payload(bridge, 'stop'); value['last_assistant_message'] = text
    output = io.StringIO()
    ap.hook('stop', io.StringIO(json.dumps(value)), out=output, clock=lambda:100)
    ta.scan(bridge)
    assert output.getvalue() == ''
    assert bool(bridge.bot.send.call_count) == expected
    if text.startswith('**'): assert '<b>Proceed?</b>' in bridge.bot.send.call_args.args[1]
    if 'pytest' in text: assert '<code>pytest</code>' in bridge.bot.send.call_args.args[1]
    assert ta.markdown('<script>bad</script> *ok*') == '&lt;script&gt;bad&lt;/script&gt; <i>ok</i>'


def test_diff_request_and_expiry_notice(bridge):
    value = payload(bridge,'permission-request')
    value.update(tool_name='Edit', tool_input={'file_path':'app.py','old_string':'old\n','new_string':'new\n'})
    data = ap.submit(bridge.project, bridge.settings,'lead-pane','permission-request',value,100)
    ta.scan(bridge)
    text = bridge.bot.send.call_args.args[1]
    assert '<code class="language-diff">' in text and '-old' in text and '+new' in text
    bridge.approval_clock = lambda:701
    ta.scan(bridge)
    assert read(bridge,data)['status'] == 'expired'
    assert 'Expired' in bridge.bot.call.call_args.kwargs['text']
    tap(bridge,data,'allow')
    assert read(bridge,data)['status'] == 'expired'


def test_unsupported_setup_stops_before_token_and_runtime_sends_only_apology(bridge):
    bridge.settings.team = 'pipeline'
    hidden = Mock(side_effect=AssertionError('must not request token'))
    with pytest.raises(ValueError, match="Sorry, Telegram isn't ready for the pipeline team yet"):
        tg.setup(bridge.project, bridge.settings, lambda *a: '', hidden=hidden)
    hidden.assert_not_called()
    for text in ('hello','/status','/boss hi','/resume'):
        bridge.handle({'message':{'from':{'id':42},'chat':{'id':42,'type':'private'},'text':text}})
        assert bridge.bot.send.call_args.args[1] == 'Sorry, we haven&#x27;t done Telegram for the pipeline team yet.'
    count = bridge.bot.send.call_count
    ta.scan(bridge)
    bridge.blocked({'name':'worker'})
    assert bridge.bot.send.call_count == count
    tg.messages.send.assert_not_called()


def test_hook_install_and_cli_dispatch(tmp_path, monkeypatch):
    target = tmp_path/'claude.json'
    ville.install_hook(target)
    hooks = json.loads(target.read_text())['hooks']
    assert hooks['PermissionRequest'][0]['hooks'][0]['timeout'] > 600
    assert hooks['PreToolUse'][1]['matcher'] == 'AskUserQuestion'
    assert hooks['PreToolUse'][1]['hooks'][0]['timeout'] > 600
    assert hooks['PermissionDenied'][0]['hooks'][0]['command'] == 'tmv hook permission-denied'
    run = Mock(return_value=0)
    monkeypatch.setattr(ap,'hook',run)
    assert main(['hook','permission-request']) == 0
    run.assert_called_once_with('permission-request')


def test_permission_io_error_fails_closed(bridge, monkeypatch):
    monkeypatch.setattr(ap, 'submit', Mock(side_effect=OSError('fixture disk failure')))
    output = io.StringIO()
    ap.hook('permission-request', io.StringIO(json.dumps(payload(bridge,'permission-request'))), out=output)
    assert json.loads(output.getvalue())['hookSpecificOutput']['decision']['behavior'] == 'deny'


def test_setting_changes_cancel_a_waiting_hook(bridge):
    output = io.StringIO()
    def sleep(_):
        ville.update_ville(bridge.project, {'telegram': {'enabled': False}})
    ap.hook('permission-request', io.StringIO(json.dumps(payload(bridge,'permission-request'))), out=output,
            sleep=sleep, clock=lambda:100)
    decision = json.loads(output.getvalue())['hookSpecificOutput']['decision']
    assert decision['behavior'] == 'deny' and 'cancelled' in decision['message']


def test_paused_bot_issues_no_requests_and_wrong_question_tool_is_ignored(bridge):
    data = submit(bridge)
    bridge.config['paused'] = True
    ta.scan(bridge)
    assert not read(bridge,data).get('issued')
    bridge.bot.send.assert_not_called()
    value = payload(bridge,'ask-user-question'); value['tool_name'] = 'Bash'
    output = io.StringIO()
    ap.hook('ask-user-question', io.StringIO(json.dumps(value)), out=output)
    assert output.getvalue() == ''
    assert len(list((bridge.project/ap.DIRECTORY).glob('*.json'))) == 1


def test_request_text_splits_safely_and_keeps_action_buttons_on_last_chunk(bridge):
    from tomville.core.telegram_text import chunks
    value = payload(bridge,'permission-request')
    value['tool_input']['command'] = 'echo "<unsafe>"\n' * 1500
    data = ap.submit(bridge.project,bridge.settings,'lead-pane','permission-request',value,100)
    text, markup = ta.issue(bridge,data)[0]
    parts = chunks(text)
    assert len(parts) > 1 and '&lt;unsafe&gt;' in ''.join(parts)
    assert all(len(part) <= 4096 for part in parts)
    assert all(part.count('<pre>') == part.count('</pre>') for part in parts)
    assert len(markup['inline_keyboard'][0]) == 2


def test_runtime_scans_requests_while_long_poll_waits(bridge, monkeypatch):
    import asyncio
    import threading
    from tomville.core import events
    delivered = threading.Event()
    class Reader:
        agents, cards = {}, {}
        def __init__(self, *args): pass
        async def run(self, emit):
            async with asyncio.timeout(2):
                while not delivered.is_set():
                    await asyncio.sleep(.01)
    def call(method, **kwargs):
        if method == 'getUpdates':
            assert delivered.wait(2), 'hook delivery must not wait for getUpdates'
            return []
        return True
    bridge.bot.call.side_effect = call
    bridge.bot.send.side_effect = lambda *a, **kw: (delivered.set() or {'message_id':100})
    monkeypatch.setattr(events,'EventReader',Reader)
    monkeypatch.setattr(tg,'load_config',lambda settings:bridge.config)
    submit(bridge)
    async def run():
        async with asyncio.timeout(3):
            await tg._run(bridge)
    asyncio.run(run())
    assert delivered.is_set()


def test_non_lead_runtime_drops_all_events_and_hook_notices(bridge, monkeypatch):
    import asyncio
    import threading
    from tomville.core import events
    from tomville.core.models import AgentStatusChanged, CardChanged, Card, Column, Status
    handled = threading.Event()
    class Reader:
        agents, cards = {}, {}
        def __init__(self, *args): pass
        async def run(self, emit):
            emit(AgentStatusChanged('boss',Status.WORKING,Status.BLOCKED))
            emit(CardChanged(Card('#1','Done',Column.DONE),Column.REVIEW))
            async with asyncio.timeout(2):
                while not handled.is_set(): await asyncio.sleep(.01)
    def call(method, **kwargs):
        if method == 'getUpdates':
            if not handled.is_set():
                return [{'update_id':1,'message':{'from':{'id':42},'chat':{'id':42,'type':'private'},'text':'hi'}}]
            return []
        return True
    bridge.bot.call.side_effect = call
    bridge.bot.send.side_effect = lambda *a, **kw: (handled.set() or {'message_id':100})
    monkeypatch.setattr(events,'EventReader',Reader)
    monkeypatch.setattr(tg,'load_config',lambda settings:bridge.config)
    monkeypatch.setattr(tg,'change_config',lambda settings,**kw:dict(bridge.config,**kw))
    submit(bridge,'stop')
    ville.update_ville(bridge.project,{'team':{'shape':'pipeline'}})
    async def run():
        async with asyncio.timeout(3): await tg._run(bridge)
    asyncio.run(run())
    assert bridge.bot.send.call_count == 1
    assert 'pipeline team yet' in bridge.bot.send.call_args.args[1]
