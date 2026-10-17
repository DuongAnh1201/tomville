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


@dataclass
class OfficeSettings(ReaderSettings):
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

    def __post_init__(self):
        super().__post_init__()
        self.pets = self.pets or {}
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
    for key in ('board', 'team', 'pets'):
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
    return OfficeSettings(
        source=board.get('source', 'github'), repo=board.get('repo', ''),
        check_seconds=float(board.get('check_seconds', 60)), poll_seconds=float(data.get('poll_seconds', 1)),
        fps=data.get('fps', 10), style=data.get('style', 'emoji'), theme=data.get('theme', 'night'),
        layout=data.get('layout', 'auto'), team=team.get('shape', 'lead'), lead=team.get('lead'),
        stages=tuple(team.get('stages', [])), pets=data.get('pets', {}),
        demo=data.get('demo', False), still=data.get('still', False),
    )


def load_settings(project, *, config=None, **overrides):
    # Project settings are the ville's defaults; env and CLI always win.
    data = merge_settings(read_toml(config_path(config)), read_toml(project / '.tomville/ville.toml'))
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

    known = {'fps', 'style', 'theme', 'layout', 'poll_seconds', 'demo', 'still', 'board.source', 'board.repo', 'board.check_seconds', 'team.shape', 'team.lead', 'team.stages'}
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
