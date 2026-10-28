"""Settings needed by the M2 data reader; CLI values override TOML and env."""
from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


@dataclass
class ReaderSettings:
    source: str = 'github'
    repo: str = ''
    check_seconds: float = 60
    poll_seconds: float = 1

    def __post_init__(self):
        if not 10 <= self.check_seconds < float('inf'):
            raise ValueError('board check interval must be at least 10 seconds')
        if not 0 < self.poll_seconds < float('inf'):
            raise ValueError('poll interval must be positive')


def load_reader_settings(project, *, config=None, source=None, check_seconds=None, poll_seconds=None):
    return load_settings(project, config=config, source=source, check_seconds=check_seconds, poll_seconds=poll_seconds)


PLACES = ('here', 'worktree', 'tab', 'pane')
ROLES = ('', 'secretary')
DEFAULT_START_TIMEOUT = 120.0  # seconds; agents start slowly under PRoot


@dataclass(frozen=True)
class AgentSpec:
    """One `[agents.NAME]` table: what `tmv up` starts and where."""

    name: str
    kind: str
    model: str = ''  # empty: the CLI's own default
    place: str = 'worktree'
    branch: str = ''  # worktree branch; empty: the agent's name
    role: str = ''
    email: str = ''  # secretary: the only address it sends to

    def __post_init__(self):
        for key in ('kind', 'model', 'branch', 'role', 'email'):
            if not isinstance(getattr(self, key), str):
                raise ValueError(f'agents.{self.name}.{key} must be text')
        if not self.kind:
            raise ValueError(f'agents.{self.name}.kind is missing')
        if self.place not in PLACES:
            raise ValueError(f'agents.{self.name}.place must be one of {PLACES}')
        if self.role not in ROLES:
            raise ValueError(f'agents.{self.name}.role must be one of {ROLES}')

    @property
    def worktree_branch(self) -> str:
        return self.branch or self.name


def agent_specs(table):
    if not isinstance(table, dict) or any(not isinstance(v, dict) for v in table.values()):
        raise ValueError('agents must contain one table per agent')
    known = {'kind', 'model', 'place', 'branch', 'role', 'email'}
    for name, spec in table.items():
        if unknown := set(spec) - known:
            raise ValueError(f'agents.{name}: unknown key {sorted(unknown)[0]}')
    return {name: AgentSpec(name=name, **spec) for name, spec in table.items()}


def telegram_settings(table):
    known = {'enabled', 'bot', 'id', 'approvals', 'from'}
    if not isinstance(table, dict) or set(table) - known:
        raise ValueError('telegram allows only enabled, bot, id, approvals and from; no secrets')
    for key in ('enabled', 'approvals'):
        if not isinstance(table.get(key, False), bool):
            raise ValueError(f'telegram.{key} must be a boolean')
    for key in ('bot', 'id'):
        if not isinstance(table.get(key, ''), str):
            raise ValueError(f'telegram.{key} must be text')
    import re
    if table.get('id') and not re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', table['id']):
        raise ValueError('telegram.id must be an opaque ville ID')
    allowed = table.get('from', ['secretary', 'lead'])
    if not isinstance(allowed, list) or any(not isinstance(a, str) for a in allowed):
        raise ValueError('telegram.from must be an array of agent names')
    return dict(enabled=False, bot='', id='', approvals=False) | table | {'from': allowed}


@dataclass
class OfficeSettings(ReaderSettings):
    name: str = ''
    watch: bool = False
    fps: int = 10
    style: str = 'emoji'
    theme: str = 'night'
    layout: str = 'auto'
    team: str = 'lead'
    lead: str | None = None
    stages: tuple[str, ...] = ()
    pets: dict = None
    demo: bool = False
    still: bool = False
    agents: dict = None  # name -> AgentSpec, in ville order
    telegram: dict = None
    docs_roots: tuple[str, ...] = ('.', 'notes')
    docs_keep: int = 50
    start_timeout: float = DEFAULT_START_TIMEOUT

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.watch, bool):
            raise ValueError('board.watch must be a boolean')
        self.pets = self.pets or {}
        self.agents = self.agents or {}
        self.telegram = telegram_settings(self.telegram or {})
        if isinstance(self.start_timeout, bool) or not 0 < self.start_timeout <= 300:
            raise ValueError('start_timeout must be between 0 and 300 seconds')
        for key, choices in {'fps': (5, 10, 15, 30), 'style': ('emoji', 'ascii', 'blocks'), 'theme': ('night', 'game-boy', 'green-screen'), 'layout': ('auto', 'landscape', 'portrait'), 'team': ('lead', 'pipeline')}.items():
            if getattr(self, key) not in choices:
                raise ValueError(f'{key} must be one of {choices}')
        if isinstance(self.fps, bool) or not isinstance(self.fps, int):
            raise ValueError('fps must be an integer')
        if not isinstance(self.demo, bool) or not isinstance(self.still, bool):
            raise ValueError('demo and still must be booleans')
        if not isinstance(self.pets, dict) or any(not isinstance(v, dict) or not isinstance(v.get('sprite', ''), str) for v in self.pets.values()):
            raise ValueError('pets must contain tables with sprite names')


def config_path(config=None):
    return Path(config or os.environ.get('TOMVILLE_CONFIG', Path.home() / '.config/tomville/settings.toml')).expanduser()


