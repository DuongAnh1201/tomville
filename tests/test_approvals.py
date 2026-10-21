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
    monkeypatch.setattr(Path, 'home', lambda: tmp_path/'home')
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
        assert tg.messages.send.call_args.kwargs == {'sender':'tom','via':'telegram-approval','target':'lead-pane','prompt_prefix':'📱 Tom (Telegram): ','process_timeout':10}
    else: tg.messages.send.assert_not_called()


@pytest.mark.parametrize('text,expected', [
    ('All done.', False), ('**Proceed?**', True), ('Use `pytest`?', True),
    ('Want to do it now?\nStart with step 1: run the checks.', True),
    ('Want to do it now? Start with step 1: run the checks.', True),
    ('Summary first.\nReady to proceed？\nNext steps below.', True),
    ('```python\nprint("Ready?")\n```\nDone.', False),
    ('~~~text\nReady?\n~~~', False), ('    Ready?\nDone.', False),
    ('Use `ready?` here.', False), ('Use ``is `ready?` `` here.', False),
    ('See https://example.com/?next=ready', False), ('See https://example.com/?', False),
    ('He said "Ready? https://example.com/"', False), ('See [docs](./help?ready)', False),
    ('> Ready?\nThat was quoted.', False), ('He asked "Ready?"', False),
    ("He asked 'Ready?'", False), ('He asked “Ready?”', False),
    ("What's next?\nI'll wait.", True),
])
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
            if not handled.is_set() and kwargs.get('offset',0) == 0:
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


@pytest.mark.parametrize('kind,tool,inputs,expected', [
    ('permission-request','Bash',{'command':'uv run pytest'},'Bash: uv run pytest'),
    ('permission-request','Edit',{'file_path':'app.py','old_string':'old','new_string':'new'},'Edit: app.py'),
    ('permission-request','Write',{'file_path':'new.py','content':'not a log summary'},'Write: new.py'),
    ('ask-user-question',None,None,'Which framework?; Which checks?'),
    ('permission-denied',None,None,'Bash: gh pr merge 69 --squash — Auto mode could not evaluate this action and is blocking it for safety'),
    ('stop',None,None,'First line?'),
])
def test_request_log_contains_only_brief_action_or_question(bridge, kind, tool, inputs, expected):
    value = payload(bridge,kind)
    value.update(session_id='private-session-fixture', transcript_path='/private/transcript-fixture.jsonl', cwd='/private/metadata-cwd')
    if tool is not None: value.update(tool_name=tool,tool_input=inputs)
    if kind == 'stop': value['last_assistant_message'] = 'First line?\nSecond line is not a request summary'
    ap.submit(bridge.project,bridge.settings,'lead-pane',kind,value,100)
    entry = json.loads((bridge.project/'.tomville/messages.jsonl').read_text())
    assert entry['text'] == 'Requested ' + kind + ': ' + expected
    assert entry['from'] == 'boss'
    assert entry['via'] == ('telegram-approval' if kind.startswith('permission-') else 'telegram-question')
    for excluded in ('session_id','transcript_path','private-session-fixture','/private/','old_string','new_string','not a log summary','Second line'):
        assert excluded not in entry['text']


def test_long_hook_requests_keep_log_brief_and_one_line(bridge):
    value = payload(bridge,'permission-denied')
    value['tool_input']['command'] = 'echo line\n' * 500
    value['reason'] = 'Reason to deny ' * 100
    ap.submit(bridge.project,bridge.settings,'lead-pane','permission-denied',value,100)
    entry = json.loads((bridge.project/'.tomville/messages.jsonl').read_text())
    assert len(entry['text']) <= 512 and len(entry['text'].splitlines()) == 1
    assert 'Bash: echo line' in entry['text'] and ' — Reason to deny' in entry['text']
    assert '…' in entry['text']


