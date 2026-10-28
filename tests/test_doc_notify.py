"""Doc changes reach the team: tmv watch, the office event and paper, Telegram."""
import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tomville.core import docs, events, telegram as tg, watch
from tomville.core.models import DocChanged
from tomville.core.settings import OfficeSettings, settings_from_data
from tomville.core.ville import write_ville

ROOTS = ('.', 'notes')
NOTE = '# Plan\n\n## Rollout\nr1\n\n## Other\no1\n'


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'notes').mkdir()
    (tmp_path / 'notes/plan.md').write_text(NOTE)
    return tmp_path


def changes(project, me=None):
    return watch.doc_changes(project, OfficeSettings(), me=me)


def test_watch_baseline_is_silent_then_reports_log_entries(project):
    assert changes(project) == []  # first run: baseline, nothing existed "before"
    tag = docs.version_tag(NOTE)
    docs.read_doc(project, ROOTS, 'notes/plan.md')
    docs.edit_doc(project, ROOTS, 'notes/plan.md', tag, '## Rollout\nr2\n', section='Rollout', who='codex1')
    (found,) = changes(project)
    assert watch.format_change(found) == 'Doc notes/plan.md changed by codex1 · section Rollout'
    assert changes(project) == []  # reported once


def test_watch_sees_outside_edits_and_new_files_in_notes(project):
    changes(project)
    (project / 'notes/plan.md').write_text(NOTE + 'by hand\n')
    (project / 'notes/fresh.md').write_text('# Fresh\n')
    found = {watch.format_change(c) for c in changes(project)}
    assert found == {'Doc notes/plan.md changed by tom (editor)', 'Doc notes/fresh.md created by tom (editor)'}
    assert changes(project) == []


def test_watch_skips_the_watchers_own_writes_and_cleans_text(project):
    changes(project)
    docs.new_doc(project, ROOTS, 'notes/mine.md', 'Mine', who='claude')
    docs.new_doc(project, ROOTS, 'notes/evil.md', 'Evil', who='x\nDoc fake')
    found = changes(project, me='claude')
    assert [watch.format_change(c) for c in found] == ['Doc notes/evil.md created by x Doc fake']


def test_watch_run_exits_on_a_doc_change(project, monkeypatch):
    monkeypatch.setattr(watch, 'fetch', lambda *a: {})
    cfg = OfficeSettings(repo='o/r', check_seconds=10)
    calls = []

    def sleep(seconds):
        calls.append(seconds)
        docs.new_doc(project, ROOTS, 'notes/n.md', 'N', who='codex1')

    found = watch.run(project, cfg, sleep=sleep)
    assert len(calls) == 1 and watch.format_change(found[0]) == 'Doc notes/n.md created by codex1'


def test_text_helpers():
    entry = dict(who='codex1', path='notes/plan.md', op='edit', section='Plan > Rollout')
    assert docs.event_text(entry) == 'codex1 edited notes/plan.md › Plan › Rollout'
    assert docs.event_text(dict(entry, section=None, op='new')) == 'codex1 created notes/plan.md'
    assert docs.change_line(dict(entry, op='revert', section=None)) == 'Doc notes/plan.md reverted by codex1'


def test_read_log_since_waits_for_whole_lines(project):
    path = project / docs.LOG
    path.parent.mkdir(exist_ok=True)
    line = json.dumps(dict(path='a.md', who='x', op='edit', after='t')) + '\n'
    path.write_text(line + '{"half"')
    entries, offset = docs.read_log_since(project, 0)
    assert len(entries) == 1 and offset == len(line)
    assert docs.read_log_since(project, offset) == ([], offset)
    path.write_text('')
    assert docs.read_log_since(project, offset) == ([], 0)