def read_toml(path):
    if not path.exists():
        return {}
    with path.open('rb') as stream:
        return tomllib.load(stream)


def merge_settings(base, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_settings(base[key], value)
        else:
            base[key] = value
    return base


def settings_from_data(data):
    for key in ('board', 'team', 'pets', 'agents', 'telegram', 'docs'):
        if not isinstance(data.get(key, {}), dict):
            raise ValueError(f'{key} must be a TOML table')
    board = data.get('board', {})
    team = data.get('team', {})
    if not isinstance(board.get('source', 'github'), str) or not isinstance(board.get('repo', ''), str):
        raise ValueError('board source and repo must be strings')
    if not isinstance(team.get('stages', []), list) or any(not isinstance(s, str) for s in team.get('stages', [])):
        raise ValueError('team.stages must be an array of names')
    if team.get('lead') is not None and not isinstance(team['lead'], str):
        raise ValueError('team.lead must be a name')
    if not isinstance(data.get('name', ''), str):
        raise ValueError('name must be text')
    docs = data.get('docs', {})
    roots = docs.get('roots', ['.', 'notes'])
    keep = docs.get('keep_versions', 50)
    if set(docs) - {'roots', 'keep_versions'} or not isinstance(roots, list) or not roots or any(not isinstance(r, str) or not r for r in roots):
        raise ValueError('docs allows only roots (a non-empty array of folders) and keep_versions')
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        raise ValueError('docs.keep_versions must be a whole number, at least 1')
    return OfficeSettings(
        name=data.get('name', ''), watch=board.get('watch', False), source=board.get('source', 'github'), repo=board.get('repo', ''),
        check_seconds=float(board.get('check_seconds', 60)), poll_seconds=float(data.get('poll_seconds', 1)),
        fps=data.get('fps', 10), style=data.get('style', 'emoji'), theme=data.get('theme', 'night'),
        layout=data.get('layout', 'auto'), team=team.get('shape', 'lead'), lead=team.get('lead'),
        stages=tuple(team.get('stages', [])), pets=data.get('pets', {}),
        demo=data.get('demo', False), still=data.get('still', False),
        docs_roots=tuple(roots), docs_keep=keep, telegram=data.get('telegram', {}), agents=agent_specs(data.get('agents', {})), start_timeout=float(data.get('start_timeout', DEFAULT_START_TIMEOUT)),
    )


def load_settings(project, *, config=None, **overrides):
    # Project settings are the ville's defaults; env and CLI always win.
    user_data = read_toml(config_path(config))
    telegram_settings(user_data.get('telegram', {}))  # reject secrets even in a masked table
    project_data = read_toml(project / '.tomville/ville.toml')
    data = merge_settings(user_data, project_data)
    data['telegram'] = project_data.get('telegram', {})  # links belong to this ville only
    paths = {'source': 'board.source', 'repo': 'board.repo', 'check_seconds': 'board.check_seconds', 'poll_seconds': 'poll_seconds', 'team': 'team.shape', 'lead': 'team.lead'}
    env_names = {'source': 'BOARD', 'check_seconds': 'BOARD_CHECK', 'poll_seconds': 'POLL'}
    for key in ('source', 'repo', 'check_seconds', 'poll_seconds', 'fps', 'style', 'theme', 'layout', 'team', 'lead', 'demo', 'still'):
        value = os.environ.get('TOMVILLE_' + env_names.get(key, key.upper()))
        if overrides.get(key) is not None:
            value = overrides[key]
        if value is None:
            continue
        if key == 'fps':
            value = int(value)
        if key in ('demo', 'still') and isinstance(value, str):
            if value.lower() not in ('true', 'false', '1', '0'):
                raise ValueError(f'{key} must be true or false')
            value = value.lower() in ('true', '1')
        set_key(data, paths.get(key, key), value)
    for assignment in overrides.get('pets') or []:
        name, separator, sprite = assignment.partition('=')
        if not separator or not name or not sprite:
            raise ValueError('--pet must be AGENT=PET')
        data.setdefault('pets', {}).setdefault(name, {})['sprite'] = sprite
    return settings_from_data(data)


def set_key(data, key, value):
    parts = key.split('.')
    if any(not p for p in parts):
        raise ValueError('setting keys must use nonempty dotted names')
    for part in parts[:-1]:
        data = data.setdefault(part, {})
        if not isinstance(data, dict):
            raise ValueError(f'{part} is not a settings table')
    data[parts[-1]] = value


def write_config_value(path, key, text):
    import tomli_w

    known = {'fps', 'style', 'theme', 'layout', 'poll_seconds', 'demo', 'still', 'start_timeout', 'board.source', 'board.repo', 'board.check_seconds', 'board.watch', 'team.shape', 'team.lead', 'team.stages', 'docs.roots', 'docs.keep_versions'}
    pet_key = key.startswith('pets.') and len(key.split('.')) == 3 and key.split('.')[-1] in ('sprite', 'color')
    if key not in known and not pet_key:
        raise ValueError(f'unknown setting: {key}')
    try:
        value = tomllib.loads('value = ' + text)['value']
    except tomllib.TOMLDecodeError:
        value = text
    data = read_toml(path)
    set_key(data, key, value)
    settings_from_data(data)  # Validate the file itself, without env masking errors.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(tomli_w.dumps(data))
    temporary.replace(path)
    return value
