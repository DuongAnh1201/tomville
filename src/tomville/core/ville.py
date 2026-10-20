"""Create and repair a ville: `tmv new` and `tmv setup`. No UI code here.

A ville is `.tomville/ville.toml` in the project, plus three things set up around
it: the GitHub board labels, the `tmv send` / `tmv task` rules in `CLAUDE.md` /
`AGENTS.md`, and the Claude Code hook that logs direct `herdr agent prompt` calls.
Every step is safe to run again.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from tomville.core.commands import run_command
from tomville.core.settings import read_toml, settings_from_data
from tomville.core.sprites import available_pets

MIN_CHECK_SECONDS = 10  # as in ReaderSettings
VILLE = Path('.tomville') / 'ville.toml'
RULES_START, RULES_END = '<!-- tomville:start -->', '<!-- tomville:end -->'
HOOK_COMMAND = 'd=$(cat); case "$d" in *"agent prompt"*) printf %s "$d" | tmv hook claude-pre-tool-use;; esac; exit 0'
HOOK_MARKER = 'tmv hook claude-pre-tool-use'
RULER = '|..|..|..|..|..|..|..|..|\n|🐱|🐶|🐑|🐸|🦊|🐼|🤖|👾|'
Ask = Callable[[str, str], str]  # (question, default) -> answer
KINDS = ('claude', 'codex', 'gemini', 'cursor', 'opencode', 'copilot', 'pi', 'amp', 'grok', 'qwen', 'kimi')  # a few `herdr agent start --kind` values
ANY_KIND = re.compile(r'[a-z][a-z0-9-]*')
PLACES = ('worktree', 'tab', 'pane')  # the lead is always `here`
SECRETARY_MODEL = 'claude-haiku-5-5'


def ville_path(project: Path) -> Path:
    return project / VILLE


def has_ville(project: Path) -> bool:
    return ville_path(project).exists()


@dataclass
class Answers:
    name: str
    shape: str = 'lead'
    lead: str = 'claude'
    workers: list[str] = field(default_factory=lambda: ['codex1', 'codex2'])  # pipeline: the stages
    pets: dict[str, str] = field(default_factory=dict)
    source: str = 'github'
    repo: str = ''
    check_seconds: float = 60
    watch: bool = False
    style: str = 'emoji'
    agent_specs: dict = field(default_factory=dict)  # lead shape: name -> [agents.NAME] table, in order
    secretary: str = ''  # name of the secretary in agent_specs, if any

    @property
    def agents(self) -> list[str]:
        return ([self.lead] if self.shape == 'lead' else []) + self.workers

    def data(self) -> dict:
        team: dict = {'shape': self.shape}
        if self.shape == 'lead':
            team['lead'] = self.lead
        else:
            team['stages'] = self.workers
        board: dict = {'source': self.source, 'check_seconds': self.check_seconds, 'watch': self.watch}
        if self.repo and self.source == 'github':
            board['repo'] = self.repo
        data = {
            'name': self.name,
            'style': self.style,
            'team': team,
            'board': board,
            'pets': {a: {'sprite': self.pets.get(a) or default_pet(i)} for i, a in enumerate(self.agents + ([self.secretary] if self.secretary else []))},
        }
        if self.agent_specs:
            data['agents'] = self.agent_specs
        return data


def default_pet(index: int) -> str:
    pets = available_pets()
    return pets[index % len(pets)]


def github_repo(project: Path) -> str:
    """`owner/repo` from the `origin` remote, or '' when there isn't one."""
    try:
        url = run_command(['git', 'remote', 'get-url', 'origin'], project)
    except (OSError, subprocess.SubprocessError):
        return ''
    match = re.search(r'github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$', url)
    return match.group(1) if match else ''


def names(text: str) -> list[str]:
    return [n for n in re.split(r'[,\s]+', text.strip()) if n]


def ask_answers(project: Path, name: str | None, ask: Ask) -> Answers:
    """The create-a-ville questions. `ask(question, default)` returns the answer."""
    a = Answers(name=ask('Name of the ville', name or project.name.replace('-', ' ').title() + ' ville'))
    a.shape = _choice(ask, 'Team shape (lead = boss + workers, pipeline = stages in a row)', 'lead', ('lead', 'pipeline'))
    if a.shape == 'lead':
        a.lead = ask('Boss agent', 'claude').strip() or 'claude'
        a.workers = names(ask('Worker agents (comma separated)', 'codex1,codex2')) or ['codex1']
        _ask_agents(project, a, ask)
    else:
        a.workers = names(ask('Pipeline stages in order (comma separated)', 'planner,coder,tester')) or ['planner']
    pets = available_pets()
    for i, agent in enumerate(a.agents + ([a.secretary] if a.secretary else [])):
        a.pets[agent] = _choice(ask, f'Pet for {agent} ({", ".join(pets)})', default_pet(i), tuple(pets))
    a.repo = github_repo(project)
    a.source = _choice(ask, 'Board (github = GitHub Issues, tasks-md = TASKS.md)', 'github' if a.repo else 'tasks-md', ('github', 'tasks-md'))
    if a.source == 'github':
        a.repo = ask('GitHub repository (owner/name, empty = this folder\'s)', a.repo).strip()
    a.check_seconds = _number(ask, 'Check the board every how many seconds', 60)
    if a.source == 'github':
        a.watch = _choice(ask, f'Should the lead check GitHub every {a.check_seconds:g} s for new issues, PRs, reviews and CI?', 'no', ('yes', 'no')) == 'yes'
    a.style = calibrate(ask)
    return a


