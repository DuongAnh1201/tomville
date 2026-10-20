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
    rows = team.down(project, settings=settings(worker=AgentSpec('worker', 'codex'), lead=AgentSpec('lead', 'claude'), stale=AgentSpec('stale', 'claude')), agents=True, confirm=lambda rows: True)
    assert [a for a, kw in calls if a[1:3] == ['pane', 'close']] == [['herdr', 'pane', 'close', 'owned']]
    assert any(a[-1] == '/quit' for a, kw in calls)
    assert not any(a[1] == 'worktree' for a, kw in calls)
    assert set(team.load_state(project)['agents']) == {'lead', 'stale'}


def test_down_does_not_close_replacement_agent(runtime):
    project, calls, agents, panes, tabs = runtime
    team.save_state(project, {'agents': {'worker': {'pane': 'p', 'terminal': 't', 'kind': 'codex'}}, 'office': None})
    panes.append({'pane_id': 'p', 'terminal_id': 't', 'name': 'other', 'agent': 'claude'})
    agents.append({'pane_id': 'p', 'name': 'other', 'agent': 'claude'})
    assert team.down(project, 'worker')[0]['result'].startswith('FAILED')
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
    assert team.down(project, 'worker')[0]['result'].startswith('FAILED')
    assert not any(a[1:3] == ['pane', 'close'] for a, kw in calls)


def office_state(runtime):
    project, calls, agents, panes, tabs = runtime
    pane = recorded('herdr_tab_create.json')['result']['root_pane']
    panes.append(pane)
    record = {'pane': pane['pane_id'], 'terminal': pane['terminal_id'], 'tab': pane['tab_id']}
    team.save_state(project, {'agents': {'working': {'pane': 'working', 'terminal': 'busy', 'kind': 'codex'}}, 'office': record})
    agents.append({'pane_id': 'working', 'name': 'working', 'agent': 'codex', 'agent_status': 'working'})
    return record


@pytest.mark.parametrize('option', [[], ['--office']])
def test_down_default_and_office_keep_all_agents(runtime, option):
    project, calls, agents, panes, tabs = runtime
    office = office_state(runtime)
    assert main(['down', *option, '-C', str(project)]) == 0
    assert any(a == ['herdr', 'tab', 'close', office['tab']] for a, kw in calls)
    assert not any(a[1:3] in (['agent', 'prompt'], ['agent', 'send-keys'], ['agent', 'list']) for a, kw in calls)
    assert 'working' in team.load_state(project)['agents']


def shutdown_team(runtime):
    project, calls, agents, panes, tabs = runtime
    office = office_state(runtime)
    agents.clear()
    conf = settings(boss=AgentSpec('boss', 'claude', place='here'), secretary=AgentSpec('secretary', 'claude', role='secretary'), worker=AgentSpec('worker', 'codex'), outsider_missing=AgentSpec('outsider_missing', 'gemini'))
    for name, status in [('boss', 'idle'), ('secretary', 'blocked'), ('worker', 'working'), ('unrelated', 'working')]:
        agent = dict(recorded('herdr_agent_start.json')['result']['agent'], name=name, agent='codex' if name == 'worker' else 'claude', pane_id=name, terminal_id='term-' + name, agent_status=status)
        agents.append(agent)
        panes.append(dict(agent))
    state = team.load_state(project)
    state['agents'] = {'worker': {'pane': 'worker', 'terminal': 'term-worker', 'kind': 'codex'}}
    team.save_state(project, state)
    return conf, office


def test_full_shutdown_order_owned_and_existing_panes(runtime):
    project, calls, *_ = runtime
    conf, office = shutdown_team(runtime)
    previews = []
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: previews.append(rows) or True)
    assert [r['agent'] for r in rows] == ['worker', 'outsider_missing', 'secretary', 'boss', 'office']
    assert [r['result'] for r in rows] == ['stopped', 'not running', 'stopped (pane kept)', 'stopped (pane kept)', 'stopped']
    assert any(r['result'] == 'working (busy)' for r in previews[0])
    assert any(r['result'] == 'blocked (waiting for an answer)' for r in previews[0])
    assert [a[3] for a, kw in calls if a[1:3] == ['agent', 'prompt']] == ['worker', 'secretary', 'boss']
    assert [a[3] for a, kw in calls if a[1:3] == ['pane', 'close']] == ['worker']
    assert not any('unrelated' in a for a, kw in calls)
    assert team.load_state(project)['agents'] == {} and team.load_state(project)['office'] is None


