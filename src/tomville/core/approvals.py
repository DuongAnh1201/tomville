"""Claude hooks and the local, one-answer Telegram request queue (no bot token)."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time

from tomville.core import messages, team, leads
from tomville.core.models import Message
from tomville.core.questions import question_lines
from tomville.core.locks import file_lock
from tomville.core.settings import load_settings

DIRECTORY = Path('.tomville/approvals')
EVENTS = {'permission-request': 'PermissionRequest', 'permission-denied': 'PermissionDenied',
          'ask-user-question': 'PreToolUse', 'stop': 'Stop'}
TIMEOUT = 600


def path(project, request_id):
    if not re.fullmatch(r'[a-f0-9]{24}', request_id):
        raise ValueError('invalid approval ID')
    return project / DIRECTORY / (request_id + '.json')


def write(file, data):
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=file.parent, prefix='.request-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(name, file)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def locked(project, request_id, *, timeout=1):
    file = path(project, request_id)
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(file.with_suffix('.lock'), timeout=timeout):
        data = json.loads(file.read_text()) if file.exists() else None
        before = deepcopy(data)
        yield data
        if data is not None and data != before:
            write(file, data)


def log(project, data, text, *, sender='tom'):
    via = 'telegram-approval' if data['kind'] in ('permission-request', 'permission-denied') else 'telegram-question'
    messages.append(project, Message(datetime.now(timezone.utc), sender, data['lead'], text, via))


def eligible(project, settings, pane):
    state = team.load_state(project)
    return (settings.team == 'lead' and settings.telegram['enabled'] and bool(settings.lead)
            and bool(pane) and pane == state.get('lead_pane'))


def resolve_ville(cwd, pane):
    """Registry first; stale hints never fall through to another ville."""
    if not pane:
        return None

    def candidate(project):
        try:
            if (project / '.tomville/ville.toml').is_file():
                settings = load_settings(project)
                if eligible(project, settings, pane):
                    return project, settings
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    try:
        registered = leads.lookup(pane)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if registered is not None:
        return candidate(registered)
    if not cwd.is_absolute():
        return None
    cwd = cwd.resolve()
    for project in (cwd, *cwd.parents):
        found = candidate(project)
        if found is not None:
            return found
    return None


def active(project, settings, data, now):
    return (data['status'] == 'pending' and now < data['deadline']
            and data['lead'] == settings.lead and eligible(project, settings, data['pane'])
            and (data['kind'] not in ('permission-request', 'ask-user-question') or settings.telegram['approvals']))


def request_summary(kind, payload):
    def brief(text, limit=240):
        text = ' '.join(text.split())
        return text if len(text) <= limit else text[:limit - 1] + '…'

    if kind == 'stop':
        lines = payload.get('last_assistant_message', '').splitlines()
        return brief(lines[0] if lines else '', 480)
    inputs = payload.get('tool_input', {})
    if kind == 'ask-user-question':
        return brief('; '.join(q['question'] for q in inputs.get('questions', [])), 480)
    action = inputs.get('command') or inputs.get('file_path') or inputs.get('path') or inputs.get('url') or ''
    summary = brief(payload.get('tool_name', 'Unknown tool') + (': ' + action if action else ''))
    if kind == 'permission-denied':
        summary += ' — ' + brief(payload.get('reason', 'Unknown reason'))
    return summary


def submit(project, settings, pane, kind, payload, now):
    request_id = secrets.token_hex(12)
    data = dict(id=request_id, kind=kind, status='pending', created=now, deadline=now + TIMEOUT,
                lead=settings.lead, pane=pane, payload=payload, messages=[], selections={})
    write(path(project, request_id), data)
    log(project, data, 'Requested ' + kind + ': ' + request_summary(kind, payload), sender=settings.lead)
    return data


def denial(kind, reason):
    if kind == 'permission-request':
        return {'hookSpecificOutput': {'hookEventName': 'PermissionRequest', 'decision': {'behavior': 'deny', 'message': reason}}}
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}


def result(data):
    answer = data['answer']
    if data['kind'] == 'permission-request':
        decision = {'behavior': answer['behavior']}
        if answer['behavior'] == 'deny':
            decision['message'] = answer.get('reason', 'Tom denied this request')
        return {'hookSpecificOutput': {'hookEventName': 'PermissionRequest', 'decision': decision}}
    if answer['behavior'] != 'allow':
        return denial(data['kind'], answer.get('reason', 'Question cancelled'))
    inputs = dict(data['payload']['tool_input'], answers=answer['answers'])
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'allow', 'updatedInput': inputs}}


def expire(project, data, reason='no answer from Tom within 10 minutes'):
    data.update(status='expired', answer={'behavior': 'deny', 'reason': reason})
    log(project, data, reason, sender='tomville')


def hook(kind, stream=None, *, out=None, clock=time.time, sleep=time.sleep):
    """Exit silently outside the lead; after accepting a request, fail closed."""
    stream, out = stream or sys.stdin, out or sys.stdout
    accepted = False
    project = None
    data = None
    try:
        payload = json.load(stream)
        if not isinstance(payload, dict) or payload.get('hook_event_name') != EVENTS[kind]:
            return 0
        # Subagent hooks inherit the pane too; never answer those as the lead.
        if os.environ.get('HERDR_ENV') != '1' or payload.get('agent_id'):
            return 0
        pane = os.environ.get('HERDR_PANE_ID')
        found = resolve_ville(Path(payload['cwd']), pane)
        if found is None:
            return 0
        project, settings = found
        if kind == 'ask-user-question' and payload.get('tool_name') != 'AskUserQuestion':
            return 0
        if kind in ('permission-request', 'ask-user-question') and not settings.telegram['approvals']:
            return 0
        if kind == 'stop':
            text = payload.get('last_assistant_message', '')
            if not isinstance(text, str):
                return 0
            if not question_lines(text):
                return 0
        accepted = True
        if kind == 'ask-user-question':
            inputs = payload.get('tool_input')
            if not isinstance(inputs, dict):
                raise ValueError('invalid question input')
            questions = inputs.get('questions')
            if not isinstance(questions, list) or not questions:
                raise ValueError('missing questions')
            seen = set()
            for question in questions:
                if not isinstance(question, dict):
                    raise ValueError('invalid question')
                text = question['question']
                if not isinstance(text, str) or not text or text in seen:
                    raise ValueError('invalid question text')
                seen.add(text)
                options = question['options']
                if not isinstance(options, list) or not options or any(
                    not isinstance(o, dict) or not isinstance(o.get('label'), str) or not isinstance(o.get('description'), str) for o in options
                ):
                    raise ValueError('invalid question options')
        data = submit(project, settings, pane, kind, payload, clock())
        if kind in ('permission-denied', 'stop'):
            return 0  # Notices are picked up asynchronously; no auto-mode override.
        while True:
            with locked(project, data['id']) as current:
                if current['status'] == 'answered':
                    response = result(current)
                    break
                if current['status'] == 'expired':
                    response = denial(kind, current['answer']['reason'])
                    break
                settings = load_settings(project)
                if not active(project, settings, current, clock()):
                    reason = ('no answer from Tom within 10 minutes' if clock() >= current['deadline']
                              else 'Telegram request cancelled: lead or settings changed')
                    expire(project, current, reason)
                    response = denial(kind, reason)
                    break
            sleep(.25)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if not accepted or kind not in ('permission-request', 'ask-user-question'):
            return 0
        response = denial(kind, 'Telegram request failed; permission denied')
        print(f'tmv hook {kind}: {type(exc).__name__}', file=sys.stderr)
        if data is not None:
            try:
                with locked(project, data['id']) as current:
                    if current and current['status'] == 'pending':
                        expire(project, current, 'Telegram request failed; permission denied')
            except (OSError, ValueError, TypeError):
                pass
    print(json.dumps(response, ensure_ascii=False), file=out, flush=True)
    return 0