def _ask_agents(project: Path, a: Answers, ask: Ask) -> None:
    """Kind, model and place per agent, then the optional secretary (lead shape)."""
    a.agent_specs[a.lead] = {'kind': _kind(ask, a.lead, 'claude'), 'model': _model(ask, a.lead), 'place': 'here'}
    for worker in a.workers:
        a.agent_specs[worker] = {
            'kind': _kind(ask, worker, 'codex'),
            'model': _model(ask, worker),
            'place': _choice(ask, f'Where does {worker} work (worktree = own git worktree, tab, pane)', 'worktree', PLACES),
        }
    if ask('Add a secretary (Claude Haiku) to file issues and email you when work is finished? (yes/no)', 'yes').strip().lower().startswith('y'):
        name = 'secretary'
        while name in a.agent_specs:
            name += '2'
        email = ask('Email address for the secretary', git_email(project)).strip()
        a.secretary = name
        a.agent_specs[name] = {'kind': 'claude', 'model': SECRETARY_MODEL, 'place': 'tab', 'role': 'secretary', **({'email': email} if email else {})}


def _kind(ask: Ask, agent: str, default: str) -> str:
    while True:
        value = ask(f'Kind of agent for {agent} ({", ".join(KINDS)}, or any kind herdr knows)', default).strip().lower() or default
        if ANY_KIND.fullmatch(value):
            return value
        print('  a kind is a lowercase word such as claude or codex')


def _model(ask: Ask, agent: str) -> str:
    return ask(f'Model for {agent} (empty = the CLI\'s default)', '').strip()


def git_email(project: Path) -> str:
    try:
        return run_command(['git', 'config', 'user.email'], project).strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def calibrate(ask: Ask, show: Callable[[str], None] = print) -> str:
    """The emoji test row: 'emoji' if the bars line up, else 'ascii'."""
    show(RULER)
    answer = ask('Do the bars line up (top row against the emoji row)? yes/no', 'yes').strip().lower()
    return 'emoji' if answer.startswith('y') else 'ascii'


def _choice(ask: Ask, question: str, default: str, choices: tuple[str, ...]) -> str:
    while True:
        value = ask(question, default).strip().lower() or default
        if value in choices:
            return value
        print(f'  choose one of: {", ".join(choices)}')


def _number(ask: Ask, question: str, default: float) -> float:
    while True:
        try:
            value = float(ask(question, f'{default:g}') or default)
        except ValueError:
            value = 0
        if value >= MIN_CHECK_SECONDS:
            return value
        print(f'  a number, at least {MIN_CHECK_SECONDS:g}')


def write_ville(project: Path, data: dict) -> Path:
    settings_from_data(data)  # never write a file that would not load
    path = ville_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(tomli_w.dumps(data), encoding='utf-8')
    tmp.replace(path)
    return path


def update_ville(project: Path, updates: dict) -> Path:
    """Change top-level keys of an existing ville (e.g. `style`, `theme`)."""
    data = read_toml(ville_path(project))
    data.update(updates)
    return write_ville(project, data)


def expected_agents(settings) -> set[str]:
    agents = set(settings.pets) | set(settings.stages) | set(getattr(settings, 'agents', None) or {})
    if settings.lead:
        agents.add(settings.lead)
    return agents


def ensure_labels(project: Path, settings) -> list[str]:
    """Create the board labels that are missing; returns the ones it created."""
    if settings.source != 'github':
        return []
    base = ['--repo', settings.repo] if settings.repo else []
    listing = json.loads(run_command(['gh', 'label', 'list', '--limit', '1000', '--json', 'name', *base], project))
    have = {label['name'] for label in listing}
    wanted = [(f'status:{c}', 'c5def5', f'Board: {c}') for c in ('todo', 'doing', 'review')]
    wanted += [(f'agent:{n}', 'f5a97f', f'Work for {n}') for n in sorted(expected_agents(settings))]
    created = []
    for label, color, description in wanted:
        if label not in have:
            run_command(['gh', 'label', 'create', label, '--color', color, '--description', description, *base], project)
            created.append(label)
    return created


