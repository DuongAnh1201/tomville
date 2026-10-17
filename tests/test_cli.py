import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from tomville.cli import main
from tomville.core import doctor, status, tasks
from tomville.core.events import parse_agents
from tomville.core.settings import OfficeSettings, config_path, load_settings

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith('TOMVILLE_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path / 'user.toml'))


def test_settings_layers(tmp_path, monkeypatch):
    config_path().write_text('fps=5\nstyle="ascii"\n[board]\ncheck_seconds=30\n[pets.codex1]\nsprite="dog"\ncolor="#abcdef"\n')
    ville = tmp_path / '.tomville/ville.toml'
    ville.parent.mkdir()
    ville.write_text('fps=10\n[team]\nshape="pipeline"\nstages=["planner","coder"]\n')
    monkeypatch.setenv('TOMVILLE_FPS', '15')
    monkeypatch.setenv('TOMVILLE_STYLE', 'emoji')
    monkeypatch.setenv('TOMVILLE_STILL', 'false')
    settings = load_settings(tmp_path, fps=30, pets=['codex1=cat'])
    assert (settings.fps, settings.style, settings.team, settings.still) == (30, 'emoji', 'pipeline', False)
    assert settings.pets['codex1'] == {'sprite': 'cat', 'color': '#abcdef'}
    assert settings.check_seconds == 30
    assert settings.stages == ('planner', 'coder')
    monkeypatch.setenv('TOMVILLE_FPS', '999')
    assert load_settings(tmp_path, fps=10).fps == 10
    with pytest.raises(ValueError):
        load_settings(tmp_path)


def test_config_roundtrip_and_invalid_value(tmp_path, capsys):
    path = tmp_path / 'settings.toml'
    assert main(['config', 'set', 'fps', '15', '--config', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['value'] == 15
    assert main(['--config', str(path), 'config', 'set', 'theme', 'game-boy']) == 0
    capsys.readouterr()
    assert main(['config', 'get', 'theme', '--config', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out) == 'game-boy'
    before = path.read_text()
    assert main(['config', 'set', 'fps', '9', '--config', str(path), '--json']) == 2
    assert path.read_text() == before
    assert main(['config', 'set', 'unknown', '1', '--json']) == 2
    assert main(['config', 'get', 'missing', '--json']) == 2


def test_status_recordings_and_agent_filter(tmp_path, monkeypatch, capsys):
    agents = parse_agents(json.loads((FIXTURES / 'herdr_named_agents.json').read_text()))
    async def agent_list():
        return agents
    monkeypatch.setattr(status, 'agent_list', agent_list)
    path = tmp_path / 'TASKS.md'
    path.write_text('| id | title | status | agent |\n| T1 | Fix tests | doing | codex1 |\n| T2 | Review | review | claude |\n')
    assert main(['status', '--json', '-C', str(tmp_path), '--board', 'tasks-md', '--agent', 'codex1']) == 0
    data = json.loads(capsys.readouterr().out)
    assert [a['name'] for a in data['agents']] == ['codex1']
    assert data['agents'][0]['role'] == 'worker'
    assert [c['id'] for c in data['cards']] == ['T1']
    assert data['columns']['doing'] == 1
    path.unlink()
    assert main(['status', '--json', '-C', str(tmp_path), '--board', 'tasks-md']) == 1
    assert json.loads(capsys.readouterr().out)['offline_since']


def test_watch_json_lines_and_interrupt(monkeypatch, capsys):
    calls = 0
    def sleep(interval):
        nonlocal calls
        calls += 1
        assert interval == .01
        if calls == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr('tomville.cli.time.sleep', sleep)
    assert main(['status', '--demo', '--json', '--watch', '.01', '--agent', 'codex1']) == 0
    snapshots = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(snapshots) == 2
    assert all(s['agents'][0]['status'] == 'blocked' for s in snapshots)
    assert main(['status', '--demo', '--json', '--watch', 'nan']) == 2


def test_task_take_preserves_other_labels_and_is_repeatable(tmp_path, monkeypatch, capsys):
    commands = []
    def run(args, project):
        commands.append(args)
        if 'view' in args:
            return json.dumps({'state': 'OPEN', 'labels': [{'name': n} for n in ('status:todo', 'status:doing', 'agent:claude2', 'agent:codex1', 'bug')]})
        return 'updated'
    monkeypatch.setattr(tasks, 'run_command', run)
    assert main(['task', 'take', '6', '--agent', 'codex1', '--json']) == 0
    edit = commands[-1]
    assert '--remove-label' in edit and 'status:todo' in edit
    assert 'bug' not in edit
    removed = [edit[i+1] for i, value in enumerate(edit) if value == '--remove-label']
    assert removed == ['status:todo']
    added = [edit[i+1] for i, value in enumerate(edit) if value == '--add-label']
    assert added == ['status:doing', 'agent:codex1']
    assert json.loads(capsys.readouterr().out)['result'] == '#6 → doing'


def test_task_infers_agent_from_current_pane(tmp_path, monkeypatch):
    agents = parse_agents(json.loads((FIXTURES / 'herdr_named_agents.json').read_text()))
    codex = next(a for a in agents if a.name == 'codex1')
    monkeypatch.setenv('HERDR_PANE_ID', codex.pane_id)
    async def listing():
        return agents
    monkeypatch.setattr(tasks, 'agent_list', listing)
    assert tasks.Tasks(tmp_path, OfficeSettings()).current_agent() == 'codex1'
    monkeypatch.delenv('HERDR_PANE_ID')
    with pytest.raises(ValueError, match='--agent'):
        tasks.Tasks(tmp_path, OfficeSettings()).current_agent()


def test_task_new_move_done_reopen_and_failure(tmp_path, monkeypatch, capsys):
    commands = []
    state = 'OPEN'
    def run(args, project):
        commands.append(args)
        if 'view' in args:
            return json.dumps({'state': state, 'labels': [{'name': 'status:review'}]})
        return 'https://github.test/issues/99'
    monkeypatch.setattr(tasks, 'run_command', run)
    config_path().write_text('[board]\nrepo="owner/project"\n')
    assert main(['task', 'new', 'A title; literal $HOME', '--agent', 'codex1', '--body', 'one\ntwo', '--json']) == 0
    assert commands[-1][-2:] == ['--repo', 'owner/project']
    assert 'status:todo,agent:codex1' in commands[-1]
    assert 'one\ntwo' in commands[-1]
    assert main(['task', 'move', '99', 'done']) == 0
    assert 'close' in commands[-1]
    state = 'CLOSED'
    assert main(['task', 'move', '99', 'doing']) == 0
    assert 'reopen' in commands[-1]
    def fail(*args):
        raise OSError('offline')
    monkeypatch.setattr(tasks, 'run_command', fail)
    capsys.readouterr()
    assert main(['task', 'take', '99', '--agent', 'codex1', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'offline'
    assert main(['task', 'new', 'Demo', '--demo', '--json']) == 2


def test_doctor_required_errors_vs_warnings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HERDR_ENV', '1')
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: '/bin/herdr')
    async def listing():
        return []
    monkeypatch.setattr(doctor, 'agent_list', listing)
    def run(args, project):
        if args[:3] == ['gh', 'auth', 'status']:
            raise OSError('not logged in')
        return '[]'
    monkeypatch.setattr(doctor, 'run_command', run)
    monkeypatch.setattr('tomville.core.events.EventReader.update_board', lambda self: [])
    assert main(['doctor', '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['warnings'] == 2  # login and missing status labels
    monkeypatch.delenv('HERDR_ENV')
    assert main(['doctor', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['problems'] == 1


def test_office_options_and_no_color_reach_app(tmp_path, monkeypatch):
    from tomville.tui import app
    captured = {}
    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            captured['no_color'] = __import__('os').environ.get('NO_COLOR')
        def run(self):
            assert __import__('os').environ.get('NO_COLOR') == '1'
    monkeypatch.setattr(app, 'TomvilleApp', FakeApp)
    monkeypatch.delenv('NO_COLOR', raising=False)
    assert main(['--fps', '15', '--style', 'ascii', '--theme', 'green-screen', '--pet', 'codex1=dog', '--team', 'pipeline', '--layout', 'portrait', '--demo', '--still', '--no-color']) == 0
    settings = captured['settings']
    assert (settings.fps, settings.style, settings.theme, settings.layout, settings.team, settings.demo, settings.still) == (15, 'ascii', 'green-screen', 'portrait', 'pipeline', True, True)
    assert settings.pets['codex1']['sprite'] == 'dog'
    assert captured['live'] is False and captured['no_color'] == '1'
    assert 'NO_COLOR' not in __import__('os').environ


@pytest.mark.parametrize('argv', [['--fps', '7'], ['task', 'move', '1', 'invalid'], ['task', 'take', '-1'], ['status', '--watch', '0'], ['--board-check', '9'], ['--pet', 'invalid']])
def test_usage_exit_codes(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2


def test_task_list_filters_and_runtime_response(monkeypatch, capsys):
    assert main(['task', 'list', '--demo', '--agent', 'codex1', '--status', 'doing', '--json']) == 0
    cards = json.loads(capsys.readouterr().out)
    assert [card['id'] for card in cards] == ['T1']
    monkeypatch.setattr(tasks, 'run_command', lambda *args: 'invalid json')
    assert main(['task', 'move', '6', 'review', '--json']) == 1
    assert 'invalid GitHub issue response' in json.loads(capsys.readouterr().out)['error']


def test_config_path_show_and_no_color_env(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'settings.toml'
    assert main(['config', 'path', '--config', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out) == str(path)
    path.write_text('fps = 15\n')
    assert main(['config', 'show', '--config', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'fps': 15}
    monkeypatch.setenv('NO_COLOR', '1')
    assert main(['status', '--demo']) == 0
    assert '\x1b[' not in capsys.readouterr().out


@pytest.mark.parametrize('column', ['todo', 'doing', 'review', 'done'])
@pytest.mark.parametrize('agent', [None, 'codex1'])
def test_task_move_preserves_all_agent_labels(tmp_path, monkeypatch, column, agent):
    labels = {'status:doing', 'agent:codex1', 'agent:claude2', 'bug'}
    commands = []

    def run(args, project):
        commands.append(args)
        if 'view' in args:
            return json.dumps({'state': 'OPEN', 'labels': [{'name': name} for name in sorted(labels)]})
        if 'edit' in args:
            for index, value in enumerate(args):
                if value == '--remove-label':
                    labels.discard(args[index + 1])
                elif value == '--add-label':
                    labels.add(args[index + 1])
        return 'updated'

    monkeypatch.setattr(tasks, 'run_command', run)
    tasks.Tasks(tmp_path, OfficeSettings()).move(6, column, agent)
    assert {'agent:codex1', 'agent:claude2', 'bug'} <= labels
    assert {label for label in labels if label.startswith('status:')} == (set() if column == 'done' else {f'status:{column}'})
    assert all(not command[index + 1].startswith('agent:') for command in commands for index, value in enumerate(command) if value == '--remove-label')
