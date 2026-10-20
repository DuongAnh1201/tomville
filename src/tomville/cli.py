"""Command line entry point. Core command modules stay independent of Textual."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from tomville import __version__
from tomville.core.board.base import BoardUnavailable
from tomville.core.events import EventReader
from tomville.core.settings import config_path, load_settings, read_toml, write_config_value


def common_options(parser):
    # Suppressed defaults let options appear before or after any subcommand.
    parser.add_argument('-C', '--project', type=Path, default=argparse.SUPPRESS, metavar='DIR')
    parser.add_argument('--config', type=Path, default=argparse.SUPPRESS, help='settings TOML file')
    parser.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='machine-readable output')
    parser.add_argument('--no-color', action='store_true', default=argparse.SUPPRESS, help='disable colors (also NO_COLOR)')
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument('-q', '--quiet', action='store_true', default=argparse.SUPPRESS)
    verbosity.add_argument('-v', '--verbose', action='store_true', default=argparse.SUPPRESS)
    parser.add_argument('--lead', default=argparse.SUPPRESS, metavar='AGENT', help='who sits at the front desk (default: claude)')
    parser.add_argument('--fps', type=int, choices=(5, 10, 15, 30), default=argparse.SUPPRESS)
    parser.add_argument('--style', choices=('emoji', 'ascii', 'blocks'), default=argparse.SUPPRESS)
    parser.add_argument('--theme', choices=('night', 'game-boy', 'green-screen'), default=argparse.SUPPRESS)
    parser.add_argument('--pet', action='append', default=argparse.SUPPRESS, metavar='AGENT=PET')
    parser.add_argument('--board', default=argparse.SUPPRESS, help='github, tasks-md, or Markdown file path')
    parser.add_argument('--board-check', type=float, default=argparse.SUPPRESS, metavar='SEC', help='GitHub interval (minimum 10)')
    parser.add_argument('--poll', type=float, default=argparse.SUPPRESS, metavar='SEC')
    parser.add_argument('--layout', choices=('auto', 'landscape', 'portrait'), default=argparse.SUPPRESS)
    parser.add_argument('--team', choices=('lead', 'pipeline'), default=argparse.SUPPRESS)
    parser.add_argument('--demo', action='store_true', default=argparse.SUPPRESS, help='fake agents and tasks, no network or herdr')
    parser.add_argument('--still', action='store_true', default=argparse.SUPPRESS, help='jump directly to target positions')


def build_parser():
    parser = argparse.ArgumentParser(prog='tomville', description='A retro game view of your agent team, built on top of herdr.')
    parser.add_argument('-V', '--version', action='version', version=f'tomville {__version__}')
    common_options(parser)
    commands = parser.add_subparsers(dest='command')
    status = commands.add_parser('status', help='print the team and board')
    common_options(status)
    status.add_argument('--watch', nargs='?', const=1, type=float, metavar='SEC')
    status.add_argument('--agent', metavar='NAME')
    doctor = commands.add_parser('doctor', help='check setup and print fixes')
    common_options(doctor)
    config = commands.add_parser('config', help='read and write user settings')
    common_options(config)
    config_commands = config.add_subparsers(dest='config_command', required=True)
    for name in ('path', 'show', 'get', 'set'):
        sub = config_commands.add_parser(name)
        common_options(sub)
        if name in ('get', 'set'):
            sub.add_argument('key')
        if name == 'set':
            sub.add_argument('value')
    send = commands.add_parser('send', help='prompt another agent and log who sent it')
    common_options(send)
    send.add_argument('agent', help='herdr name of the agent to prompt')
    send.add_argument('text', nargs='+', help='the prompt')
    send.add_argument('--wait', action='store_true', help='wait until the agent settles (passed to herdr)')
    send.add_argument('--timeout', type=int, metavar='MS', help='give up after MS milliseconds (passed to herdr)')
    telegram = commands.add_parser('telegram', help='optional phone chat for this ville')
    common_options(telegram)
    telegram.add_argument('telegram_command', choices=('setup', 'run', 'status', 'pause', 'resume', 'off'))
    reply = commands.add_parser('reply', help='reply to the ville Telegram chat (HTML bold/italic)')
    common_options(reply)
    reply.add_argument('text')
    hook = commands.add_parser('hook', help=argparse.SUPPRESS)
    hook.add_argument('name', choices=('claude-pre-tool-use',))
    new = commands.add_parser('new', help='create a new ville for this project')
    common_options(new)
    new.add_argument('name', nargs='?', help='name of the ville')
    new.add_argument('--yes', action='store_true', help='accept the defaults, no questions')
    new.add_argument('--claude-settings', type=Path, metavar='FILE', help='Claude Code settings.json for the hook (default: ~/.claude/settings.json)')
    setup = commands.add_parser('setup', help='redo emoji test, labels, agent rules or the Claude hook')
    common_options(setup)
    setup.add_argument('--yes', action='store_true', help='redo labels, rules and hook without asking; skip the emoji test unless --style is given')
    setup.add_argument('--claude-settings', type=Path, metavar='FILE', help='Claude Code settings.json for the hook (default: ~/.claude/settings.json)')
    setup.add_argument('setup_part', nargs='?', choices=('launcher',))
    setup.add_argument('kind', nargs='?')
    up = commands.add_parser('up', help='start the team and office in herdr')
    common_options(up)
    down = commands.add_parser('down', help='close the office, or stop the team with --agents')
    common_options(down)
    stop = down.add_mutually_exclusive_group()
    stop.add_argument('name', nargs='?')
    stop.add_argument('--office', action='store_true', help='close only the owned office tab (default)')
    stop.add_argument('--agents', action='store_true', help='stop all ville agents, then the office')
    down.add_argument('--yes', action='store_true', help='confirm --agents without prompting')
    task = commands.add_parser('task', help='manage GitHub task cards')
    common_options(task)
    tasks = task.add_subparsers(dest='task_command', required=True)
    new = tasks.add_parser('new')
    common_options(new)
    new.add_argument('title')
    new.add_argument('--body', default='')
    new.add_argument('--agent')
    take = tasks.add_parser('take')
    common_options(take)
    take.add_argument('number', type=positive_issue)
    take.add_argument('--agent')
    move = tasks.add_parser('move')
    common_options(move)
    move.add_argument('number', type=positive_issue)
    move.add_argument('column', choices=('todo', 'doing', 'review', 'done'))
    listing = tasks.add_parser('list')
    common_options(listing)
    listing.add_argument('--agent')
    listing.add_argument('--status', choices=('todo', 'doing', 'review', 'done'))
    return parser


def positive_issue(value):
    try:
        number = int(value.removeprefix('#'))
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('issue number must be a positive integer')


def output(value, args, text=None):
    if args.json:
        print(json.dumps(value, ensure_ascii=False), flush=True)
    elif not args.quiet:
        print(text if text is not None else value, flush=True)


def config_command(args):
    path = config_path(args.config)
    if args.config_command == 'path':
        output(str(path), args)
    elif args.config_command == 'show':
        data = read_toml(path)
        output(data, args, path.read_text() if path.exists() else '')
    elif args.config_command == 'set':
        value = write_config_value(path, args.key, args.value)
        output({'key': args.key, 'value': value}, args, f'{args.key} = {value}')
    else:
        data = read_toml(path)
        try:
            for part in args.key.split('.'):
                data = data[part]
        except (KeyError, TypeError):
            raise ValueError(f'setting not found in {path}: {args.key}') from None
        output(data, args)
    return 0


def status_command(args, project, settings):
    from tomville.core.status import snapshot, format_status

    if args.watch is not None and not 0 < args.watch < float('inf'):
        raise ValueError('--watch interval must be positive and finite')
    reader = EventReader(project, settings)
    while True:
        data = snapshot(reader, project, settings, args.agent)
        output(data, args, format_status(data, settings))
        if args.watch is None:
            return int(bool(data['errors']))
        time.sleep(args.watch)


def task_command(args, project, settings):
    from tomville.core.tasks import Tasks

    if args.task_command == 'list':
        reader = EventReader(project, settings)
        if settings.demo:
            from tomville.core.status import demo_data
            reader.cards = {c.id: c for c in demo_data()[1]}
        else:
            reader.update_board()
        if reader.offline_since:
            raise OSError('board unavailable')
        from dataclasses import asdict
        cards = [asdict(c) for c in reader.cards.values() if (not args.agent or c.agent == args.agent) and (not args.status or c.column == args.status)]
        output(cards, args, '\n'.join(f"{c['id']} {c['column']} {c['title']}" + (f" ({c['agent']})" if c['agent'] else '') for c in cards))
        return 0
    tasks = Tasks(project, settings)
    if args.task_command == 'new':
        result = tasks.new(args.title, args.body, args.agent)
    elif args.task_command == 'take':
        result = tasks.move(args.number, 'doing', args.agent or tasks.current_agent())
    else:
        result = tasks.move(args.number, args.column)
    output({'result': result}, args, result)
    return 0


def prompt(question, default):
    return input(f'{question} [{default}]: ').strip() or default


def confirm(question):
    return prompt(question + ' (yes/no)', 'yes').lower().startswith('y')


def new_command(args, project, *, start=True):
    from tomville.core import ville

    if ville.has_ville(project):
        raise ValueError('this project already has a ville; run `tmv setup` to redo parts of it')
    ask = (lambda question, default: default) if args.yes else prompt
    answers = ville.ask_answers(project, args.name, ask)
    print(f'Saved {ville.write_ville(project, answers.data())}')
    settings = load_settings(project, config=args.config)
    failed = ville.run_steps(project, settings, ville.STEPS, args.claude_settings or ville.claude_settings_path())
    if start and answers.agent_specs and not args.yes and confirm('Start the team now?'):
        return max(int(failed > 0), team_command(args, project, settings, 'up'))
    elif start:
        print('Next: run `tmv up` to start the team (`tmv doctor` lists what is missing), then `tmv` in its own tab.')
    return int(failed > 0)


def setup_command(args, project, settings):
    from tomville.core import ville

    if args.setup_part == 'launcher':
        from tomville.core.team import install_launcher
        if not args.kind:
            raise ValueError('usage: tmv setup launcher KIND')
        output({'result': install_launcher(args.kind, lambda question: args.yes or confirm(question))}, args)
        return 0
    if args.kind:
        raise ValueError('unexpected setup argument')
    if not ville.has_ville(project):
        raise ValueError('no ville in this project; run `tmv new` first')
    updates = {key: getattr(args, key) for key in ('style', 'theme') if hasattr(args, key)}
    if 'style' not in updates and not args.yes and confirm('Redo the emoji test?'):
        updates['style'] = ville.calibrate(prompt)
    if updates:
        print(f'Saved {ville.update_ville(project, updates)}: ' + ', '.join(f'{k} = {v}' for k, v in updates.items()))
    steps = [step for step in ville.STEPS if args.yes or confirm(f'Redo {step}?')]
    return int(ville.run_steps(project, settings, steps, args.claude_settings or ville.claude_settings_path()) > 0)


def team_command(args, project, settings, command):
    from tomville.core import team, ville

    if command == 'up' and not ville.has_ville(project):
        args.name, args.yes, args.claude_settings = None, False, None
        if new_command(args, project, start=False):
            return 1
        settings = load_settings(project, config=args.config)
    def approve_shutdown(preview):
        for row in preview:
            print(f"{row['agent']} · {row['pane'] or '—'} · {row['result']}", file=sys.stderr, flush=True)
        if args.yes:
            return True
        if not sys.stdin.isatty():
            raise ValueError('tmv down --agents requires --yes when non-interactive')
        return input('Stop them? [y/N] ').strip().lower() in ('y', 'yes')

    rows = team.up(project, settings) if command == 'up' else team.down(
        project, args.name, settings=settings, agents=args.agents, confirm=approve_shutdown)

    lines = ['agent · place · pane · result']
    for row in rows:
        lines.append(' · '.join(str(row.get(k) or '—') for k in ('agent', 'place', 'pane', 'result')))
        if row.get('detail'):
            lines.append(row['detail'])
        if row.get('fix'):
            lines.append('Fix: ' + row['fix'])
    output(rows, args, '\n'.join(lines))
    return int(any(row['result'].startswith('FAILED') for row in rows))


def offer_new(args, project, settings):
    """Bare `tomville` in a project with no ville: offer `tmv new`. True if it created one."""
    if settings.demo or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    from tomville.core.ville import has_ville

    if has_ville(project):
        return False
    if not confirm('No ville in this project yet. Create one now with `tmv new`?'):
        return False
    args.name, args.yes, args.claude_settings = None, False, None
    new_command(args, project)
    return True


def dependency_checks():
    """Check imports in the running tool's interpreter, not another install."""
    checks = []
    for module in ('textual', 'tomli_w'):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            checks.append(dict(name=f'Dependency {module}', ok=False,
                               detail=str(exc), required=True,
                               fix='uv tool install --editable . --reinstall'))
        else:
            checks.append(dict(name=f'Dependency {module}', ok=True,
                               detail='installed', required=True, fix=''))
    return checks


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    for name, default in {'project': Path.cwd(), 'config': None, 'json': False, 'no_color': False, 'quiet': False, 'verbose': False}.items():
        if not hasattr(args, name):
            setattr(args, name, default)
    if args.command == 'hook':
        from tomville.core.messages import claude_hook
        return claude_hook()
    project = args.project.expanduser().resolve()
    try:
        if args.command == 'config':
            return config_command(args)
        if not project.is_dir():
            raise ValueError(f'project directory does not exist: {project}')
        keys = {'source': 'board', 'check_seconds': 'board_check', 'poll_seconds': 'poll', 'pets': 'pet'}
        settings = load_settings(project, config=args.config, **{key: getattr(args, keys.get(key, key), None) for key in ('source', 'check_seconds', 'poll_seconds', 'pets', 'fps', 'style', 'theme', 'layout', 'team', 'lead', 'demo', 'still')})
        if args.verbose:
            print(f'Project: {project} · Settings: {config_path(args.config)}', file=sys.stderr)
        if args.command in ('telegram', 'reply'):
            from tomville.core import telegram
            if args.command == 'reply':
                from tomville.core.messages import repo_root
                root = repo_root(project)
                telegram.reply(root, load_settings(root, config=args.config), args.text)
                return 0
            action = args.telegram_command
            if action == 'setup':
                telegram.setup(project, settings, prompt)
            elif action == 'run':
                telegram.run(project, settings)
            elif action == 'off':
                telegram.off(project, settings, lambda question: input(question + ' [y/N] ').lower() in ('yes', 'y'))
            elif action in ('pause', 'resume'):
                telegram.change_config(settings, paused=action == 'pause')
                output('Paused' if action == 'pause' else 'Resumed', args)
            else:
                ok, detail = telegram.health(settings)
                output({'ok': ok, 'detail': detail}, args, 'Telegram: ' + detail)
                return int(not ok)
            return 0
        if args.command == 'status':
            return status_command(args, project, settings)
        if args.command == 'doctor':
            from tomville.core.doctor import diagnose
            dependencies = dependency_checks()
            result = diagnose(project, settings, args.config)
            result['checks'] = dependencies + result['checks']
            result['problems'] += sum(not check['ok'] for check in dependencies)
            lines = [f'Tomville doctor · v{__version__}']
            for check in result['checks']:
                if args.quiet and check['ok']:
                    continue
                lines.append(f"{'OK' if check['ok'] else 'FAIL' if check['required'] else 'WARN'} {check['name']}: {check['detail']}" + (f" → {check['fix']}" if check['fix'] else ''))
            lines.append(f"{result['problems']} problems · {result['warnings']} warnings")
            output(result, args, '\n'.join(lines))
            return int(result['problems'] > 0)
        if args.command in ('up', 'down'):
            return team_command(args, project, settings, args.command)
        if args.command == 'task':
            return task_command(args, project, settings)
        if args.command == 'new':
            return new_command(args, project)
        if args.command == 'setup':
            return setup_command(args, project, settings)
        if args.command == 'send':
            from tomville.core.messages import repo_root, send
            result = send(repo_root(project), args.agent, ' '.join(args.text), args.wait, args.timeout)
            output({'sent': args.agent, 'herdr': result}, args, f'sent to {args.agent}')
            return 0
        if (args.command is None and not settings.demo
                and sys.stdin.isatty() and sys.stdout.isatty()
                and offer_new(args, project, settings)):
            settings = load_settings(project, config=args.config)
        from tomville.tui.app import TomvilleApp
        previous_no_color = os.environ.get('NO_COLOR')
        if args.no_color:
            os.environ['NO_COLOR'] = '1'
        try:
            app = TomvilleApp(project=project, settings=settings, live=not settings.demo)
            app.run()
        finally:
            if previous_no_color is None:
                os.environ.pop('NO_COLOR', None)
            else:
                os.environ['NO_COLOR'] = previous_no_color
        return 0
    except KeyboardInterrupt:
        return 0
    except EOFError:
        print('tomville: cancelled', file=sys.stderr)
        return 1
    except (ValueError, TypeError, KeyError) as exc:
        if args.json:
            output({'error': str(exc)}, args)
            return 2
        parser.error(str(exc))
    except (OSError, subprocess.SubprocessError, BoardUnavailable) as exc:
        if args.json:
            output({'error': str(exc)}, args)
        else:
            print(f'tomville: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
