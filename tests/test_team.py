"""Lifecycle tests replay recorded herdr replies; never start real agents."""
import json
from pathlib import Path

import pytest

from tomville.cli import main
from tomville.core import team, ville
from tomville.core.settings import AgentSpec, OfficeSettings, load_settings

FIXTURES = Path(__file__).parent / 'fixtures'


def recorded(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('HERDR_ENV', '1')
    monkeypatch.delenv('HERDR_PANE_ID', raising=False)
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path / 'user.toml'))
    calls = []
    agents, panes, tabs = [], [], []
    def run(args, project, **kw):
        calls.append((args, kw))
        if args[0] in ('tmv', 'git'):
            return ''
        command = args[1:3]
        if command == ['agent', 'list']:
            return json.dumps({'result': {'agents': agents}})
        if command == ['pane', 'list']:
            return json.dumps({'result': {'panes': panes}})
        if command == ['tab', 'list']:
            return json.dumps({'result': {'tabs': tabs}})
        if command == ['pane', 'process-info']:
            return (FIXTURES / 'herdr_shell_process.json').read_text()
        if command == ['agent', 'start']:
            data = recorded('herdr_agent_start.json')
            agent = data['result']['agent']
            agent.update(name=args[3], pane_id=args[args.index('--pane') + 1])
            agents.append(agent)
            return json.dumps(data)
        if command in (['tab', 'create'], ['pane', 'split'], ['worktree', 'create'], ['worktree', 'open']):
            file = {('tab', 'create'): 'herdr_tab_create.json', ('pane', 'split'): 'herdr_pane_split.json', ('worktree', 'create'): 'herdr_worktree_create.json', ('worktree', 'open'): 'herdr_worktree_open.json'}[tuple(command)]
            data = recorded(file)
            result = data['result']
            pane = result.get('root_pane') or result['pane']
            panes.append(pane)
            if 'tab' in result:
                tabs.append(result['tab'])
            return json.dumps(data)
        if command == ['pane', 'read']:
            return 'Trust this folder?'
        return json.dumps({'result': {}})
    monkeypatch.setattr(team, 'run_command', run)
    return tmp_path, calls, agents, panes, tabs


def settings(**specs):
    return OfficeSettings(lead='boss', agents=specs)


def test_up_sequential_models_office_and_repeat(runtime):
    project, calls, agents, panes, tabs = runtime
    conf = settings(boss=AgentSpec('boss', 'claude', place='here', model='model with spaces'), worker=AgentSpec('worker', 'codex'))
    rows = team.up(project, conf)
    assert [r['result'] for r in rows] == ['started', 'started', 'open']
    starts = [a for a, kw in calls if a[1:3] == ['agent', 'start']]
    assert starts[0][-3:] == ['--', '--model', 'model with spaces']
    assert calls[next(i for i, (a, kw) in enumerate(calls) if a == starts[0])][1]['timeout'] == 130
    assert len([a for a, kw in calls if a[0] == 'tmv']) == 2
    before = len(starts)
    team.up(project, conf)
    assert len([a for a, kw in calls if a[1:3] == ['agent', 'start']]) == before
    assert set(team.load_state(project)['agents']) == {'boss', 'worker'}