def rules_text(settings) -> str:
    lines = [
        '## Tomville',
        '',
        'This project runs as a Tomville team office. The rules for agents:',
        '',
        '- To prompt another agent, run `tmv send AGENT "text"`, not `herdr agent prompt`: it logs who sent the message.',
    ]
    if settings.source == 'github' and settings.watch:
        lines += [
            '- Lead only: keep `tmv watch` running in the background at all times. It polls every `[board] check_seconds` and exits on changes; handle them and restart it.',
            '- Lead only: team PR → check conflicts, review/test and merge when ready; outside/fork/unverified PR → review and report to Tom via Telegram/email, never merge without Tom’s approval; new issue → label and assign, or ask Tom.',
        ]
    if settings.source == 'github':
        lines += [
            '- Work items are GitHub issues. Use `tmv task new "title"`, `tmv task take N`, `tmv task move N review` and `tmv task list` instead of long `gh` commands.',
        ]
    else:
        lines += ['- Work items are rows in `TASKS.md`; keep each row\'s status column up to date.']
    return '\n'.join([RULES_START, *lines, RULES_END, ''])


def install_rules(project: Path, settings) -> list[Path]:
    """Add (or refresh) the Tomville rules in CLAUDE.md and AGENTS.md.

    Edits the files that exist; with neither, creates AGENTS.md.
    """
    targets = [p for p in (project / 'CLAUDE.md', project / 'AGENTS.md') if p.exists()] or [project / 'AGENTS.md']
    block = rules_text(settings)
    pattern = re.compile(re.escape(RULES_START) + r'.*?' + re.escape(RULES_END) + r'\n?', re.DOTALL)
    changed = []
    for path in targets:
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        if pattern.search(text):
            new = pattern.sub(lambda _: block, text)
        else:
            new = text + ('' if not text or text.endswith('\n\n') else '\n' if text.endswith('\n') else '\n\n') + block
        if new != text:
            path.write_text(new, encoding='utf-8')
            changed.append(path)
    return changed


def claude_settings_path() -> Path:
    return Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home() / '.claude')).expanduser() / 'settings.json'


def install_hook(path: Path) -> str:
    """Install message logging and lead Telegram hooks, preserving other hooks."""
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
        raise ValueError(f'{path} does not look like Claude Code settings')
    before = json.dumps(data, sort_keys=True)
    definitions = [('PreToolUse', 'Bash', HOOK_MARKER, HOOK_COMMAND, 10),
                   ('PreToolUse', 'AskUserQuestion', 'tmv hook ask-user-question', 'tmv hook ask-user-question', 660),
                   ('PermissionRequest', '*', 'tmv hook permission-request', 'tmv hook permission-request', 660),
                   ('PermissionDenied', '*', 'tmv hook permission-denied', 'tmv hook permission-denied', 10),
                   ('Stop', None, 'tmv hook stop', 'tmv hook stop', 10)]
    owned = any(marker in before for _, _, marker, _, _ in definitions)
    for event, matcher, marker, command, timeout in definitions:
        entries = data.setdefault('hooks', {}).setdefault(event, [])
        hook = {'type': 'command', 'command': command, 'timeout': timeout}
        for entry in entries:
            for existing in entry.get('hooks', []):
                if marker in existing.get('command', ''):
                    existing.clear()
                    existing.update(hook)
                    if matcher is None:
                        entry.pop('matcher', None)
                    else:
                        entry['matcher'] = matcher
                    break
            else:
                continue
            break
        else:
            entries.append(dict(hooks=[hook], **({'matcher': matcher} if matcher is not None else {})))
    if json.dumps(data, sort_keys=True) == before:
        return 'unchanged'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)
    return 'updated' if owned else 'added'


STEPS = ('labels', 'rules', 'hook')


def run_steps(project: Path, settings, steps, claude_settings: Path, say: Callable[[str], None] = print) -> int:
    """Run setup steps, one line each; returns how many failed. A failure doesn't stop the rest."""
    failed = 0
    for step in steps:
        try:
            if step == 'labels':
                created = ensure_labels(project, settings)
                say('labels: ' + (f'created {", ".join(created)}' if created else 'ready' if settings.source == 'github' else 'not needed (TASKS.md board)'))
            elif step == 'rules':
                changed = install_rules(project, settings)
                say('rules: ' + (f'written to {", ".join(p.name for p in changed)}' if changed else 'already there'))
            elif step == 'hook':
                say(f'hook: {install_hook(claude_settings)} in {claude_settings}')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            failed += 1
            say(f'{step}: FAILED: {exc}')
    return failed