def test_stop_forwards_whole_message_bolds_question_and_keeps_code(bridge):
    text = ('Summary first.\n```python\nprint("Example?")\n```\n'
            'Ready to proceed? Start with step 1.\n*More context below.*\n' + 'Extra detail. ' * 600)
    value = payload(bridge,'stop'); value['last_assistant_message'] = text
    output = io.StringIO()
    ap.hook('stop',io.StringIO(json.dumps(value)),out=output,clock=lambda:100)
    ta.scan(bridge)
    rendered = bridge.bot.send.call_args.args[1]
    assert rendered.startswith('💬 Summary first.\n')
    assert '<b>Ready to proceed? Start with step 1.</b>' in rendered
    assert '<pre><code class="language-python">print(&quot;Example?&quot;)\n</code></pre>' in rendered
    assert '<i>More context below.</i>' in rendered
    assert rendered.endswith('Extra detail. ' * 600)
    assert output.getvalue() == ''
    assert not bridge.bot.send.call_args.kwargs  # Notice only, no approval buttons.
    parts = tg.chunks(rendered)
    assert len(parts) > 1 and all(len(part) <= 4096 for part in parts)
    assert ta.markdown('Context\n*Ready?*\nNotes.', bold_lines={1}) == 'Context\n<i><b>Ready?</b></i>\nNotes.'
    assert ta.markdown('Use `pytest`?', bold_lines={0}) == '<b>Use </b><code>pytest</code><b>?</b>'


@pytest.mark.parametrize('change', ['worker', 'disabled'])
def test_middle_question_still_requires_lead_and_telegram(bridge, monkeypatch, change):
    if change == 'worker': monkeypatch.setenv('HERDR_PANE_ID','worker-pane')
    else: ville.update_ville(bridge.project,{'telegram':{'enabled':False}})
    value = payload(bridge,'stop'); value['last_assistant_message'] = 'Ready?\nNotes follow.'
    output = io.StringIO()
    ap.hook('stop',io.StringIO(json.dumps(value)),out=output,clock=lambda:100)
    ta.scan(bridge)
    bridge.bot.send.assert_not_called()
    assert output.getvalue() == ''

@pytest.mark.parametrize('slow', ['send', 'herdr'])
def test_runtime_applies_taps_while_slow_io_is_outstanding(bridge, monkeypatch, slow):
    import asyncio
    import threading
    from tomville.core import events
    request = submit(bridge)
    ta.scan(bridge)
    current = read(bridge,request)
    callback = {'update_id':20,'callback_query':{'id':'fast-tap','from':{'id':42},
        'data':request['id'] + ':allow','message':{'message_id':current['messages'][0]['id'],
        'chat':{'id':42,'type':'private'}}}}
    started, release, acknowledged = threading.Event(), threading.Event(), threading.Event()
    if slow == 'send':
        submit(bridge,'permission-denied')
        def send(*args, **kwargs):
            started.set()
            assert release.wait(2), 'tap decision must not wait for outbound send'
            return {'message_id':200}
        bridge.bot.send.side_effect = send
    else:
        def target(_):
            started.set()
            assert release.wait(2), 'tap decision must not wait for herdr'
            return 'lead-pane'
        bridge.target_pane.side_effect = target
    calls = []
    def call(method, **kwargs):
        calls.append(method)
        if method == 'answerCallbackQuery':
            acknowledged.set()
            return True
        if method == 'getUpdates':
            if slow == 'herdr' and calls.count('getUpdates') == 1:
                return [{'update_id':10,'message':{'from':{'id':42},'chat':{'id':42,'type':'private'},'text':'slow message'}}]
            assert started.wait(2)
            return [callback] if calls.count('getUpdates') == (2 if slow == 'herdr' else 1) else []
        return True
    bridge.bot.call.side_effect = call
    class Reader:
        agents, cards = {}, {}
        def __init__(self,*args): pass
        async def run(self, emit):
            async with asyncio.timeout(2):
                while read(bridge,request)['status'] != 'answered':
                    await asyncio.sleep(.005)
            assert acknowledged.is_set()
            assert not release.is_set()
            release.set()
    monkeypatch.setattr(events,'EventReader',Reader)
    monkeypatch.setattr(tg,'load_config',lambda settings:bridge.config)
    monkeypatch.setattr(tg,'change_config',lambda settings,**kw:dict(bridge.config,**kw))
    async def run():
        async with asyncio.timeout(3): await tg._run(bridge)
    try:
        asyncio.run(run())
    finally:
        release.set()
    assert read(bridge,request)['answer']['behavior'] == 'allow'
    assert bridge.config['offset'] == 21
    assert bridge.config['last_poll'] > 0


