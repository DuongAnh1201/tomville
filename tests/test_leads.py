"""Registry storage uses a temporary home, without herdr or Telegram."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from tomville.core import leads


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path/'home')


def test_private_atomic_registry_keeps_other_villes_and_replaces_old_pane(tmp_path):
    first, second = tmp_path/'first', tmp_path/'second'
    leads.register(first,'p1')
    leads.register(second,'p2')
    leads.registry_path().chmod(0o644)
    leads.register(first,'p3')
    assert leads.read() == {'p2':str(second),'p3':str(first)}
    assert leads.registry_path().stat().st_mode & 0o777 == 0o600
    leads.unregister(first)
    assert leads.read() == {'p2':str(second)}
    # An old ville cannot remove a pane that has since been adopted elsewhere.
    leads.register(first,'shared')
    leads.register(second,'shared')
    leads.unregister(first)
    assert leads.lookup('shared') == second
    assert not list(leads.registry_path().parent.glob('.leads-*'))


def test_parallel_registrations_do_not_lose_another_ville(tmp_path):
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(leads.register,tmp_path/str(i),f'p{i}') for i in range(2)]
        for job in jobs: job.result(timeout=3)
    assert leads.read() == {f'p{i}':str(tmp_path/str(i)) for i in range(2)}


@pytest.mark.parametrize('contents',['[]','{broken','{"p": "relative/path"}','{"p": null}'])
def test_invalid_registry_is_not_overwritten(tmp_path,contents):
    file = leads.registry_path(); file.parent.mkdir(parents=True)
    file.write_text(contents)
    with pytest.raises(ValueError): leads.register(tmp_path,'p')
    assert file.read_text() == contents