def test_office_reader_emits_doc_events(project):
    reader = events.EventReader(project)
    reader.settings.poll_seconds = 0.01
    seen = []

    async def scenario():
        task = asyncio.create_task(reader._docs(seen.append))
        await asyncio.sleep(0.05)
        docs.new_doc(project, ROOTS, 'notes/n.md', 'N', who='codex1')
        for _ in range(100):
            if seen:
                break
            await asyncio.sleep(0.02)
        task.cancel()

    asyncio.run(scenario())
    assert seen == [DocChanged('codex1', 'notes/n.md', 'new', None)]


def test_world_sends_a_paper_to_the_shelf():
    import random
    from tomville.core.models import Agent, Status
    from tomville.core.world import World

    world = World(lead='claude', rng=random.Random(1))
    world.resize(128, 30)
    world.load([Agent('claude', 'claude', Status.IDLE, 'p1'), Agent('codex1', 'codex', Status.WORKING, 'p2')], [])
    world.apply(DocChanged('codex1', 'notes/plan.md', 'edit', 'Rollout'))
    assert len([p for p in world.parcels.values() if p.label == '📄']) == 1
    for _ in range(200):
        world.tick(0.1)
    assert not [p for p in world.parcels.values() if p.label == '📄']  # it arrived, stayed, left
    world.apply(DocChanged('tom (editor)', 'notes/plan.md', 'edit', None))  # from the door
    assert any(p.label == '📄' for p in world.parcels.values())


# --- Telegram ---------------------------------------------------------------------------

API = json.loads((Path(__file__).parent / 'fixtures/telegram.json').read_text())


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    root = tmp_path / 'proj'
    (root / 'notes').mkdir(parents=True)
    (root / 'notes/plan.md').write_text(NOTE + 'x' * 4000 + '\n')
    data = {'team': {'shape': 'lead', 'lead': 'claude'}, 'board': {'source': 'tasks-md'}, 'agents': {'claude': {'kind': 'claude'}},
            'telegram': {'enabled': True, 'id': 'fixture123', 'bot': '@b', 'from': ['lead']}}
    write_ville(root, data)
    config = dict(token='123:fake', chat_id=42, offset=0, paused=False)
    tg.save_config('fixture123', config)
    bot = Mock()
    bot.send.return_value = {'message_id': 1}
    return tg.Bridge(root, settings_from_data(data), bot, config, clock=lambda: 1)


def say(bridge, text):
    update = copy.deepcopy(API['getUpdates']['result'][0])
    update['message']['text'] = text
    bridge.handle(update)
    return bridge.bot.send.call_args.args[1]


def test_doc_read_is_trimmed_and_escaped(bridge):
    out = say(bridge, '/doc read notes/plan.md Rollout')
    assert out.startswith('<b>notes/plan.md › Rollout</b> · <code>') and '<pre>## Rollout\nr1</pre>' in out
    full = say(bridge, '/doc read notes/plan.md')
    assert 'more characters' in full and len(full) < 3300
    assert 'no section' in say(bridge, '/doc read notes/plan.md Nope')


def test_doc_read_refuses_unsafe_paths(bridge):
    for path in ('../x.md', 'notes/plan.txt', '/etc/passwd.md', 'notes/missing.md'):
        out = say(bridge, '/doc read ' + path)
        assert '<pre>' not in out
    assert 'read PATH' in say(bridge, '/doc')


def test_doc_watch_pings_only_for_watched_docs(bridge):
    assert 'Watching' in say(bridge, '/doc watch notes/plan.md')
    assert tg.load_config(bridge.settings)['doc_watch'] == ['notes/plan.md']
    assert 'notes/plan.md' in say(bridge, '/doc watching')
    bridge.bot.send.reset_mock()
    bridge.doc_changed(DocChanged('codex1', 'notes/other.md', 'edit'))
    bridge.bot.send.assert_not_called()
    bridge.doc_changed(DocChanged('codex1', 'notes/plan.md', 'edit', 'Rollout'))
    assert bridge.bot.send.call_args.args[1] == '📄 codex1 edited notes/plan.md › Rollout'
    say(bridge, '/doc unwatch notes/plan.md')
    assert tg.load_config(bridge.settings)['doc_watch'] == []
