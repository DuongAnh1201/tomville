"""Bot side of Claude hook requests; all callbacks stay in the paired chat."""
import difflib
from html import escape
import json
import re

from tomville.core import approvals, messages
from tomville.core.questions import question_lines


def markdown(text, *, bold_lines=()):
    """Small safe Markdown subset for assistant text, emitting allowed HTML."""
    pattern = re.compile(r'```([^\n`]*)\n(.*?)```|`([^`\n]+)`|\*\*(.+?)\*\*|(?<!\*)\*([^*\n]+)\*|_([^_\n]+)_', re.S)
    def plain(value, offset):
        first = text.count('\n', 0, offset)
        return '\n'.join('<b>' + escape(part) + '</b>' if part and first + i in bold_lines else escape(part)
                         for i, part in enumerate(value.split('\n')))

    result, end = [], 0
    for match in pattern.finditer(text):
        result.append(plain(text[end:match.start()], end))
        language, block, code, bold, italic, under = match.groups()
        if block is not None:
            language = language.strip()
            attr = f' class="language-{language}"' if re.fullmatch(r'[a-zA-Z0-9_+-]+', language) else ''
            result.append(f'<pre><code{attr}>{escape(block)}</code></pre>')
        elif code is not None:
            result.append('<code>' + escape(code) + '</code>')
        else:
            tag, value = ('b', bold) if bold is not None else ('i', italic if italic is not None else under)
            inner = escape(value) if bold is not None else plain(value, match.start(5 if italic is not None else 6))
            result.append(f'<{tag}>' + inner + f'</{tag}>')
        end = match.end()
    return ''.join(result) + plain(text[end:], end)


def details(data):
    payload = data['payload']
    inputs = payload.get('tool_input', {})
    text = '<b>' + escape(payload.get('tool_name', 'Unknown tool')) + '</b>\n'
    text += 'cwd: <code>' + escape(payload['cwd']) + '</code>\n'
    text += '<pre><code>' + escape(json.dumps(inputs, ensure_ascii=False, indent=2)) + '</code></pre>'
    if payload.get('tool_name') in ('Edit', 'Write'):
        edits = inputs.get('edits', [inputs])
        for edit in edits:
            old, new = edit.get('old_string', ''), edit.get('new_string', edit.get('content', ''))
            file = inputs.get('file_path', 'file')
            diff = ''.join(difflib.unified_diff([line + '\n' for line in old.splitlines()], [line + '\n' for line in new.splitlines()],
                                               fromfile=file, tofile=file))
            text += ('\nProposed edit fragment' if payload['tool_name'] == 'Edit' else '\nProposed content; old content not supplied by the hook')
            text += '\n<pre><code class="language-diff">' + escape(diff) + '</code></pre>'
    return text


def buttons(data, rows):
    return {'inline_keyboard': [[{'text': text, 'callback_data': data['id'] + ':' + choice} for text, choice in row] for row in rows]}


def issue(bridge, data):
    kind = data['kind']
    if kind == 'stop':
        text = data['payload']['last_assistant_message']
        return [('💬 ' + markdown(text, bold_lines=question_lines(text)), None)]
    if kind == 'permission-request':
        return [('🔐 ' + details(data), buttons(data, [[('✅ Allow once', 'allow'), ('❌ Deny', 'deny')]]))]
    if kind == 'permission-denied':
        return [('⛔ ' + details(data) + '\nReason: ' + escape(data['payload'].get('reason', 'Unknown reason')),
                 buttons(data, [[('🔁 Approve, retry', 'retry'), ('Leave it', 'leave')]]))]
    result = []
    for index, question in enumerate(data['payload']['tool_input']['questions']):
        text = '❓ <b>' + escape(question['question']) + '</b>'
        rows = []
        for option_index, option in enumerate(question['options']):
            text += '\n<b>' + escape(option['label']) + '</b>: ' + escape(option['description'])
            rows.append([(option['label'][:60], f'q{index}.{option_index}')])
        rows.append([('Other: reply to this message', f'other{index}')])
        if question.get('multiSelect'):
            text += '\nSelect one or more options, then Submit answers.'
        rows.append([('Submit answers', 'done'), ('Cancel', 'cancel')])
        result.append((text, buttons(data, rows)))
    return result


def update_messages(bridge, data, text):
    for record in data['messages']:
        bridge.bot.call('editMessageText', chat_id=bridge.config['chat_id'], message_id=record['id'],
                        text=text, reply_markup={'inline_keyboard': []})


def scan(bridge):
    if bridge.settings.team != 'lead' or bridge.config.get('paused'):
        return
    for file in sorted((bridge.project / approvals.DIRECTORY).glob('*.json')):
        try:
            scan_request(bridge, file)
        except TimeoutError as exc:
            bridge.error('approval scan skipped', exc)


def scan_request(bridge, file):
    close = None
    with approvals.locked(bridge.project, file.stem, timeout=0) as data:
        if not data:
            return
        if data['status'] == 'pending' and not approvals.active(bridge.project, bridge.settings, data, bridge.approval_clock()):
            approvals.expire(bridge.project, data)
        if data['status'] != 'pending':
            if data.get('issued') and not data.get('closed_notice'):
                data['closed_notice'] = True
                close = 'Expired; no answer accepted' if data['status'] == 'expired' else 'Answered'
            else:
                return
        elif data.get('issued'):
            return
        else:
            data['issued'] = True  # Claim before I/O; a crash never reissues buttons.
    if close:
        update_messages(bridge, data, close)
        return
    for index, (text, markup) in enumerate(issue(bridge, data)):
        result = bridge.say(text, **({'reply_markup': markup} if markup else {}))
        with approvals.locked(bridge.project, file.stem) as current:
            current['messages'].append({'id': result['message_id'], 'question': index})
            if not approvals.active(bridge.project, bridge.settings, current, bridge.approval_clock()):
                current['closed_notice'] = False
                return
    if data['kind'] == 'stop':
        with approvals.locked(bridge.project, file.stem) as current:
            if current['status'] == 'pending':
                current.update(status='notified', closed_notice=True)
        approvals.log(bridge.project, data, data['payload']['last_assistant_message'], sender=data['lead'])