def test_full_shutdown_keeps_caller_and_reports_it(runtime, monkeypatch):
    project, calls, *_ = runtime
    conf, _ = shutdown_team(runtime)
    monkeypatch.setenv('HERDR_PANE_ID', 'boss')
    previews = []
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: previews.append(rows) or True)
    assert next(r for r in rows if r['agent'] == 'boss')['result'] == 'kept: lead/caller'
    assert next(r for r in previews[0] if r['agent'] == 'boss')['result'] == 'kept: lead/caller'
    assert not any(a[1:3] == ['agent', 'prompt'] and a[3] == 'boss' for a, kw in calls)


def test_declined_shutdown_changes_nothing(runtime):
    project, calls, *_ = runtime
    conf, _ = shutdown_team(runtime)
    before = (project / team.STATE).read_text()
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: False)
    assert all(r['result'] == 'cancelled' for r in rows)
    assert (project / team.STATE).read_text() == before
    assert all(a[1:3] in (['pane', 'list'], ['agent', 'list']) for a, kw in calls)


@pytest.mark.parametrize('options', [['--office', '--agents'], ['worker', '--office'], ['worker', '--agents']])
def test_shutdown_conflicting_options_are_usage_errors(runtime, options):
    project, calls, *_ = runtime
    with pytest.raises(SystemExit) as exc:
        main(['down', *options, '-C', str(project)])
    assert exc.value.code == 2 and calls == []


def test_full_shutdown_noninteractive_requires_yes(runtime, monkeypatch, capsys):
    project, calls, *_ = runtime
    ville.write_ville(project, {'team': {'shape': 'lead', 'lead': 'boss'}, 'agents': {'boss': {'kind': 'claude'}}})
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(SystemExit) as exc:
        main(['down', '--agents', '-C', str(project)])
    assert exc.value.code == 2
    assert 'requires --yes when non-interactive' in capsys.readouterr().err
    assert all(a[1:3] in (['pane', 'list'], ['agent', 'list']) for a, kw in calls)
    assert main(['down', '--agents', '--yes', '-C', str(project)]) == 0


def test_full_shutdown_default_no_and_prompt_flags(runtime, monkeypatch, capsys):
    project, calls, *_ = runtime
    conf, _ = shutdown_team(runtime)
    ville.write_ville(project, {'team': {'shape': 'lead', 'lead': 'boss'}, 'agents': {'worker': {'kind': 'codex'}, 'secretary': {'kind': 'claude', 'role': 'secretary'}, 'boss': {'kind': 'claude'}}})
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    prompts = []
    monkeypatch.setattr('builtins.input', lambda text: prompts.append(text) or '')
    assert main(['down', '--agents', '-C', str(project)]) == 0
    assert prompts == ['Stop them? [y/N] ']
    output = capsys.readouterr().err
    assert 'working (busy)' in output and 'blocked (waiting for an answer)' in output
    assert all(a[1:3] in (['pane', 'list'], ['agent', 'list']) for a, kw in calls)


def test_full_shutdown_adopted_lead_stops_when_not_caller(runtime):
    project, calls, *_ = runtime
    conf, _ = shutdown_team(runtime)
    state = team.load_state(project)
    state['lead_pane'] = 'boss'
    team.save_state(project, state)
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: True)
    assert next(r for r in rows if r['agent'] == 'boss')['result'] == 'stopped (pane kept)'


def test_named_shutdown_keeps_office_and_other_agents(runtime):
    project, calls, *_ = runtime
    shutdown_team(runtime)
    rows = team.down(project, 'worker')
    assert [r['agent'] for r in rows] == ['worker']
    assert rows[0]['result'] == 'stopped'
    assert team.load_state(project)['office'] is not None
    assert not any(a[1:3] == ['tab', 'close'] for a, kw in calls)


def test_full_shutdown_rechecks_identity_after_confirmation(runtime):
    project, calls, agents, panes, tabs = runtime
    conf, _ = shutdown_team(runtime)
    def approve(rows):
        next(a for a in agents if a['name'] == 'worker')['name'] = 'replacement'
        return True
    rows = team.down(project, settings=conf, agents=True, confirm=approve)
    assert next(r for r in rows if r['agent'] == 'worker')['result'].startswith('FAILED: pane now belongs to replacement')
    assert not any(a[1:3] == ['agent', 'prompt'] and a[3] == 'worker' for a, kw in calls)


def test_full_shutdown_includes_running_agent_with_gone_owned_pane(runtime):
    project, calls, *_ = runtime
    conf, _ = shutdown_team(runtime)
    state = team.load_state(project)
    state['agents']['worker']['pane'] = 'gone'
    team.save_state(project, state)
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: True)
    assert next(r for r in rows if r['agent'] == 'worker')['result'] == 'stopped (pane kept)'
    assert not any(a == ['herdr', 'pane', 'close', 'worker'] for a, kw in calls)


