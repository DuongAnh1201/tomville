"""Sequential, restartable team startup and diagnostics. No UI dependencies."""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

from tomville.core.commands import run_command

STATE = Path('.tomville/team.json')
ERRORS = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def herdr(project, *args, timeout=30):
    raw = run_command(['herdr', *args], project, timeout=timeout)
    if not raw:
        return {}
    data = json.loads(raw)
    if data.get('error'):
        raise OSError(json.dumps(data['error']))
    return data['result']


def load_state(project):
    path = project / STATE
    return json.loads(path.read_text()) if path.exists() else {'agents': {}, 'office': None}


def save_state(project, state):
    path = project / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2) + '\n')
    temp.replace(path)


def agent_name(agent):
    return agent.get('name') or agent.get('agent') or agent.get('agent_session', {}).get('agent')


def wait_shell(project, pane, timeout):
    deadline = time.monotonic() + timeout
    while True:
        info = herdr(project, 'pane', 'process-info', '--pane', pane)['process_info']
        foreground = info.get('foreground_processes', [])
        if foreground and all(p['pid'] == info.get('shell_pid') for p in foreground):
            return
        if time.monotonic() >= deadline:
            raise OSError(f'shell not ready in {pane}')
        time.sleep(.2)


def launcher_plan(kind):
    """Resolve an npm Codex native binary, never guess another CLI's env."""
    if not re.fullmatch(r'[a-z][a-z0-9-]*', kind):
        raise ValueError('invalid agent kind')
    launcher = shutil.which(kind)
    if not launcher:
        raise OSError(f'{kind} is not on PATH; install its CLI first')
    source = Path(launcher).resolve()
    with source.open('rb') as stream:
        text = stream.read(16384).decode('utf-8', 'replace')
    if kind != 'codex' or 'node' not in text.split('\n', 1)[0]:
        raise ValueError(f'{kind}: no supported script launcher found; run herdr agent explain')
    package = source.parent.parent
    machine = platform.machine()
    arch = {'aarch64': 'aarch64', 'arm64': 'aarch64', 'x86_64': 'x86_64', 'amd64': 'x86_64'}.get(machine)
    candidates = list(package.glob(f'node_modules/@openai/codex-*/vendor/{arch}-*/bin/codex')) if arch else []
    candidates += list(package.glob(f'vendor/{arch}-*/bin/codex')) if arch else []
    candidates = [p for p in candidates if os.access(p, os.X_OK)]
    if len(candidates) != 1:
        raise ValueError(f'{kind}: cannot resolve one native binary; run herdr agent explain')
    binary = candidates[0]
    bindir = binary.parent.parent / 'path'
    script = '#!/bin/sh\n# Tomville native Codex launcher (bypasses the npm node process).\n'
    script += f'export CODEX_MANAGED_PACKAGE_ROOT={shlex.quote(str(package))}\nexport CODEX_MANAGED_BY_NPM=1\n'
    if bindir.is_dir():
        script += f'export PATH={shlex.quote(str(bindir))}:"$PATH"\n'
    script += f'exec {shlex.quote(str(binary))} "$@"\n'
    return Path.home() / '.local/bin' / kind, script


def install_launcher(kind, confirm):
    if not re.fullmatch(r'[a-z][a-z0-9-]*', kind):
        raise ValueError('invalid agent kind')
    existing = Path.home() / '.local/bin' / kind
    if existing.is_file() and not existing.is_symlink():
        with existing.open('rb') as stream:
            if b'# Tomville native Codex launcher' in stream.read(256):
                return f'Already installed: {existing}'
    path, script = launcher_plan(kind)
    if not confirm(f'Write {path} (outside this project)?'):
        return f'Cancelled: {path}'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        backup = path.with_name(path.name + '.bak')
        if backup.exists():
            raise ValueError(f'backup already exists: {backup}; keep or move it first')
        path.rename(backup)
    path.write_text(script)
    path.chmod(0o755)
    return f'Wrote {path}; put ~/.local/bin first on PATH and run tmv up in a fresh pane'


def detection(project, spec, pane=None, error=''):
    """Facts plus actionable advice; also used by doctor, without mutations."""
    facts = [str(error)] if error else []
    if pane:
        facts.append(f'pane {pane}')
        for args in [('pane', 'process-info', '--pane', pane),
                     ('pane', 'read', pane, '--source', 'recent-unwrapped', '--lines', '12')]:
            try:
                output = run_command(['herdr', *args], project)
                if args[:2] == ('pane', 'read') and not output.strip():
                    output = run_command(['herdr', 'pane', 'read', pane, '--source', 'visible', '--lines', '20'], project)
                facts.append(output)
            except ERRORS as exc:
                facts.append(str(exc))
    executable = shutil.which(spec.kind)
    text = '\n'.join(facts)
    if not executable or 'command not found' in text or 'not found in PATH' in text:
        fix = f'Install {spec.kind} and add it to PATH; retry tmv up in a fresh pane'
    elif any(word in text.lower() for word in ('trust', 'login', 'sign in', 'agent_not_ready', 'blocked')):
        fix = 'Answer the startup question in that pane, then retry tmv up; Tomville will not answer it'
    else:
        try:
            with Path(executable).resolve().open('rb') as stream:
                first = stream.read(256).decode('utf-8', 'replace').split('\n')[0]
        except OSError:
            first = ''
        if 'node' in first or 'MainThread' in text or '"name":"node"' in text.replace(' ', ''):
            fix = f'tmv setup launcher {spec.kind} (script launcher hides the native process)'
        elif any(word in text.lower() for word in ('hash:', 'hashed', 'no such file')):
            fix = 'Shell remembers an old path; retry tmv up in a fresh pane'
        else:
            fix = f'herdr agent explain {pane or spec.name}'
    return {'detail': '\n'.join(facts) or f'{spec.name}: not running', 'fix': fix}


