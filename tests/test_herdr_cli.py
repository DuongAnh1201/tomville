"""Offline checks of the shared contract and the CI help checker."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from tomville.core import doctor
from tomville.core.herdr_cli import CALLS, TESTED_RANGE, argv, tested_version as version_is_tested
from tomville.core.settings import OfficeSettings


@pytest.mark.parametrize('version,ok', [
    ('herdr 0.9.5', True), ('herdr 0.9.4', False),
    ('herdr 0.9.6', False), ('herdr 0.10.0', False),
    ('herdr 0.9.5-rc.1', False), ('unknown', False)])
def test_version_row(tmp_path, monkeypatch, version, ok):
    async def agents():
        return []
    monkeypatch.setattr(doctor, 'agent_list', agents)
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: '/fixture/herdr')
    monkeypatch.setattr(doctor, 'run_command', lambda args, project: version if '--version' in args else '')
    conf = OfficeSettings(source='tasks-md', lead='')
    (tmp_path / 'TASKS.md').write_text('')
    result = doctor.diagnose(tmp_path, conf)
    row = next(r for r in result['checks'] if r['name'] == 'herdr version')
    assert row['ok'] is ok
    assert not row['required']
    assert TESTED_RANGE in row['detail']
    assert version_is_tested(version) is ok
    assert row['fix'] == '' if ok else 'herdr --version' in row['fix']


def checker():
    spec = importlib.util.spec_from_file_location('check_herdr_cli', Path(__file__).parents[1] / 'scripts/check_herdr_cli.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_help_checker_covers_every_command_and_rejects_removed_flag():
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        command = tuple(args[1:-1] if args[-1] == '--help' else args[1:])
        return SimpleNamespace(stdout='Options: ' + ' '.join(CALLS[command][1]), stderr='')
    checker().check(run)
    assert len(calls) == len(CALLS)
    assert all(args[-1] in ('--help', '--version') for args in calls)
    def missing(args, **kwargs):
        result = run(args, **kwargs)
        result.stdout = result.stdout.replace('--direction', '--direction-other')
        return result
    with pytest.raises(ValueError, match='no longer documents --direction'):
        checker().check(missing)


def test_contract_rejects_drift_preserves_payload_and_agent_options():
    with pytest.raises(ValueError, match='Undeclared herdr command'):
        argv('pane', 'new')
    with pytest.raises(ValueError, match='Undeclared herdr option'):
        argv('pane', 'split', 'p', '--new-flag')
    assert argv('agent', 'prompt', 'worker', '--arbitrary prompt')[-1] == '--arbitrary prompt'
    assert argv('agent', 'start', 'worker', '--kind', 'codex', '--', '--model', 'new')[-2:] == ['--model', 'new']


def test_usage_error_keeps_failing_command(tmp_path, monkeypatch):
    from tomville.core import commands
    from tomville.core.herdr_cli import usage_hint
    monkeypatch.setattr(commands.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=2, stdout='', stderr="error: unexpected argument '--direction'"))
    with pytest.raises(OSError) as error:
        commands.run_command(['herdr', 'pane', 'split', 'p', '--direction', 'right'], tmp_path)
    assert '`herdr pane split`' in usage_hint(error.value)


@pytest.mark.parametrize('installed', [False, True])
def test_doctor_missing_or_unreadable_version(tmp_path, monkeypatch, installed):
    async def agents():
        return []
    monkeypatch.setattr(doctor, 'agent_list', agents)
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: '/fixture/herdr' if installed else None)
    def fail(*args):
        raise OSError('version unavailable')
    monkeypatch.setattr(doctor, 'run_command', fail)
    monkeypatch.setattr(doctor.EventReader, 'update_board', lambda self: [])
    result = doctor.diagnose(tmp_path, OfficeSettings(source='tasks-md', lead=''))
    rows = [r for r in result['checks'] if r['name'] == 'herdr version']
    if installed:
        assert len(rows) == 1 and not rows[0]['ok'] and not rows[0]['required']
    else:
        assert not rows
        assert any(r['name'] == 'herdr' and not r['ok'] and r['required'] for r in result['checks'])
