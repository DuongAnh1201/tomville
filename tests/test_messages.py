import asyncio
import io
import json
import random
import subprocess
from datetime import datetime, timezone

import pytest

from tomville.cli import main
from tomville.core import messages
from tomville.core.events import EventReader
from tomville.core.messages import LogFollower, append, claude_hook, log_path, prompts_in, repo_root, send
from tomville.core.models import Agent, Message, MessageSent, Status
from tomville.core.settings import ReaderSettings
from tomville.core.world import World


def msg(sender, to, text, via='send'):
    return Message(datetime(2026, 10, 17, 10, 42, tzinfo=timezone.utc), sender, to, text, via)


def git_repo(path):
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(path)], check=True)
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init'], check=True)
    return path


def test_log_round_trip_and_follower_reads_only_new_lines(tmp_path):
    follower = LogFollower(log_path(tmp_path))
    append(tmp_path, msg('claude', 'codex1', 'Fix the login test'))
    follower.skip_existing()
    assert follower.read_new() == []
    append(tmp_path, msg(None, 'claude2', 'Take #4', 'hook'))
    [m] = follower.read_new()
    assert (m.sender, m.to, m.text, m.via) == (None, 'claude2', 'Take #4', 'hook')
    line = json.loads(log_path(tmp_path).read_text().splitlines()[0])
    assert line == {'time': '2026-10-17T10:42:00+00:00', 'from': 'claude', 'to': 'codex1', 'text': 'Fix the login test', 'via': 'send'}


def test_follower_waits_for_a_half_written_line(tmp_path):
    path = log_path(tmp_path)
    path.parent.mkdir(parents=True)
    follower = LogFollower(path)
    path.write_text('{"time": "2026-10-17T10:42:00+00:00", "from": "claude", "to": "co')
    assert follower.read_new() == []
    with path.open('a') as f:
        f.write('dex1", "text": "hi", "via": "send"}\n')
    assert [m.to for m in follower.read_new()] == ['codex1']


@pytest.mark.parametrize('command, found', [
    ('herdr agent prompt codex1 "Fix the login test" --wait --timeout 600000', [('codex1', 'Fix the login test')]),
    ("cd x && herdr agent prompt claude2 'Take #4'", [('claude2', 'Take #4')]),
    ('herdr --machine tablet agent prompt reviewer "Check it"', [('reviewer', 'Check it')]),
    ('herdr agent list; herdr agent read codex1', []),
    ('echo "herdr agent prompt fake text"', []),
])
def test_prompts_in_shell_commands(command, found):
    assert prompts_in(command) == found


def test_claude_hook_logs_into_the_main_repo_from_a_worktree(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / 'repo')
    worktree = tmp_path / 'wt'
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-q', '-b', 'w', str(worktree)], check=True)
    assert repo_root(worktree) == repo
    monkeypatch.setattr(messages, 'sender_name', lambda: 'claude')
    payload = {'tool_name': 'Bash', 'cwd': str(worktree), 'tool_input': {'command': 'herdr agent prompt codex1 "Take #2"'}}
    assert claude_hook(io.StringIO(json.dumps(payload))) == 0
    [line] = log_path(repo).read_text().splitlines()
    assert json.loads(line) | {'time': None} == {'time': None, 'from': 'claude', 'to': 'codex1', 'text': 'Take #2', 'via': 'hook'}
    assert not log_path(worktree).exists()


def test_claude_hook_never_fails(tmp_path):
    assert claude_hook(io.StringIO('not json')) == 0
    other_tool = {'tool_name': 'Edit', 'cwd': str(tmp_path), 'tool_input': {'command': 'herdr agent prompt a b'}}
    assert claude_hook(io.StringIO(json.dumps(other_tool))) == 0
    assert not log_path(tmp_path).exists()


def test_send_logs_only_after_herdr_accepts(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if args[3] == 'ghost' else 0, '{"result":{}}', 'no such agent')

    monkeypatch.setattr(messages.subprocess, 'run', fake_run)
    monkeypatch.setattr(messages, 'sender_name', lambda: 'claude')
    send(tmp_path, 'codex1', 'Take #6', wait=True, timeout=5000)
    assert calls[-1] == ['herdr', 'agent', 'prompt', 'codex1', 'Take #6', '--wait', '--timeout', '5000']
    with pytest.raises(OSError, match='no such agent'):
        send(tmp_path, 'ghost', 'hello')
    assert [json.loads(l)['to'] for l in log_path(tmp_path).read_text().splitlines()] == ['codex1']


def test_tmv_send_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(messages.subprocess, 'run', lambda args, **kw: subprocess.CompletedProcess(args, 0, '', ''))
    monkeypatch.setattr(messages, 'sender_name', lambda: None)
    monkeypatch.setattr(messages, 'repo_root', lambda path: tmp_path)
    assert main(['send', 'codex1', 'Fix', 'the', 'test', '-C', str(tmp_path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['sent'] == 'codex1'
    assert json.loads(log_path(tmp_path).read_text())['text'] == 'Fix the test'


def test_reader_emits_messages_sent_while_open(tmp_path):
    append(tmp_path, msg('claude', 'codex1', 'old'))
    reader = EventReader(tmp_path, ReaderSettings(source='tasks-md', poll_seconds=0.01))
    got = []

    async def run():
        task = asyncio.create_task(reader._messages(got.append))
        await asyncio.sleep(0.05)
        append(tmp_path, msg('claude', 'claude2', 'new'))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    assert [e.message.text for e in got] == ['new']


def world_with_team():
    world = World(lead='claude', rng=random.Random(1))
    world.resize(128, 30)
    world.load([Agent(n, 'codex', Status.IDLE, f'p-{n}') for n in ('claude', 'codex1', 'claude2')], [])
    return world


def test_envelope_walks_from_sender_to_the_receivers_desk_and_back():
    world = world_with_team()
    seat = world.office.seats['claude']
    world.apply(MessageSent(msg('claude', 'codex1', 'Fix the login test')))
    desk = world.office.desks['codex1']
    seen = set()
    for _ in range(300):
        world.tick(0.1)
        lead = world.appearance(world.pets['claude'])
        if lead.bubble:
            seen.add((lead.bubble, (lead.x, lead.y)))
    assert ('✉ Fix the login test', (desk.cx, desk.y - 1)) in seen
    assert world.pets['claude'].cell == seat


def test_worker_to_boss_envelope_goes_to_the_front_of_the_boss_desk():
    world = world_with_team()
    boss = world.office.desks['claude']
    assert world._front_of_desk('claude') == (boss.cx, boss.y + boss.h)


def test_unknown_sender_shows_a_question_mark_on_the_receiver():
    world = world_with_team()
    world.apply(MessageSent(msg(None, 'claude2', 'Take #4')))
    assert world.appearance(world.pets['claude2']).bubble == '? ✉ Take #4'
    assert not world.pets['claude'].script