def test_callback_ack_failure_is_nonfatal_and_precedes_decision(bridge):
    data = submit(bridge)
    ta.scan(bridge)
    def call(method, **kwargs):
        if method == 'answerCallbackQuery':
            assert read(bridge,data)['status'] == 'pending'
            raise OSError('query is too old')
        # Even edits happen after the request lock has been released.
        with ap.locked(bridge.project,data['id'],timeout=0) as current:
            assert current['status'] == 'answered'
        return True
    bridge.bot.call.side_effect = call
    tap(bridge,data,'allow')
    assert read(bridge,data)['answer']['behavior'] == 'allow'
    assert 'acknowledgement failed' in (bridge.project/'.tomville/messages.jsonl').read_text()


def test_scan_sends_without_request_file_lock(bridge):
    data = submit(bridge)
    def send(*args, **kwargs):
        with ap.locked(bridge.project,data['id'],timeout=0) as current:
            assert current['issued']
        return {'message_id':100}
    bridge.bot.send.side_effect = send
    ta.scan(bridge)
    assert read(bridge,data)['messages'] == [{'id':100,'question':0}]


def test_busy_file_lock_has_deadline_and_scan_skips_it(bridge):
    data = submit(bridge)
    with ap.locked(bridge.project,data['id']):
        with pytest.raises(TimeoutError,match='file lock timed out'):
            with ap.locked(bridge.project,data['id'],timeout=0): pass
        ta.scan(bridge)
    bridge.bot.send.assert_not_called()
    ta.scan(bridge)
    bridge.bot.send.assert_called_once()


def test_timed_out_scan_does_not_fill_workers_or_block_decisions(bridge, monkeypatch):
    import asyncio
    import threading
    from tomville.core import events
    request = submit(bridge)
    ta.scan(bridge)
    current = read(bridge,request)
    started, timed_out, release = threading.Event(), threading.Event(), threading.Event()
    scans = []
    def scan(_):
        scans.append(1)
        started.set()
        assert release.wait(2)
    original_error = bridge.error
    def error(context, exception, *args):
        if context == 'hook request failed' and isinstance(exception,TimeoutError): timed_out.set()
        return original_error(context,exception,*args)
    bridge.error = error
    callback = {'update_id':1,'callback_query':{'id':'timed-out-scan-tap','from':{'id':42},'data':request['id']+':allow',
        'message':{'message_id':current['messages'][0]['id'],'chat':{'id':42,'type':'private'}}}}
    sent = [False]
    def call(method,**kwargs):
        if method == 'getUpdates' and not sent[0]:
            assert started.wait(1) and timed_out.wait(1)
            sent[0] = True
            return [callback]
        return [] if method == 'getUpdates' else True
    bridge.bot.call.side_effect = call
    class Reader:
        agents, cards = {}, {}
        def __init__(self,*args): pass
        async def run(self,emit):
            async with asyncio.timeout(2):
                while read(bridge,request)['status'] != 'answered': await asyncio.sleep(.005)
            release.set()
    monkeypatch.setattr(events,'EventReader',Reader)
    monkeypatch.setattr(tg.telegram_approvals,'scan',scan)
    monkeypatch.setattr(tg,'load_config',lambda settings:bridge.config)
    monkeypatch.setattr(tg,'change_config',lambda settings,**kw:dict(bridge.config,**kw))
    async def run():
        async with asyncio.timeout(3): await tg._run(bridge,worker_timeout=.02)
    try: asyncio.run(run())
    finally: release.set()
    assert len(scans) == 1
    assert read(bridge,request)['answer']['behavior'] == 'allow'