def test_shutdown_waits_for_recorded_slow_exit(runtime, monkeypatch, capsys):
    project, calls, agents, panes, tabs = runtime
    conf, _ = shutdown_team(runtime)
    conf.start_timeout = 12
    elapsed = [0.0]
    original = team.run_command
    def run(args, project, **kw):
        if args[1:3] == ['pane', 'process-info'] and args[-1] == 'worker':
            fixture = 'herdr_codex_process.json' if elapsed[0] < 6 else 'herdr_shell_process.json'
            return (FIXTURES / fixture).read_text()
        return original(args, project, **kw)
    monkeypatch.setattr(team, 'run_command', run)
    monkeypatch.setattr(team.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(team.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: True)
    assert next(r for r in rows if r['agent'] == 'worker')['result'] == 'stopped'
    assert 6 <= elapsed[0] < conf.start_timeout
    assert 'waiting for worker to quit…' in capsys.readouterr().err
    assert any(a == ['herdr', 'pane', 'close', 'worker'] for a, kw in calls)


@pytest.mark.parametrize('timeout', [None, 42])
def test_named_shutdown_uses_default_or_configured_timeout(runtime, monkeypatch, timeout):
    project, *_ = runtime
    conf, _ = shutdown_team(runtime)
    conf.start_timeout = timeout or 120
    waited = []
    monkeypatch.setattr(team, 'wait_shell', lambda project, pane, seconds: waited.append(seconds))
    rows = team.down(project, 'worker', settings=conf if timeout else None)
    assert rows[0]['result'] == 'stopped'
    assert waited == [timeout or 120]


def test_shutdown_timeout_keeps_owned_pane(runtime, monkeypatch):
    project, calls, *_ = runtime
    conf, _ = shutdown_team(runtime)
    def timeout(project, pane, seconds):
        raise OSError(f'shell not ready in {pane}')
    monkeypatch.setattr(team, 'wait_shell', timeout)
    rows = team.down(project, 'worker', settings=conf)
    assert rows[0]['result'].startswith('FAILED: shell not ready')
    assert 'worker' in team.load_state(project)['agents']
    assert not any(a == ['herdr', 'pane', 'close', 'worker'] for a, kw in calls)


def test_telegram_tab_up_repeat_and_shutdown(runtime):
    project, calls, agents, panes, tabs = runtime
    conf = settings(boss=AgentSpec('boss', 'claude', place='here'))
    conf.telegram['enabled'] = True
    team.up(project, conf)
    commands = [a for a, kw in calls if a[1:3] == ['pane', 'run']]
    assert commands[-1][-1].endswith('telegram run')
    assert '--label' in next(a for a, kw in calls if 'telegram' in a)
    assert team.load_state(project)['telegram']['launched']
    before = len(commands)
    team.up(project, conf)
    assert len([a for a, kw in calls if a[1:3] == ['pane', 'run']]) == before
    team.down(project)
    assert team.load_state(project)['telegram'] is not None
    rows = team.down(project, settings=conf, agents=True, confirm=lambda rows: True)
    assert any(r['agent'] == 'telegram' and r['result'] == 'stopped' for r in rows)
    assert team.load_state(project)['telegram'] is None


def test_up_names_unnamed_adopted_lead_and_records_identity(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    caller = recorded('herdr_named_agents.json')['result']['agents'][0]
    assert not caller.get('name')
    agents.append(caller)
    monkeypatch.setenv('HERDR_PANE_ID', caller['pane_id'])
    conf = settings(boss=AgentSpec('boss', 'claude', place='here'))
    rows = team.up(project, conf)
    assert rows[0]['result'] == 'lead: boss'
    assert any(a == ['herdr', 'agent', 'rename', caller['pane_id'], 'boss'] for a, kw in calls)
    state = team.load_state(project)
    assert state['lead_pane'] == caller['pane_id']
    assert state['lead_terminal'] == caller['terminal_id']
    assert state['lead_kind'] == 'claude'
    assert not any(a[1:3] == ['agent', 'start'] for a, kw in calls)
    # Once herdr has the name, repeated startup must not rename it again.
    caller['name'] = 'boss'
    calls.clear()
    team.up(project, conf)
    assert not any(a[1:3] == ['agent', 'rename'] for a, kw in calls)


def test_up_reports_adopted_lead_rename_failure(runtime, monkeypatch):
    project, calls, agents, panes, tabs = runtime
    caller = recorded('herdr_named_agents.json')['result']['agents'][0]
    agents.append(caller)
    monkeypatch.setenv('HERDR_PANE_ID', caller['pane_id'])
    original = team.run_command
    def run(args, project, **kw):
        if args[1:3] == ['agent', 'rename']:
            raise OSError('agent name already in use')
        return original(args, project, **kw)
    monkeypatch.setattr(team, 'run_command', run)
    with pytest.raises(OSError, match='name already in use'):
        team.up(project, settings(boss=AgentSpec('boss', 'claude', place='here')))
    assert not (project / team.STATE).exists()