def first_prompt(spec, lead, specs, project):
    if spec.role == 'secretary':
        return f'Read the secretary section of AGENTS.md in {project}. Only {lead} sends you work. File issues when asked; email only {spec.email}. Wait for the lead’s nudge.'
    if spec.name == lead:
        roster = ', '.join(f'{a.name} ({a.role or "worker"})' for a in specs.values() if a.name != lead)
        return f'Read AGENTS.md in {project}. You lead this team: {roster}. Use tmv task for issues and tmv send for handoffs. Wait for the user’s goal.'
    return f'Read AGENTS.md. Your lead is {lead}. Work in your own worktree when assigned work; use tmv task and tmv send. Wait for the lead’s nudge.'


def make_place(project, spec, lead_pane):
    if spec.place == 'worktree':
        listing = run_command(['git', 'worktree', 'list', '--porcelain'], project)
        existing = None
        for block in listing.split('\n\n'):
            if f'branch refs/heads/{spec.worktree_branch}' in block.splitlines():
                existing = next(line[9:] for line in block.splitlines() if line.startswith('worktree '))
        args = ['worktree', 'open', '--path', existing] if existing else ['worktree', 'create', '--branch', spec.worktree_branch]
        result = herdr(project, *args, '--cwd', str(project), '--label', spec.name, '--no-focus')
    elif spec.place == 'pane':
        if not lead_pane:
            raise ValueError('cannot split a pane before the lead is available')
        result = herdr(project, 'pane', 'split', lead_pane, '--cwd', str(project), '--no-focus')
    else:  # a lead configured `here` starts in a tab when invoked in a shell
        result = herdr(project, 'tab', 'create', '--cwd', str(project), '--label', spec.name, '--no-focus')
    pane = result.get('root_pane') or result.get('pane')
    if not pane:
        # worktree create/open returns workspace_created nested under open_result
        opened = result.get('open_result', {})
        pane = opened.get('root_pane') or opened.get('pane')
    if not pane:
        raise ValueError(f'herdr did not return a pane: {result}')
    return {'pane': pane['pane_id'], 'terminal': pane.get('terminal_id'), 'place': spec.place, 'kind': spec.kind}


