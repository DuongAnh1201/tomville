from pathlib import Path

import pytest

from tomville.core import settings


REPO_ROOT = Path(__file__).parents[1].resolve()
REPO_VILLE = REPO_ROOT / '.tomville' / 'ville.toml'


@pytest.fixture(autouse=True)
def reject_repo_ville(monkeypatch):
    """Tests must provide their own project instead of using the live ville."""
    read_toml = settings.read_toml

    def guarded_read_toml(path):
        if Path(path).resolve() == REPO_VILLE:
            pytest.fail(
                'test read the checkout\'s .tomville/ville.toml; '
                'use tmp_path and pass it as the project with -C'
            )
        return read_toml(path)

    monkeypatch.setattr(settings, 'read_toml', guarded_read_toml)