def permitted(bridge, data, message_id):
    return (data and not bridge.config.get('paused') and bridge.settings.team == 'lead'
            and approvals.active(bridge.project, bridge.settings, data, bridge.approval_clock())
            and message_id in [m['id'] for m in data['messages']])


def finish(bridge, data, answer):
    data.update(status='answered', answer=answer)
    approvals.log(bridge.project, data, json.dumps(answer, ensure_ascii=False))
    # Persist consumption before any prompt or Telegram I/O.
    approvals.write(approvals.path(bridge.project, data['id']), data)


def retry(bridge, data):
    payload = data['payload']
    text = 'Tom approved: ' + payload['tool_name'] + ' ' + json.dumps(payload['tool_input'], ensure_ascii=False) + ', retry it'
    pane = bridge.target_pane(data['lead'])
    messages.send(bridge.project, data['lead'], text, sender='tom', via='telegram-approval', target=pane,
                  prompt_prefix=messages.TELEGRAM_PREFIX, process_timeout=10)


def callback(bridge, callback):
    token, _, choice = callback.get('data', '').partition(':')
    try:
        approvals.path(bridge.project, token)
    except ValueError:
        return
    answer, retry_data, closed = 'expired', None, None
    with approvals.locked(bridge.project, token) as data:
        if permitted(bridge, data, callback.get('message', {}).get('message_id')):
            kind = data['kind']
            if kind == 'permission-request' and choice in ('allow', 'deny'):
                finish(bridge, data, dict(behavior=choice, **({'reason': 'Tom denied this request'} if choice == 'deny' else {})))
                answer = 'Allowed once' if choice == 'allow' else 'Denied'
            elif kind == 'permission-denied' and choice in ('retry', 'leave'):
                finish(bridge, data, {'behavior': choice})
                answer = 'Left blocked'
                if choice == 'retry':
                    retry_data = data
                    answer = 'Approval sent; the safety check decides on retry'
            elif kind == 'ask-user-question':
                answer = question_choice(bridge, data, choice)
            if data['status'] == 'answered':
                data['closed_notice'] = True
                closed = data
    # Decisions are durable and unlocked before any slow side effects.
    if retry_data:
        bridge.defer(retry, bridge, retry_data)
    if closed:
        bridge.defer(update_messages, bridge, closed, answer)
    elif answer != 'expired':
        bridge.defer(bridge.say, escape(answer))


def question_choice(bridge, data, choice):
    questions = data['payload']['tool_input']['questions']
    if choice == 'cancel':
        finish(bridge, data, {'behavior': 'deny', 'reason': 'Tom cancelled the question'})
        return 'Cancelled'
    if choice == 'done':
        if not all(data['selections'].get(str(i)) for i in range(len(questions))):
            return 'Answer every question before submitting'
        answers = {q['question']: ', '.join(data['selections'][str(i)]) for i, q in enumerate(questions)}
        finish(bridge, data, {'behavior': 'allow', 'answers': answers})
        return 'Answers submitted'
    other = re.fullmatch(r'other(\d+)', choice)
    option = re.fullmatch(r'q(\d+)\.(\d+)', choice)
    if other and int(other[1]) < len(questions):
        return 'Reply to the question message with your answer'
    if option and int(option[1]) < len(questions):
        index, selected = int(option[1]), int(option[2])
        question = questions[index]
        if selected < len(question['options']):
            label = question['options'][selected]['label']
            values = data['selections'].setdefault(str(index), [])
            if question.get('multiSelect'):
                values.remove(label) if label in values else values.append(label)
            else:
                data['selections'][str(index)] = [label]
            return 'Selected: ' + ', '.join(data['selections'][str(index)]) + '; Submit answers when ready'
    return 'Unknown option'


def reply(bridge, message):
    """Late hook replies are consumed, never forwarded as fresh prompts."""
    message_id = message.get('reply_to_message', {}).get('message_id')
    if message_id is None:
        return False
    for file in (bridge.project / approvals.DIRECTORY).glob('*.json'):
        closed, notice = None, None
        with approvals.locked(bridge.project, file.stem) as data:
            record = next((m for m in data['messages'] if m['id'] == message_id), None) if data else None
            if not record:
                continue
            if data['kind'] == 'stop':
                return False
            if not permitted(bridge, data, message_id):
                notice = 'Expired or already answered; nothing sent'
            elif data['kind'] == 'permission-request':
                finish(bridge, data, {'behavior': 'deny', 'reason': message['text']})
                data['closed_notice'] = True
                closed = data
            elif data['kind'] == 'ask-user-question':
                data['selections'][str(record['question'])] = [message['text']]
                notice = 'Answer recorded; tap Submit answers when ready'
            else:
                notice = 'Use Approve, retry or Leave it'
        if closed:
            bridge.defer(update_messages, bridge, closed, 'Denied with your reason')
        if notice:
            bridge.defer(bridge.say, notice)
        return True
    return False