def up(project, settings):
    if os.environ.get('HERDR_ENV') != '1':
        raise ValueError('run tmv up inside herdr')
    if settings.team != 'lead' or not settings.agents:
        raise ValueError('tmv up needs a lead ville with [agents.*]; run tmv new')
    state = load_state(project)
    agents = herdr(project, 'agent', 'list')['agents']
    caller = next((a for a in agents if a['pane_id'] == os.environ.get('HERDR_PANE_ID')), None)
    lead = agent_name(caller) if caller else settings.lead
    lead_pane = caller['pane_id'] if caller else None
    lead_spec = state.get('lead_spec', settings.lead)
    if caller:
        state['lead_spec'] = lead_spec
        state['lead_pane'] = lead_pane
        save_state(project, state)
    if lead != settings.lead:
        from tomville.core.ville import update_ville, ville_path
        from tomville.core.settings import read_toml
        data = read_toml(ville_path(project)).get('team', {})
        update_ville(project, {'team': dict(data, lead=lead)})
    rows = []
    for name, spec in settings.agents.items():
        pane = None
        try:
            agents = herdr(project, 'agent', 'list')['agents']
            live = next((a for a in agents if agent_name(a) == name), None)
            if caller and name == lead_spec:
                rows.append(dict(agent=name, place='here', pane=lead_pane, result=f'lead: {lead}'))
                continue
            if not caller and name == lead_spec and lead != name:
                live = next((a for a in agents if agent_name(a) == lead), live)
            if live:
                if live.get('agent_status') == 'blocked' or not live.get('agent'):
                    pane = live['pane_id']
                    raise OSError('blocked at startup' if live.get('agent_status') == 'blocked' else 'agent not detected')
                if name in (lead, lead_spec):
                    lead_pane = live['pane_id']
                owned = state['agents'].get(name)
                if owned and owned['pane'] == live['pane_id'] and not owned.get('prompt_sent'):
                    run_command(['tmv', '-C', str(project), 'send', name, first_prompt(spec, lead, settings.agents, project)], project)
                    owned['prompt_sent'] = True
                    save_state(project, state)
                rows.append(dict(agent=name, place=spec.place, pane=live['pane_id'], result='already running'))
                continue
            owned = state['agents'].get(name)
            if owned:
                panes = herdr(project, 'pane', 'list')['panes']
                found = next((p for p in panes if p['pane_id'] == owned['pane'] and p.get('terminal_id') == owned['terminal']), None)
                if found:
                    raise OSError('previous startup is still in this pane; inspect it before retrying')
            if name == lead_spec and not caller:
                lead = name
            owned = make_place(project, spec, lead_pane)
            pane = owned['pane']
            state['agents'][name] = owned
            save_state(project, state)  # retain partial starts even if detection fails
            wait_shell(project, pane, settings.start_timeout)
            args = ['agent', 'start', name, '--kind', spec.kind, '--pane', pane, '--timeout', str(max(3001, int(settings.start_timeout * 1000)))]
            if spec.model:
                args += ['--', '--model', spec.model]
            herdr(project, *args, timeout=max(3.001, settings.start_timeout) + 10)
            agents = herdr(project, 'agent', 'list')['agents']
            detected = next((a for a in agents if agent_name(a) == name and a['pane_id'] == pane), None)
            if not detected or not detected.get('agent') or detected.get('agent_status') in ('blocked', 'unknown'):
                raise OSError('agent not detected or blocked at startup')
            if name == lead:
                lead_pane = pane
            run_command(['tmv', '-C', str(project), 'send', name, first_prompt(spec, lead, settings.agents, project)], project)
            owned['prompt_sent'] = True
            save_state(project, state)
            rows.append(dict(agent=name, place=spec.place, pane=pane, result='started'))
        except ERRORS as exc:
            pane = pane or state['agents'].get(name, {}).get('pane')
            diagnostic = detection(project, spec, pane, str(exc))
            rows.append(dict(agent=name, place=spec.place, pane=pane, result='FAILED', **diagnostic))
    try:
        tabs = herdr(project, 'tab', 'list')['tabs']
        office = state.get('office')
        panes = herdr(project, 'pane', 'list')['panes']
        external = next((p for p in panes if p.get('cwd') == str(project) and any(t['tab_id'] == p.get('tab_id') and t.get('label') == 'office' for t in tabs)), None)
        if not office and external:
            rows.append(dict(agent='office', place='tab', pane=external['pane_id'], result='already open'))
            return rows
        if not office or not any(p['pane_id'] == office['pane'] and p.get('terminal_id') == office['terminal'] for p in panes):
            result = herdr(project, 'tab', 'create', '--cwd', str(project), '--label', 'office', '--no-focus')
            pane = result['root_pane']
            state['office'] = {'tab': result['tab']['tab_id'], 'pane': pane['pane_id'], 'terminal': pane.get('terminal_id')}
            save_state(project, state)
        if not state['office'].get('launched'):
            wait_shell(project, state['office']['pane'], settings.start_timeout)
            herdr(project, 'pane', 'run', state['office']['pane'], shlex.join(['tmv', '-C', str(project)]))
            state['office']['launched'] = True
            save_state(project, state)
        rows.append(dict(agent='office', place='tab', pane=state['office']['pane'], result='open'))
    except ERRORS as exc:
        rows.append(dict(agent='office', place='tab', pane=None, result='FAILED', detail=str(exc)))
    return rows


def down(project, name=None):
    if os.environ.get('HERDR_ENV') != '1':
        raise ValueError('run tmv down inside herdr')
    state = load_state(project)
    panes = herdr(project, 'pane', 'list')['panes']
    agents = herdr(project, 'agent', 'list')['agents']
    rows = []
    targets = dict(state['agents'])
    if not name and state.get('office'):
        targets['office'] = state['office']
    for target, owned in targets.items():
        if name and target != name:
            continue
        pane = owned['pane']
        live = next((p for p in panes if p['pane_id'] == pane), None)
        try:
            if pane == os.environ.get('HERDR_PANE_ID') or pane == state.get('lead_pane'):
                rows.append(dict(agent=target, pane=pane, result='kept lead/caller pane'))
                continue
            if live and live.get('terminal_id') == owned.get('terminal'):
                agent = next((a for a in agents if a['pane_id'] == pane), None)
                occupant = agent_name(agent) if agent else None
                if agent is None and (live.get('agent') or live.get('agent_session')):
                    raise OSError('pane agent identity is unavailable; kept for inspection')
                if occupant and occupant != target:
                    raise OSError(f'pane now belongs to {occupant}; kept')
                if occupant:
                    if agent.get('agent_status') == 'blocked':
                        herdr(project, 'agent', 'send-keys', pane, 'ctrl+c')
                    elif owned.get('kind') in ('claude', 'codex'):
                        herdr(project, 'agent', 'prompt', pane, '/quit')
                    else:
                        herdr(project, 'agent', 'send-keys', pane, 'ctrl+c')
                    wait_shell(project, pane, 5)
                herdr(project, 'pane', 'close', pane)
            if target == 'office':
                state['office'] = None
            else:
                del state['agents'][target]
            save_state(project, state)
            rows.append(dict(agent=target, pane=pane, result='stopped'))
        except ERRORS as exc:
            rows.append(dict(agent=target, pane=pane, result='FAILED', detail=str(exc)))
    return rows