def test_caller_adopted_as_lead_and_never_closed(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    agents.append({'name': 'actual', 'agent': 'codex', 'pane_id': 'caller'})
    monkeypatch.setenv('HERDR_PANE_ID', 'caller')
    ville.write_ville(project, {'team': {'shape': 'lead', 'lead': 'boss'}, 'agents': {'boss': {'kind': 'claude', 'place': 'here'}}})
    conf = load_settings(project)
    assert team.up(project, conf)[0]['result'] == 'lead: actual'
    assert load_settings(project).lead == 'actual'
    assert 'boss' not in team.load_state(project)['agents']
    monkeypatch.delenv('HERDR_PANE_ID')
    team.up(project, load_settings(project))
    assert not any(a[1:3] == ['agent', 'start'] for a, kw in calls)
    team.down(project)
    assert not any(a == ['herdr', 'pane', 'close', 'caller'] for a, kw in calls)


def test_failed_detection_keeps_ownership_continues_and_does_not_duplicate(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    original = team.run_command
    def fail(args, project, **kw):
        if args[1:3] == ['agent', 'start'] and args[3] == 'boss':
            raise OSError((FIXTURES / 'herdr_agent_timeout.json').read_text())
        return original(args, project, **kw)
    monkeypatch.setattr(team, 'run_command', fail)
    conf = settings(boss=AgentSpec('boss', 'claude', place='here'), worker=AgentSpec('worker', 'codex'))
    rows = team.up(project, conf)
    assert rows[0]['result'] == 'FAILED' and rows[1]['result'] == 'started'
    assert 'pane' in rows[0]['detail'] and 'Trust this folder?' in rows[0]['detail']
    owned = team.load_state(project)['agents']['boss']
    before = len([a for a, kw in calls if a[1:3] == ['tab', 'create']])
    team.up(project, conf)
    assert team.load_state(project)['agents']['boss'] == owned
    assert len([a for a, kw in calls if a[1:3] == ['tab', 'create']]) == before


def test_open_existing_worktree_and_split(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    original = team.run_command
    def run(args, project, **kw):
        if args[:3] == ['git', 'worktree', 'list']:
            return 'worktree /tmp/existing\nbranch refs/heads/worker\n'
        return original(args, project, **kw)
    monkeypatch.setattr(team, 'run_command', run)
    team.make_place(project, AgentSpec('worker', 'codex'), 'lead')
    assert any(a[1:5] == ['worktree', 'open', '--path', '/tmp/existing'] for a, kw in calls)
    team.make_place(project, AgentSpec('split', 'claude', place='pane'), 'lead')
    assert any(a[1:4] == ['pane', 'split', 'lead'] for a, kw in calls)


def test_down_only_owned_identity_keeps_worktrees_and_caller(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    owned = {'pane': 'owned', 'terminal': 'term1', 'kind': 'codex'}
    team.save_state(project, {'agents': {'worker': owned, 'lead': dict(owned, pane='caller'), 'stale': dict(owned, pane='reused')}, 'office': None})
    panes.extend([{'pane_id': 'owned', 'terminal_id': 'term1', 'agent': 'codex', 'name': 'worker'}, {'pane_id': 'caller', 'terminal_id': 'term1'}, {'pane_id': 'reused', 'terminal_id': 'new'}])
    agents.append({'pane_id': 'owned', 'name': 'worker', 'agent': 'codex'})
    monkeypatch.setenv('HERDR_PANE_ID', 'caller')
    rows = team.down(project)
    assert [a for a, kw in calls if a[1:3] == ['pane', 'close']] == [['herdr', 'pane', 'close', 'owned']]
    assert any(a[-1] == '/quit' for a, kw in calls)
    assert not any(a[1] == 'worktree' for a, kw in calls)
    assert set(team.load_state(project)['agents']) == {'lead'}


def test_down_does_not_close_replacement_agent(runtime):
    project, calls, agents, panes, tabs = runtime
    team.save_state(project, {'agents': {'worker': {'pane': 'p', 'terminal': 't', 'kind': 'codex'}}, 'office': None})
    panes.append({'pane_id': 'p', 'terminal_id': 't', 'name': 'other', 'agent': 'claude'})
    agents.append({'pane_id': 'p', 'name': 'other', 'agent': 'claude'})
    assert team.down(project, 'worker')[0]['result'] == 'FAILED'
    assert not any(a[1:3] == ['pane', 'close'] for a, kw in calls)


def test_shell_wait_timeout(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    monkeypatch.setattr(team, 'run_command', lambda *a, **kw: (FIXTURES / 'herdr_codex_process.json').read_text())
    with pytest.raises(OSError, match='shell not ready'):
        team.wait_shell(project, 'p', 0)


def test_detection_missing_cli_and_unknown(runtime, monkeypatch):
    project, *_ = runtime
    spec = AgentSpec('w', 'codex')
    monkeypatch.setattr(team.shutil, 'which', lambda kind: None)
    assert 'Install codex' in team.detection(project, spec)['fix']
    binary = project / 'native'
    binary.write_bytes(b'\x7fELF')
    monkeypatch.setattr(team.shutil, 'which', lambda kind: str(binary))
    assert 'herdr agent explain' in team.detection(project, spec)['fix']


def test_launcher_confirmation_env_backup_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    pkg = tmp_path / 'lib/codex'
    (pkg / 'bin').mkdir(parents=True)
    script = pkg / 'bin/codex.js'
    script.write_text('#!/usr/bin/env node\n')
    binary = pkg / 'node_modules/@openai/codex-linux-arm64/vendor/aarch64-unknown-linux-musl/bin/codex'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'\x7fELF')
    binary.chmod(0o755)
    monkeypatch.setattr('platform.machine', lambda: 'aarch64')
    monkeypatch.setattr(team.shutil, 'which', lambda kind: str(script))
    destination = tmp_path / '.local/bin/codex'
    assert 'Cancelled' in team.install_launcher('codex', lambda q: False)
    assert not destination.exists()
    team.install_launcher('codex', lambda q: True)
    assert 'CODEX_MANAGED_PACKAGE_ROOT=' in destination.read_text()
    assert 'CODEX_MANAGED_BY_NPM=1' in destination.read_text()
    assert f'exec {binary}' in destination.read_text()
    assert destination.stat().st_mode & 0o111
    assert 'Already installed' in team.install_launcher('codex', lambda q: pytest.fail('unexpected question'))
    assert 'launcher codex' in team.detection(tmp_path, AgentSpec('w', 'codex'))['fix']


def test_cli_up_without_ville_asks_once_and_builds(runtime, monkeypatch, capsys):
    project, *_ = runtime
    answers = ville.Answers('Fresh', source='tasks-md', agent_specs={'boss': {'kind': 'claude', 'place': 'here'}}, lead='boss', workers=[])
    monkeypatch.setattr(ville, 'ask_answers', lambda *a: answers)
    monkeypatch.setattr(ville, 'run_steps', lambda *a: 0)
    assert main(['up', '-C', str(project)]) == 0
    assert ville.has_ville(project) and 'started' in capsys.readouterr().out


def test_wizard_start_now_calls_builder(runtime, monkeypatch):
    project, *_ = runtime
    answers = ville.Answers('Fresh', source='tasks-md', agent_specs={'boss': {'kind': 'claude', 'place': 'here'}}, lead='boss', workers=[])
    monkeypatch.setattr(ville, 'ask_answers', lambda *a: answers)
    monkeypatch.setattr(ville, 'run_steps', lambda *a: 0)
    monkeypatch.setattr('tomville.cli.confirm', lambda q: True)
    assert main(['new', '-C', str(project)]) == 0
    assert 'boss' in team.load_state(project)['agents']


def test_empty_mutation_output_is_success(runtime, monkeypatch):
    project, *_ = runtime
    monkeypatch.setattr(team, 'run_command', lambda *a, **kw: '')
    assert team.herdr(project, 'pane', 'run', 'p', 'tmv') == {}


def test_ready_agent_gets_pending_first_prompt_once(runtime):
    project, calls, agents, panes, tabs = runtime
    agents.append({'pane_id': 'p', 'name': 'boss', 'agent': 'claude', 'agent_status': 'idle'})
    team.save_state(project, {'agents': {'boss': {'pane': 'p', 'terminal': 't', 'kind': 'claude'}}, 'office': None})
    conf = settings(boss=AgentSpec('boss', 'claude', place='here'))
    team.up(project, conf)
    team.up(project, conf)
    assert len([a for a, kw in calls if a[0] == 'tmv']) == 1


def test_empty_recent_snapshot_falls_back_to_visible(runtime, monkeypatch):
    project, *_ = runtime
    original = team.run_command
    def run(args, project, **kw):
        if args[1:3] == ['pane', 'read'] and 'recent-unwrapped' in args:
            return ''
        return original(args, project, **kw)
    monkeypatch.setattr(team, 'run_command', run)
    report = team.detection(project, AgentSpec('boss', 'claude'), 'p')
    assert 'Trust this folder?' in report['detail']


def test_doctor_uses_shared_detection_without_starting(runtime, monkeypatch):
    from tomville.core import doctor
    project, calls, *_ = runtime
    async def empty_agents():
        return []
    monkeypatch.setattr(doctor, 'agent_list', empty_agents)
    monkeypatch.setattr(doctor, 'run_command', lambda *a: '')
    monkeypatch.setattr(doctor.shutil, 'which', lambda kind: None)
    (project / 'TASKS.md').write_text('| id | title | status | agent |\n')
    conf = settings(worker=AgentSpec('worker', 'codex'))
    conf.source = 'tasks-md'
    result = doctor.diagnose(project, conf)
    report = next(c for c in result['checks'] if c['name'] == 'Detection worker')
    assert 'Install codex' in report['fix']
    assert not any(a[1:3] == ['agent', 'start'] for a, kw in calls)


def test_secretary_prompt_restricts_email_and_lead(tmp_path):
    spec = AgentSpec('secretary', 'claude', role='secretary', email='allowed@example.invalid')
    prompt = team.first_prompt(spec, 'boss', {'secretary': spec}, tmp_path)
    assert 'Only boss' in prompt and 'email only allowed@example.invalid' in prompt


def test_launcher_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / 'codex'
    target.write_text('original launcher')
    monkeypatch.setattr(team, 'launcher_plan', lambda kind: (target, '#!/bin/sh\nexec /native "$@"\n'))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    team.install_launcher('codex', lambda q: True)
    assert target.with_name('codex.bak').read_text() == 'original launcher'
    with pytest.raises(ValueError, match='backup already exists'):
        team.install_launcher('codex', lambda q: True)


def test_down_preserves_agent_with_unavailable_identity(runtime):
    project, calls, agents, panes, tabs = runtime
    team.save_state(project, {'agents': {'worker': {'pane': 'p', 'terminal': 't', 'kind': 'codex'}}, 'office': None})
    panes.append({'pane_id': 'p', 'terminal_id': 't', 'agent': 'codex'})
    assert team.down(project)[0]['result'] == 'FAILED'
    assert not any(a[1:3] == ['pane', 'close'] for a, kw in calls)