def test_callbacks_precede_ordinary_batch_messages_and_offset_never_rewinds(bridge, monkeypatch):
    import asyncio
    import threading
    from tomville.core import events
    request = submit(bridge)
    ta.scan(bridge)
    current = read(bridge,request)
    delivered = threading.Event()
    callback = {'update_id':2,'callback_query':{'id':'priority','from':{'id':42},'data':request['id']+':allow',
        'message':{'message_id':current['messages'][0]['id'],'chat':{'id':42,'type':'private'}}}}
    ordinary = {'update_id':1,'message':{'from':{'id':42},'chat':{'id':42,'type':'private'},'text':'later'}}
    order, polls = [], []
    def call(method,**kwargs):
        if method == 'answerCallbackQuery': order.append('ack')
        if method == 'getUpdates':
            polls.append(kwargs['offset'])
            return [ordinary, callback] if len(polls)==1 else []
        return True
    bridge.bot.call.side_effect = call
    def send(*args,**kwargs):
        assert read(bridge,request)['answer']['behavior'] == 'allow'
        order.append('message')
        delivered.set()
    tg.messages.send.side_effect = send
    class Reader:
        agents, cards = {}, {}
        def __init__(self,*args): pass
        async def run(self,emit):
            async with asyncio.timeout(2):
                while not delivered.is_set(): await asyncio.sleep(.005)
    monkeypatch.setattr(events,'EventReader',Reader)
    monkeypatch.setattr(tg,'load_config',lambda settings:bridge.config)
    monkeypatch.setattr(tg,'change_config',lambda settings,**kw:dict(bridge.config,**kw))
    async def run():
        async with asyncio.timeout(3): await tg._run(bridge)
    asyncio.run(run())
    assert order == ['ack','message'] and bridge.config['offset'] == 3
    assert polls[0] == 0 and all(offset == 3 for offset in polls[1:])


def test_read_only_queue_scans_do_not_rewrite_request_history(bridge, monkeypatch):
    data = submit(bridge)
    ta.scan(bridge)
    write = Mock(wraps=ap.write)
    monkeypatch.setattr(ap,'write',write)
    ta.scan(bridge)
    assert read(bridge,data)['issued']
    write.assert_not_called()


@pytest.mark.parametrize('kind', list(ap.EVENTS))
@pytest.mark.parametrize('location', ['ville','subfolder','nested_repo','registered_outside'])
def test_hooks_find_owned_ville_from_pane_across_directories(bridge, monkeypatch, kind, location):
    project = bridge.project
    if location == 'ville': cwd = project
    elif location == 'subfolder': cwd = project/'docs'/'notes'
    elif location == 'nested_repo': cwd = project/'other-repo'/'src'
    else:
        cwd = project.parent/(project.name+'-outside')/'src'
        ap.leads.register(project,'lead-pane')
    cwd.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(ap.messages,'repo_root',lambda p:pytest.fail('ville lookup must not depend on Git cwd'))
    value = payload(bridge,kind); value['cwd'] = str(cwd)
    output = io.StringIO()
    def answer(_):
        files = list((project/ap.DIRECTORY).glob('*.json'))
        assert len(files) == 1
        with ap.locked(project,files[0].stem) as request:
            request.update(status='answered',answer={'behavior':'deny','reason':'fixture answer'})
    ap.hook(kind,io.StringIO(json.dumps(value)),out=output,clock=lambda:100,sleep=answer)
    files = list((project/ap.DIRECTORY).glob('*.json'))
    assert len(files) == 1
    request = json.loads(files[0].read_text())
    assert request['pane'] == 'lead-pane' and request['payload']['cwd'] == str(cwd)
    if cwd != project: assert not (cwd/ap.DIRECTORY).exists()
    if kind in ('permission-request','ask-user-question'):
        assert json.loads(output.getvalue())['hookSpecificOutput']['hookEventName'] == ap.EVENTS[kind]
    else: assert output.getvalue() == ''


