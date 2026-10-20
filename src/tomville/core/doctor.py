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
    expected = set(settings.pets) | set(settings.stages) | set(settings.agents)
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
    agents = []
    try:
        agents = asyncio.run(agent_list())
        add('Agent connection', True, f'{len(agents)} agents')
        expected = set(settings.pets) | set(settings.stages) | set(settings.agents)
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
    from tomville.core.team import detection, load_state
    try:
        state = load_state(project)
        for name, spec in settings.agents.items():
            live = next((a for a in agents if a.name == name), None)
            executable = shutil.which(spec.kind)
            script = False
            if executable:
                try:
                    with open(executable, 'rb') as stream:
                        script = b'node' in stream.read(256).split(b'\n', 1)[0]
                except OSError:
                    pass
            if live and live.status not in ('blocked', 'unknown') and executable and not script:
                continue
            pane = live.pane_id if live else state['agents'].get(name, {}).get('pane')
            report = detection(project, spec, pane, 'blocked at startup' if live and live.status == 'blocked' else 'agent status unknown' if live and live.status == 'unknown' else '')
            add(f'Detection {name}', False, report['detail'], report['fix'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        add('Team record', False, str(exc), 'Check .tomville/team.json')
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
    from tomville.core.telegram import health
    telegram_ok, detail = health(settings)
    add('Telegram', telegram_ok, detail, 'Check the bot log; restart tmv telegram run' if 'last successful poll' in detail else 'tmv telegram setup')
    add('GitHub watch', True, f'{"enabled" if settings.watch else "off (opt-in)"}; interval {settings.check_seconds:g} seconds ([board] check_seconds; tmv watch works manually)' if settings.source == 'github' else 'not active (board is not GitHub)')
    add('Settings', True, str(config_path(config)))
    return {'checks': checks, 'problems': sum(not c['ok'] and c['required'] for c in checks), 'warnings': sum(not c['ok'] and not c['required'] for c in checks)}
