"""Optional per-ville Telegram bridge. Bot API I/O is injectable for offline tests.

No credentials live in the project. Unknown approval screens never get keys.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import fcntl
import getpass
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request

import tomli_w

from tomville.core import messages, team
from tomville.core.models import Message
from tomville.core.settings import load_settings, read_toml
from tomville.core.ville import has_ville, update_ville

COMMANDS = {'status': 'Team status', 'board': 'Task board', 'pending': 'Waiting agents',
            'pause': 'Pause forwarding and pings', 'resume': 'Resume', 'help': 'Help', 'start': 'Help'}


def config_path(ville_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', ville_id or ''):
        raise ValueError('Telegram is not paired; run tmv telegram setup')
    return Path.home() / '.config/tomville/telegram' / (ville_id + '.toml')


def save_config(ville_id, data):
    path = config_path(ville_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.telegram-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(tomli_w.dumps(data))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_config(settings):
    data = read_toml(config_path(settings.telegram['id']))
    if not data.get('token') or not isinstance(data.get('chat_id'), int) or data['chat_id'] <= 0:
        raise ValueError('Telegram token or pairing missing; run tmv telegram setup')
    return data


def change_config(settings, **updates):
    # Reload before writing so offset updates do not overwrite CLI pause/resume.
    data = load_config(settings)
    data.update(updates)
    save_config(settings.telegram['id'], data)
    return data


@contextmanager
def run_lock(ville_id):
    path = config_path(ville_id).with_suffix('.lock')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Telegram is already running for this ville') from None
        yield
    finally:
        os.close(fd)


def short_reason(error, token=''):
    """Keep useful diagnostics without credential URLs or terminal control codes."""
    text = str(error)
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get('error', payload)
        if isinstance(detail, dict) and isinstance(detail.get('message'), str):
            text = detail['message']
    if isinstance(token, str) and token:
        text = text.replace(token, '[redacted]')
    text = re.sub(r'https?://api\.telegram\.org/bot[^/\s]+', 'https://api.telegram.org/bot[redacted]', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return re.sub(r'\s+', ' ', re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text)).strip()[:240] or type(error).__name__


class TelegramHTTPSHandler(urllib.request.HTTPSHandler):
    """Bound IPv6 connect attempts; remember a failed IPv6 route per bot.

    Only TCP connection selection changes. urllib/http.client still perform the
    HTTPS handshake with the original hostname, certificate checks and proxy setup.
    No global resolver/socket patch and no replay of an HTTP request on failure.
    """
    def __init__(self):
        super().__init__()
        self.prefer_ipv4 = False

    def connect(self, address, timeout=40, source_address=None):
        addresses = socket.getaddrinfo(*address, type=socket.SOCK_STREAM)
        if self.prefer_ipv4:
            addresses.sort(key=lambda a: a[0] != socket.AF_INET)
        last_error = OSError('No addresses found for Telegram')
        while addresses:
            family, kind, protocol, _, endpoint = addresses.pop(0)
            sock = None
            try:
                sock = socket.socket(family, kind, protocol)
                sock.settimeout(min(timeout, 1) if family == socket.AF_INET6 else timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(endpoint)
                sock.settimeout(timeout)  # long-poll reads retain their normal deadline
                return sock
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
                if family == socket.AF_INET6:
                    self.prefer_ipv4 = True
                    addresses.sort(key=lambda a: a[0] != socket.AF_INET)
        raise last_error

    def https_open(self, request):
        def connection(host, **kwargs):
            conn = http.client.HTTPSConnection(host, **kwargs)
            conn._create_connection = self.connect
            return conn
        return self.do_open(connection, request, context=self._context)


class Bot:
    def __init__(self, token, opener=None):
        if not token or ':' not in token:
            raise ValueError('Invalid bot token; use @BotFather')
        self.token = token
        self.opener = opener if opener is not None else urllib.request.build_opener(TelegramHTTPSHandler()).open

    def call(self, method, **params):
        request = urllib.request.Request('https://api.telegram.org/bot' + self.token + '/' + method,
                                         data=json.dumps(params).encode(), headers={'Content-Type': 'application/json'})
        try:
            with self.opener(request, timeout=40) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.load(exc)
            except (OSError, ValueError):
                raise OSError(f'Telegram {method}: HTTP {exc.code}') from None
            finally:
                exc.close()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise OSError(f'Telegram {method}: {short_reason(exc, self.token)}') from None
        if not result.get('ok'):
            raise OSError(f'Telegram {method} refused (code {result.get("error_code", "unknown")}): ' + short_reason(result.get('description', 'request refused'), self.token))
        return result['result']

    def send(self, chat_id, text, **params):
        result = None
        parts = chunks(text)
        for index, part in enumerate(parts):
            options = params if index == len(parts) - 1 else {k: v for k, v in params.items() if k != 'reply_markup'}
            result = self.call('sendMessage', chat_id=chat_id, text=part, parse_mode='HTML', **options)
        return result


class _Chunks(HTMLParser):
    """Balance supported HTML tags and entities at each message boundary."""
    def __init__(self, size):
        super().__init__(convert_charrefs=False)
        self.size, self.parts, self.current, self.tags = size, [], '', []

    def closing(self):
        return ''.join(f'</{t}>' for t in reversed(self.tags))

    def flush(self):
        self.parts.append(self.current + self.closing())
        self.current = ''.join(f'<{t}>' for t in self.tags)

    def add(self, text):
        if len(self.current) + len(text) + len(self.closing()) > self.size:
            self.flush()
        self.current += text

    def handle_starttag(self, tag, attrs):
        if tag not in ('b', 'i') or attrs:
            raise ValueError('Telegram text supports only <b> and <i>')
        if len(self.current) + len(tag) * 2 + 5 + len(self.closing()) > self.size:
            self.flush()
        self.current += f'<{tag}>'
        self.tags.append(tag)

    def handle_endtag(self, tag):
        if not self.tags or self.tags[-1] != tag:
            raise ValueError('Unbalanced Telegram HTML')
        self.current += f'</{self.tags.pop()}>'

    def handle_data(self, data):
        for char in data:
            self.add(escape(char, quote=False))

    def handle_entityref(self, name):
        if name not in ('amp', 'lt', 'gt', 'quot'):
            raise ValueError('Unsupported HTML entity')
        self.add(f'&{name};')

    def handle_charref(self, name):
        self.add(f'&#{name};')


def chunks(text, size=4096):
    parser = _Chunks(size)
    parser.feed(text)
    parser.close()
    if parser.tags:
        raise ValueError('Unbalanced Telegram HTML')
    if parser.current:
        parser.parts.append(parser.current)
    return parser.parts


def trusted(message, chat_id=None):
    chat = message.get('chat', {})
    return (chat.get('type') == 'private' and chat.get('id', 0) > 0
            and (chat_id is None or chat['id'] == chat_id)
            and message.get('from', {}).get('id') == chat['id']
            and not any(k in message for k in ('forward_origin', 'forward_from', 'forward_from_chat', 'forward_date', 'is_automatic_forward')))


def setup(project, settings, ask, *, hidden=getpass.getpass, show=print, bot_factory=Bot, clock=time.monotonic):
    if not has_ville(project):
        raise ValueError('Run tmv new first')
    if settings.telegram['enabled']:
        raise ValueError('Telegram already enabled; turn it off before pairing again')
    show(f'In @BotFather use /newbot. Suggested name: {settings.name or project.name} ville; username: tomville_{re.sub("[^a-z0-9_]", "_", project.name.lower())}_bot')
    bot = bot_factory(hidden('Bot token (hidden): '))
    me = bot.call('getMe')
    show('@' + me['username'])
    bot.call('deleteWebhook', drop_pending_updates=True)
    code = f'{secrets.randbelow(1000000):06d}'
    show(f'Send this code to @{me["username"]} within five minutes: {code}')
    deadline, offset, chat_id = clock() + 300, 0, None
    while clock() < deadline and chat_id is None:
        for update in bot.call('getUpdates', offset=offset, timeout=20, allowed_updates=['message']):
            offset = update['update_id'] + 1
            message = update.get('message', {})
            if trusted(message) and message.get('text') == code:
                chat_id = message['chat']['id']
                break
    if chat_id is None:
        raise ValueError('Pairing expired; run tmv telegram setup again')
    choices = set(settings.agents) | {'lead'}
    defaults = ','.join(n for n in ('secretary', 'lead') if n in choices)
    while True:
        allowed = re.split(r'[,\s]+', ask('Who should message you here? Choices: ' + ', '.join(sorted(choices)), defaults).strip())
        allowed = [n for n in allowed if n]
        if set(allowed) <= choices:
            break
        show('Choose configured agents or lead')
    approvals = ask('Approve permission questions from this chat? (yes/no)', 'no').lower() in ('y', 'yes')
    ville_id = settings.telegram['id'] or secrets.token_hex(16)
    save_config(ville_id, dict(token=bot.token, chat_id=chat_id, offset=offset, paused=False))
    update_ville(project, {'telegram': dict(enabled=True, bot='@' + me['username'], id=ville_id, approvals=approvals, **{'from': allowed})})
    bot.send(chat_id, 'Paired ✅')


def agent_commands(settings):
    result, used = {}, set(COMMANDS)
    for agent in settings.agents:
        name = re.sub('[^a-z0-9_]', '_', agent.lower())[:32] or 'agent'
        if name in used:
            name = name[:26] + '_agent'
        stem, index = name, 2
        while name in used:
            suffix = '_' + str(index)
            name = stem[:32-len(suffix)] + suffix
            index += 1
        used.add(name)
        result[name] = agent
    return result


@dataclass(frozen=True)
class Question:
    text: str
    yes: str
    no: str


def parse_question(kind, screen):
    """Conservative full permission panels; no generic yes/no guessing.

    Retain the full panel, including cwd and options, for both display and equality.
    Unfamiliar panels fall back to an in-pane answer.
    """
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', screen).strip()
    if kind == 'claude' and ('Bash command' in text or 'Do you want to proceed?' in text):
        if re.search(r'1\. Yes\s*\n', text) and re.search(r'3\. No(?:\s|$)', text) and 'Do you want to proceed?' in text:
            return Question(text, '1', '3')
    if kind == 'codex' and 'Would you like to run the following command?' in text:
        if '1. Yes, proceed (y)' in text and '3. No, and tell Codex what to do differently (esc)' in text:
            return Question(text, 'y', 'esc')
    return None


def read_question(project, agent):
    raw = team.run_command(['herdr', 'pane', 'read', agent['pane_id'], '--source', 'visible'], project)
    # pane read is text, unlike the machine envelope returned by other commands.
    return parse_question(agent.get('agent'), raw)


class Bridge:
    def __init__(self, project, settings, bot, config, *, clock=time.monotonic):
        self.project, self.settings, self.bot, self.config = project, settings, bot, config
        self.clock, self.pending = clock, {}
        self.routes = agent_commands(settings)

    def log(self, target, text, via='telegram', sender='tom'):
        messages.append(self.project, Message(datetime.now(timezone.utc), sender, target, text, via))

    def error(self, context, error, target='tomville'):
        reason = short_reason(error, self.bot.token)
        text = short_reason(context + ': ' + reason, self.bot.token)
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        print(f'{stamp} Telegram: {text}', file=sys.stderr, flush=True)
        self.log(target, text, via='telegram-error', sender='tomville')
        return text

    def target_pane(self, target):
        agents = team.herdr(self.project, 'agent', 'list')['agents']
        state = team.load_state(self.project)
        lead = target == self.settings.lead or target == state.get('lead_spec')
        record = ({'pane': state.get('lead_pane'), 'terminal': state.get('lead_terminal'), 'kind': state.get('lead_kind')}
                  if lead else state.get('agents', {}).get(target, {}))
        if record.get('pane'):
            live = next((a for a in agents if a['pane_id'] == record['pane']), None)
            if live:
                if record.get('terminal') and live.get('terminal_id') != record['terminal']:
                    raise OSError('recorded pane terminal changed; run tmv up')
                if live.get('name') and live['name'] != (self.settings.lead if lead else target):
                    raise OSError('recorded pane belongs to another agent; run tmv up')
                kind = live.get('agent') or (live.get('agent_session') or {}).get('agent')
                if not kind or record.get('kind') and kind != record['kind']:
                    raise OSError('recorded pane agent changed; run tmv up')
                return live['pane_id']
        # Names must actually be herdr names: a CLI kind is not a target name.
        named = [a for a in agents if a.get('name') == (self.settings.lead if lead else target)]
        if len(named) != 1:
            raise OSError('agent not found' if not named else 'agent name is ambiguous')
        return named[0]['pane_id']

    def say(self, text, **params):
        return self.bot.send(self.config['chat_id'], text, **params)

    def snapshot(self):
        if hasattr(self, 'live_reader'):
            return {'agents': [asdict(a) for a in self.live_reader.agents.values() if a.name in self.settings.agents or a.name == self.settings.lead],
                    'cards': [asdict(c) for c in self.live_reader.cards.values()]}
        from tomville.core.events import EventReader
        from tomville.core.status import snapshot
        if not hasattr(self, 'reader'):
            self.reader = EventReader(self.project, self.settings)
        return snapshot(self.reader, self.project, self.settings)

    def handle(self, update):
        if 'callback_query' in update:
            return self.callback(update['callback_query'])
        message = update.get('message', {})
        if not trusted(message, self.config['chat_id']):
            self.log('tomville', 'Ignored unpaired, non-private or forwarded Telegram update')
            return
        text = message.get('text', '').strip()
        if not text:
            return
        command, _, body = text.partition(' ')
        command = command.removeprefix('/').split('@')[0].lower() if text.startswith('/') else ''
        if command in ('pause', 'resume'):
            self.config = change_config(self.settings, paused=command == 'pause')
            return self.say('Paused' if command == 'pause' else 'Resumed')
        if command in ('help', 'start'):
            return self.say('<b>Tomville</b>\nPlain text goes to the lead.\n' + '\n'.join('/' + n for n in [*COMMANDS, *self.routes]))
        if command in ('status', 'board', 'pending'):
            data = self.snapshot()
            if command == 'board':
                text = '\n'.join(f'{c["id"]} {c["column"]}: {c["title"]}' for c in data['cards'])
            else:
                text = '\n'.join(f'{a["name"]}: {a["status"]}' for a in data['agents'] if command != 'pending' or a['status'] == 'blocked')
            return self.say('<b>' + command.title() + '</b>\n' + escape(text or 'None'))
        if self.config.get('paused'):
            return self.say('Paused; use /resume')
        if command:
            target = self.routes.get(command)
            if not target:
                return self.say('Unknown command; use /help')
            text = body.strip()
        elif self.settings.team == 'lead' and self.settings.lead:
            target = self.settings.lead
        else:
            return self.say('plain text needs a lead; use /&lt;agent&gt;')
        if not text:
            return self.say('Include a message after the command')
        try:
            pane = self.target_pane(target)
            messages.send(self.project, target, text, sender='tom', via='telegram', target=pane)
        except team.ERRORS as exc:
            reason = self.error("couldn't reach " + target, exc, target)
            try:
                self.say(escape(reason))
            except OSError as reply_error:
                self.error('failure reply', reply_error, target)
            return
        self.say('Sent to <b>' + escape(target) + '</b>')

    def blocked(self, agent):
        name = agent['name']
        live = next((a for a in team.herdr(self.project, 'agent', 'list')['agents'] if team.agent_name(a) == name and a['pane_id'] == agent['pane_id'] and a.get('agent_status') == 'blocked'), None) if self.settings.telegram['approvals'] else None
        question = read_question(self.project, live) if live and live.get('terminal_id') and self.settings.telegram['approvals'] else None
        if question is None:
            return self.say('🤖 tomville: ' + escape(name) + ' is waiting; answer in its pane')
        token = secrets.token_hex(12)
        result = self.say('🤖 tomville: <b>' + escape(name) + ' asks:</b>\n' + escape(question.text), reply_markup={'inline_keyboard': [[
            {'text': '✅ Approve', 'callback_data': token + ':yes'}, {'text': '❌ Decline', 'callback_data': token + ':no'}]]})
        self.pending[token] = dict(agent=live, question=question, time=self.clock(), message_id=result['message_id'])

    def callback(self, callback):
        message = callback.get('message', {})
        # The callback's sender is the person; the attached message is from the bot.
        candidate = dict(message, **{'from': callback.get('from', {})})
        if not trusted(candidate, self.config['chat_id']):
            self.log('tomville', 'Ignored Telegram callback from another chat')
            return
        token, _, choice = callback.get('data', '').partition(':')
        pending = self.pending.get(token)
        answer = 'expired'
        if (pending and self.clock() - pending['time'] < 600 and choice in ('yes', 'no')
                and not self.config.get('paused') and self.settings.telegram['approvals']):
            answer = 'changed; nothing sent'
            original = pending['agent']
            live = next((a for a in team.herdr(self.project, 'agent', 'list')['agents']
                         if a['pane_id'] == original['pane_id'] and team.agent_name(a) == team.agent_name(original)
                         and a.get('terminal_id') == original.get('terminal_id') and a.get('agent') == original.get('agent')
                         and a.get('agent_status') == 'blocked'), None)
            if live and message.get('message_id') == pending['message_id'] and read_question(self.project, live) == pending['question']:
                # Consume before delivering a key: a duplicate tap must never act twice.
                self.pending.pop(token, None)
                question = pending['question']
                team.herdr(self.project, 'agent', 'send-keys', original['pane_id'], question.yes if choice == 'yes' else question.no)
                answer = '✅ approved by Tom' if choice == 'yes' else '❌ declined'
                self.log(team.agent_name(original), answer + '\n' + question.text, 'telegram-approval')
                self.bot.call('editMessageText', chat_id=self.config['chat_id'], message_id=pending['message_id'], text=answer, reply_markup={'inline_keyboard': []})
        self.pending.pop(token, None)
        self.bot.call('answerCallbackQuery', callback_query_id=callback['id'], text=answer)


def run(project, settings, *, bot_factory=Bot):
    if not settings.telegram['enabled']:
        raise ValueError('Telegram disabled; run tmv telegram setup')
    with run_lock(settings.telegram['id']):
        config = load_config(settings)
        bridge = Bridge(project, settings, bot_factory(config['token']), config)
        asyncio.run(_run(bridge))


async def _run(bridge):
    """Read live herdr events while Telegram long polls independently.

    Serialize notifications and updates so approval issuance and consumption cannot
    interleave. EventReader suppresses initial snapshots and owns its fallback.
    """
    from tomville.core.events import EventReader
    reader = EventReader(bridge.project, bridge.settings)
    reader.snapshot = lambda agents, cards: None
    bridge.live_reader = reader
    queue = asyncio.Queue()
    guard = asyncio.Lock()

    def refresh():
        current = load_settings(bridge.project)
        if not current.telegram['enabled']:
            return False
        bridge.settings = current
        bridge.config = load_config(current)
        return True

    async def poll():
        backoff = 2
        menu_set = False
        while True:
            async with guard:
                if not refresh():
                    return
                offset = bridge.config.get('offset', 0)
            try:
                if not menu_set:
                    await asyncio.to_thread(bridge.bot.call, 'setMyCommands', commands=[{'command': c, 'description': d} for c, d in COMMANDS.items()] +
                                            [{'command': c, 'description': 'Message ' + a} for c, a in bridge.routes.items()])
                    menu_set = True
                updates = await asyncio.to_thread(bridge.bot.call, 'getUpdates', offset=offset, timeout=20, allowed_updates=['message', 'callback_query'])
                for update in updates:
                    async with guard:
                        if not refresh():
                            return
                        # At-most-once delivery: never replay prompts or keys after a crash.
                        bridge.config = change_config(bridge.settings, offset=update['update_id'] + 1)
                        try:
                            await asyncio.to_thread(bridge.handle, update)
                        except (OSError, ValueError) as exc:
                            reason = bridge.error('update failed', exc)
                            await asyncio.to_thread(bridge.say, escape(reason))
                backoff = 2
            except OSError as exc:
                bridge.error('poll failed', exc)
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    async def notify():
        from tomville.core.models import AgentStatusChanged, CardChanged
        while True:
            event = await queue.get()
            async with guard:
                if not refresh():
                    return
                bridge.pending = {t: p for t, p in bridge.pending.items() if bridge.clock() - p['time'] < 600}
                if bridge.config.get('paused'):
                    continue
                try:
                    if isinstance(event, AgentStatusChanged) and event.new == 'blocked':
                        agent = next((a for a in reader.agents.values() if a.name == event.name and (a.name in bridge.settings.agents or a.name == bridge.settings.lead)), None)
                        if agent:
                            await asyncio.to_thread(bridge.blocked, asdict(agent))
                    elif isinstance(event, CardChanged) and event.old_column is not None and event.card.column in ('review', 'done') and event.old_column != event.card.column:
                        card = event.card
                        await asyncio.to_thread(bridge.say, '🤖 tomville: ' + escape(f'{card.id} → {card.column}: {card.title}'))
                except OSError as exc:
                    bridge.error('notification failed', exc)

    tasks = [asyncio.create_task(reader.run(queue.put_nowait)), asyncio.create_task(poll()), asyncio.create_task(notify())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                task.result()
            except team.ERRORS as exc:
                bridge.error('runner stopped', exc)
                raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def reply(project, settings, text, *, bot_factory=Bot):
    if not settings.telegram['enabled']:
        raise ValueError('Telegram disabled; run tmv telegram setup')
    sender = messages.sender_name()
    allowed = settings.telegram['from']
    if not sender or not (sender in allowed or sender == settings.lead and 'lead' in allowed):
        raise ValueError('This agent is not allowed to reply; change telegram.from in the ville')
    config = load_config(settings)
    pet = settings.pets.get(sender, {}).get('sprite', '')
    icon = {'cat': '🐱', 'dog': '🐶', 'sheep': '🐑'}.get(pet, '🐾')
    bot_factory(config['token']).send(config['chat_id'], escape(f'{icon} {sender}: ') + text)
    messages.append(project, Message(datetime.now(timezone.utc), sender, 'tom', text, 'telegram'))


def stop_tab(project):
    state = team.load_state(project)
    record = state.get('telegram')
    if record:
        panes = team.herdr(project, 'pane', 'list')['panes']
        live = next((p for p in panes if p['pane_id'] == record['pane']), None)
        if live:
            if not record.get('terminal') or live.get('terminal_id') != record['terminal'] or live.get('agent') or live.get('agent_session'):
                raise OSError('Telegram pane identity changed; kept for inspection')
            team.herdr(project, 'tab', 'close', record['tab'])
        state['telegram'] = None
        team.save_state(project, state)


def off(project, settings, confirm):
    if not confirm('Stop Telegram and delete this ville’s stored token?'):
        return False
    stop_tab(project)
    update_ville(project, {'telegram': dict(settings.telegram, enabled=False)})
    if settings.telegram['id']:
        config_path(settings.telegram['id']).unlink(missing_ok=True)
    return True


def health(settings):
    if not settings.telegram['enabled']:
        return True, 'not set up (optional)'
    try:
        config = load_config(settings)
    except (ValueError, OSError):
        return False, 'enabled but token or pairing missing'
    return True, settings.telegram['bot'] + (' (paused)' if config.get('paused') else ' (paired)')
