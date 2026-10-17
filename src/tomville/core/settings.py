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
    config = config or Path(os.environ.get('TOMVILLE_CONFIG', Path.home() / '.config/tomville/settings.toml'))
    data = {}
    for path in (config, project / '.tomville/ville.toml'):
        if path.exists():
            with path.open('rb') as stream:
                values = tomllib.load(stream)
            data.update({k: v for k, v in values.items() if k != 'board'})
            data.setdefault('board', {}).update(values.get('board', {}))
    board = data.get('board', {})
    return ReaderSettings(
        source=source or os.environ.get('TOMVILLE_BOARD', board.get('source', 'github')),
        repo=board.get('repo', ''),
        check_seconds=float(check_seconds if check_seconds is not None else os.environ.get('TOMVILLE_BOARD_CHECK', board.get('check_seconds', 60))),
        poll_seconds=float(poll_seconds if poll_seconds is not None else os.environ.get('TOMVILLE_POLL', data.get('poll_seconds', 1))),
    )