@pytest.mark.parametrize('kind', list(ap.EVENTS))
@pytest.mark.parametrize('case', ['outside','different_pane','telegram_off','pipeline'])
def test_ville_lookup_never_answers_for_an_unowned_or_ineligible_ville(bridge, monkeypatch, kind, case):
    cwd = bridge.project
    if case == 'outside':
        cwd = cwd.parent/(cwd.name+'-outside'); cwd.mkdir()
    elif case == 'different_pane': monkeypatch.setenv('HERDR_PANE_ID','another-ville-pane')
    else:
        ville.update_ville(cwd,{'telegram':{'enabled':False}} if case == 'telegram_off' else {'team':{'shape':'pipeline'}})
    monkeypatch.setattr(ap.messages,'repo_root',lambda p:p)
    value = payload(bridge,kind); value['cwd'] = str(cwd)
    output = io.StringIO()
    ap.hook(kind,io.StringIO(json.dumps(value)),out=output,clock=lambda:100,
            sleep=lambda _:pytest.fail('unowned hook must not wait'))
    assert output.getvalue() == ''
    assert not list((bridge.project/ap.DIRECTORY).glob('*.json'))
    assert not list((cwd/ap.DIRECTORY).glob('*.json'))


def test_ville_lookup_skips_foreign_or_broken_inner_ville(bridge, monkeypatch):
    inner = bridge.project/'nested-ville'
    ville.write_ville(inner,{'team':{'lead':'other','shape':'lead'},'telegram':{'enabled':True,'approvals':True}})
    tg.team.save_state(inner,{'agents':{},'lead_pane':'other-pane'})
    cwd = inner/'src'; cwd.mkdir()
    monkeypatch.setattr(ap.messages,'repo_root',lambda p:inner)
    assert ap.resolve_ville(cwd,'lead-pane')[0] == bridge.project
    assert ap.resolve_ville(cwd,'other-pane')[0] == inner
    (inner/tg.team.STATE).write_text('{broken')
    assert ap.resolve_ville(cwd,'lead-pane')[0] == bridge.project
    assert ap.resolve_ville(cwd,'unrelated-pane') is None


@pytest.mark.parametrize('kind',list(ap.EVENTS))
@pytest.mark.parametrize('stale',['pane','telegram','missing','corrupt'])
def test_registered_mismatch_is_silent_without_cwd_fallback(bridge,kind,stale):
    project = bridge.project
    registered = project/'stale'
    ville.write_ville(registered,{'team':{'shape':'lead','lead':'other'},'telegram':{'enabled':True}})
    tg.team.save_state(registered,{'agents':{},'lead_pane':'lead-pane'})
    ap.leads.register(registered,'lead-pane')
    if stale == 'pane': tg.team.save_state(registered,{'agents':{},'lead_pane':'different-pane'})
    elif stale == 'telegram': ville.update_ville(registered,{'telegram':{'enabled':False}})
    elif stale == 'missing': (registered/'.tomville/ville.toml').unlink()
    else: ap.leads.registry_path().write_text('{broken')
    value = payload(bridge,kind)  # cwd has a valid matching ville; stale registry must still win.
    output = io.StringIO()
    ap.hook(kind,io.StringIO(json.dumps(value)),out=output,clock=lambda:100,
            sleep=lambda _:pytest.fail('stale registry must not wait or fall back'))
    assert output.getvalue() == ''
    assert not list((project/ap.DIRECTORY).glob('*.json'))


def test_worker_registry_entry_cannot_authorize_a_lead_hook(bridge,monkeypatch):
    ap.leads.register(bridge.project,'worker-pane')
    monkeypatch.setenv('HERDR_PANE_ID','worker-pane')
    output = io.StringIO()
    ap.hook('permission-request',io.StringIO(json.dumps(payload(bridge,'permission-request'))),out=output,
            sleep=lambda _:pytest.fail('worker must not wait'))
    assert output.getvalue() == ''
    assert not list((bridge.project/ap.DIRECTORY).glob('*.json'))
