"""Read-only environment checks with concrete fixes."""
import asyncio
import json
import os
import shutil
import sys
import subprocess

from tomville.core.commands import run_command
from tomville.core.events import EventReader, agent_list
from tomville.core.settings import config_path


def diagnose(project, settings, config=None):
    checks = []
    expected = set(settings.pets) | set(settings.stages)
    if settings.lead:
        expected.add(settings.lead)
    def add(name, ok, detail, fix='', required=False):
        checks.append(dict(name=name, ok=ok, detail=detail, fix=fix if not ok else '', required=required))
    add('Python', sys.version_info >= (3, 11), sys.version.split()[0], 'Install Python 3.11+', True)
    size = shutil.get_terminal_size()
    add('Terminal', True, f'{size.columns} × {size.lines} cells')
    herdr = shutil.which('herdr')
    add('herdr', bool(herdr), herdr or 'not on PATH', 'Install herdr and add it to PATH', True)
    add('Inside herdr', os.environ.get('HERDR_ENV') == '1', 'HERDR_ENV=' + os.environ.get('HERDR_ENV', ''), 'Run tmv in a herdr pane', True)
    try:
        agents = asyncio.run(agent_list())
        add('Agent connection', True, f'{len(agents)} agents')
        expected = set(settings.pets) | set(settings.stages)
        if settings.lead:
            expected.add(settings.lead)
        try:
            integrations = run_command(['herdr', 'integration', 'status'], project)
            for kind in sorted({a.kind for a in agents}):
                line = next((line for line in integrations.splitlines() if line.startswith(kind + ':')), '')
                add(f'Integration {kind}', ': current' in line, line or 'not found', f'herdr integration install {kind}')
        except (OSError, subprocess.SubprocessError) as exc:
            add('Integrations', False, str(exc), 'herdr integration status')
        for name in sorted(expected):
            add(f'Agent {name}', any(a.name == name for a in agents), name, f'herdr agent start {name} --kind <kind> --pane <pane>')
    except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError) as exc:
        add('Agent connection', False, str(exc), 'Start herdr and check HERDR_SOCKET_PATH', True)
    if settings.source == 'github':
        try:
            run_command(['gh', 'auth', 'status'], project)
            add('GitHub login', True, 'gh authenticated')
        except (OSError, subprocess.SubprocessError) as exc:
            add('GitHub login', False, str(exc), 'gh auth login')
        try:
            args = ['gh', 'label', 'list', '--limit', '1000', '--json', 'name']
            if settings.repo:
                args += ['--repo', settings.repo]
            labels = {label['name'] for label in json.loads(run_command(args, project))}
            needed = {'status:todo', 'status:doing', 'status:review'} | {f'agent:{name}' for name in expected}
            missing = sorted(needed - labels)
            add('Board labels', not missing, ', '.join(missing) if missing else 'ready', 'tmv setup (create board labels)')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            add('Board labels', False, str(exc), 'Check gh login and the board repository')
    reader = EventReader(project, settings)
    reader.update_board()
    add('Board', reader.offline_since is None, f'{len(reader.cards)} cards' if reader.offline_since is None else 'unavailable', 'Check board source, repository or TASKS.md')
    add('Settings', True, str(config_path(config)))
    return {'checks': checks, 'problems': sum(not c['ok'] and c['required'] for c in checks), 'warnings': sum(not c['ok'] and not c['required'] for c in checks)}
