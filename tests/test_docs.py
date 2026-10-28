import json
import os
import subprocess

import pytest

from tomville.cli import main
from tomville.core import docs

ROOTS = ('.', 'notes')

SAMPLE = """# Guide

Intro.

## Setup

### Linux
apt stuff

### Mac
brew stuff

## Usage

```
# not a heading
```

~~~md
## also not
~~~

### Linux
second linux

## Setup
again
"""


def test_headings_skip_fences_and_nest():
    paths = [h.path for h in docs.parse_headings(SAMPLE)]
    assert ('Guide', 'Setup', 'Linux') in paths
    assert not any('not a heading' in p[-1] or 'also not' in p[-1] for p in paths)
    guide = docs.parse_headings(SAMPLE)[0]
    assert guide.end == len(SAMPLE.splitlines())


def test_section_runs_to_next_same_or_higher_level():
    text = docs.section_text(SAMPLE, 'Guide > Setup > Mac')
    assert text.strip() == '### Mac\nbrew stuff'
    assert 'Linux' in docs.section_text(SAMPLE, 'Guide > Usage > Linux')
    usage = docs.section_text(SAMPLE, 'Usage')
    assert '# not a heading' in usage and 'second linux' in usage and 'again' not in usage


def test_duplicate_and_unknown_sections():
    with pytest.raises(docs.DocError, match='matches 2 headings'):
        docs.find_section(SAMPLE, 'Setup')
    with pytest.raises(docs.DocError, match='matches 2 headings'):
        docs.find_section(SAMPLE, 'Linux')
    with pytest.raises(docs.DocError, match='no section'):
        docs.find_section(SAMPLE, 'Nope')
    with pytest.raises(docs.DocError, match='bad section path'):
        docs.find_section(SAMPLE, 'A > ')


def test_version_tag_is_content_hash():
    assert docs.version_tag('a') == docs.version_tag(b'a') != docs.version_tag('b')
    assert len(docs.version_tag('a')) == 12


def test_safety_rules(tmp_path):
    root = tmp_path / 'proj'
    (root / 'notes').mkdir(parents=True)
    (root / 'a.md').write_text('# A\n')
    outside = tmp_path / 'out.md'
    outside.write_text('# Out\n')
    (root / 'link.md').symlink_to(outside)
    (root / 'txtlink.md').symlink_to(root / 'a.md')
    (root / 'a.txt').write_text('x')
    (root / '.git').mkdir()
    (root / '.git' / 'x.md').write_text('x')
    assert docs.resolve_doc(root, ROOTS, 'a.md') == (root / 'a.md').resolve()
    assert docs.resolve_doc(root, ROOTS, 'txtlink.md') == (root / 'a.md').resolve()
    for bad, message in [('a.txt', 'only .md'), ('../out.md', 'outside the project'),
                         (str(outside), 'outside the project'), ('link.md', 'symlink'),
                         ('.git/x.md', '.git'), ('missing.md', 'no such doc')]:
        with pytest.raises(docs.DocError, match=message):
            docs.resolve_doc(root, ROOTS, bad)
    with pytest.raises(docs.DocError, match='not under a docs root'):
        docs.resolve_doc(root, ('notes',), 'a.md')
    with pytest.raises(docs.DocError, match='outside the project'):
        docs.doc_roots(root, ('..',))


def test_new_refuses_existing_and_lists(tmp_path):
    result = docs.new_doc(tmp_path, ROOTS, 'notes/plan.md', 'The plan')
    assert (tmp_path / 'notes/plan.md').read_text() == '# The plan\n\n'
    with pytest.raises(docs.DocError, match='already exists'):
        docs.new_doc(tmp_path, ROOTS, 'notes/plan.md', 'Other')
    with pytest.raises(docs.DocError, match='only .md'):
        docs.new_doc(tmp_path, ROOTS, 'notes/plan.txt', 'x')
    rows = docs.list_docs(tmp_path, ROOTS)
    assert [(r['path'], r['title'], r['version']) for r in rows] == [('notes/plan.md', 'The plan', result['version'])]
    assert docs.list_docs(tmp_path, ROOTS, 'nothing') == []


def test_list_uses_git_editor(tmp_path):
    env = dict(os.environ, GIT_AUTHOR_NAME='Ada', GIT_AUTHOR_EMAIL='a@x', GIT_COMMITTER_NAME='Ada', GIT_COMMITTER_EMAIL='a@x')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    (tmp_path / 'a.md').write_text('# A\n')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'commit', '-qm', 'x'], cwd=tmp_path, check=True, env=env)
    (tmp_path / 'notes').mkdir()
    (tmp_path / 'notes/n.md').write_text('# N\n')
    assert docs.list_docs(tmp_path, ROOTS, '.')[0]['editor'] == 'Ada'
    rows = {r['path']: r for r in docs.list_docs(tmp_path, ROOTS, '.')}
    assert rows['a.md']['editor'] == 'Ada' and rows['notes/n.md']['editor'] == ''


def test_cli_doc(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path / 'user.toml'))
    base = ['-C', str(tmp_path), '--json']
    assert main(['doc', 'new', 'notes/x.md', '--title', 'X', *base]) == 0
    assert json.loads(capsys.readouterr().out)['path'] == 'notes/x.md'
    assert main(['doc', 'new', 'notes/x.md', '--title', 'X', *base]) == 2
    assert 'already exists' in json.loads(capsys.readouterr().out)['error']
    (tmp_path / 'notes/x.md').write_text(SAMPLE)
    assert main(['doc', 'read', 'notes/x.md', '--section', 'Guide > Setup > Mac', *base]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['text'].startswith('### Mac') and out['version'] == docs.version_tag(SAMPLE)
    assert main(['doc', 'read', 'notes/x.md', '--section', 'Setup', *base]) == 2
    capsys.readouterr()
    assert main(['doc', 'list', *base]) == 0
    assert json.loads(capsys.readouterr().out)[0]['title'] == 'Guide'
    assert main(['doc', 'read', '../etc.md', *base]) == 2
    (tmp_path / '.tomville').mkdir(exist_ok=True)
    (tmp_path / '.tomville/ville.toml').write_text('[docs]\nroots=["notes"]\n')
    (tmp_path / 'r.md').write_text('# R\n')
    assert main(['doc', 'read', 'r.md', *base]) == 2


# --- edit, merge, conflicts ---------------------------------------------------------

import multiprocessing

NOTE = """# Plan

## Alpha
a1
a2

## Beta
b1
b2

## Gamma
g1
"""


@pytest.fixture
def note(tmp_path):
    path = tmp_path / 'notes/plan.md'
    path.parent.mkdir()
    path.write_text(NOTE)
    return tmp_path, path, docs.version_tag(NOTE)


def edit(root, base, text, **kw):
    return docs.edit_doc(root, ROOTS, 'notes/plan.md', base, text, **kw)


def test_same_tag_writes(note):
    root, path, tag = note
    result = edit(root, tag, '## Beta\nnew b\n', section='Beta')
    assert path.read_text() == NOTE.replace('b1\nb2\n\n', 'new b\n\n')
    assert result['version'] == docs.version_tag(path.read_text()) and not result['merged']
    edit(root, result['version'], 'tail\n', mode='append')
    assert path.read_text().endswith('g1\ntail\n')


def test_append_to_section_goes_before_trailing_blank(note):
    root, path, tag = note
    edit(root, tag, 'a3', section='Alpha', mode='append')
    assert '## Alpha\na1\na2\na3\n\n## Beta' in path.read_text()


def test_replace_section_needs_its_heading(note):
    root, _, tag = note
    with pytest.raises(docs.DocError, match='heading line'):
        edit(root, tag, 'no heading\n', section='Beta')
    with pytest.raises(docs.DocError, match='empty'):
        edit(root, tag, '  \n')


def test_disjoint_concurrent_edits_merge(note):
    root, path, tag = note
    docs.read_doc(root, ROOTS, 'notes/plan.md')  # keeps the base object
    edit(root, tag, '## Alpha\nA!\n', section='Alpha')
    result = edit(root, tag, '## Gamma\nG!\n', section='Gamma')
    text = path.read_text()
    assert result['merged'] and not result['conflicted']
    assert 'A!' in text and 'G!' in text and 'a1' not in text and 'g1' not in text
    # adjacent sections replaced from the same base also merge
    edit(root, tag, 'x\n', section='Beta', mode='append')
    assert 'b2\nx\n' in path.read_text()


def test_same_lines_refused_with_other_change(note):
    root, path, tag = note
    docs.read_doc(root, ROOTS, 'notes/plan.md')
    edit(root, tag, '## Beta\ntheirs\n', section='Beta')
    before = path.read_text()
    with pytest.raises(docs.DocConflict) as caught:
        edit(root, tag, '## Beta\nours\n', section='Beta')
    assert path.read_text() == before
    assert '+theirs' in caught.value.diff and caught.value.version == docs.version_tag(before)
    assert not docs.is_conflicted(root, 'notes/plan.md')


def test_identical_changes_do_not_conflict(note):
    root, path, tag = note
    edit(root, tag, '## Beta\nsame\n', section='Beta')
    result = edit(root, tag, '## Beta\nsame\n', section='Beta')
    assert not result['conflicted'] and path.read_text().count('same') == 1


def test_merge_writes_markers_and_blocks_until_resolved(note):
    root, path, tag = note
    edit(root, tag, '## Beta\ntheirs\n', section='Beta')
    result = edit(root, tag, '## Beta\nours\n', section='Beta', merge=True)
    text = path.read_text()
    assert result['conflicted'] and result['conflicts'] == 1
    assert '## Beta\n<<<<<<< ours\nours\n=======\ntheirs\n>>>>>>> theirs\n\n## Gamma' in text
    assert docs.read_doc(root, ROOTS, 'notes/plan.md')['conflicted']
    with pytest.raises(docs.DocError, match='unresolved'):
        edit(root, docs.version_tag(text), 'x\n', mode='append')
    with pytest.raises(docs.DocError, match='still has conflict markers'):
        docs.resolve_doc_conflicts(root, ROOTS, 'notes/plan.md')
    path.write_text(NOTE.replace('b1\nb2', 'both'))
    done = docs.resolve_doc_conflicts(root, ROOTS, 'notes/plan.md')
    assert not done['conflicted'] and not docs.is_conflicted(root, 'notes/plan.md')
    with pytest.raises(docs.DocError, match='not marked'):
        docs.resolve_doc_conflicts(root, ROOTS, 'notes/plan.md')
    edit(root, done['version'], 'ok\n', mode='append')


def test_unknown_or_bad_base(note):
    root, path, tag = note
    path.write_text(NOTE + 'extra\n')
    with pytest.raises(docs.DocError, match='unknown version'):
        edit(root, 'abcdefabcdef', 'x\n', mode='append')
    with pytest.raises(docs.DocError, match='bad version tag'):
        edit(root, '../../etc', 'x\n', mode='append')


def test_tom_edits_in_an_editor(note):
    root, path, tag = note
    docs.read_doc(root, ROOTS, 'notes/plan.md')
    path.write_text(NOTE.replace('g1', 'g1 by Tom'))  # no lock, just a save
    edit(root, tag, '## Alpha\nA!\n', section='Alpha')
    assert 'g1 by Tom' in path.read_text() and 'A!' in path.read_text()


def _racer(args):
    root, tag, section = args
    docs.edit_doc(root, ROOTS, 'notes/plan.md', tag, f'## {section}\n{section} wrote\n', section=section)


def test_two_processes_racing_on_the_lock(note):
    root, path, tag = note
    docs.read_doc(root, ROOTS, 'notes/plan.md')
    with multiprocessing.get_context('fork').Pool(3) as pool:
        pool.map(_racer, [(root, tag, name) for name in ('Alpha', 'Beta', 'Gamma')])
    text = path.read_text()
    assert all(f'{name} wrote' in text for name in ('Alpha', 'Beta', 'Gamma'))
    assert not any(p.name.endswith('.tmp') or p.name.startswith('.plan') for p in path.parent.iterdir())


def test_merge3_unit():
    assert docs.merge3('a\nb\nc\n', 'A\nb\nc\n', 'a\nb\nC\n') == ('A\nb\nC\n', 0)
    text, n = docs.merge3('a\n', 'x\n', 'y\n')
    assert n == 1 and text == '<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n'


def test_cli_edit_and_resolve(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path / 'user.toml'))
    base = ['-C', str(tmp_path), '--json']
    (tmp_path / 'notes').mkdir()
    (tmp_path / 'notes/p.md').write_text(NOTE)
    assert main(['doc', 'read', 'notes/p.md', *base]) == 0
    tag = json.loads(capsys.readouterr().out)['version']

    def run(*argv, text):
        monkeypatch.setattr('sys.stdin', __import__('io').StringIO(text))
        code = main(['doc', *argv, *base])
        return code, json.loads(capsys.readouterr().out)

    assert run('edit', 'notes/p.md', '--base', tag, '--section', 'Beta', text='## Beta\ntheirs\n')[0] == 0
    code, out = run('edit', 'notes/p.md', '--base', tag, '--section', 'Beta', text='## Beta\nours\n')
    assert code == 3 and out['conflict'] and '+theirs' in out['diff']
    code, out = run('edit', 'notes/p.md', '--base', tag, '--section', 'Beta', '--merge', text='## Beta\nours\n')
    assert code == 0 and out['conflicted']
    code, out = run('edit', 'notes/p.md', '--base', out['version'], '--append', text='x\n')
    assert code == 2 and 'unresolved' in out['error']
    assert run('resolve', 'notes/p.md', text='')[0] == 2
    (tmp_path / 'notes/p.md').write_text(NOTE)
    assert run('resolve', 'notes/p.md', text='')[0] == 0


def test_project_docs_are_written_in_the_callers_worktree(tmp_path):
    main_repo = tmp_path / 'main'
    main_repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME='A', GIT_AUTHOR_EMAIL='a@x', GIT_COMMITTER_NAME='A', GIT_COMMITTER_EMAIL='a@x')
    run = lambda *a, cwd=main_repo: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, env=env)
    run('init', '-q', '-b', 'main')
    (main_repo / 'README.md').write_text('# R\n')
    run('add', '.')
    run('commit', '-qm', 'x')
    work = tmp_path / 'work'
    run('worktree', 'add', '-q', '-b', 'b', str(work))
    assert docs.locate(work, 'README.md') == (work.resolve(), main_repo.resolve())
    assert docs.locate(work, 'notes/x.md') == (main_repo.resolve(), main_repo.resolve())
    assert docs.locate(work, str(main_repo / 'notes/x.md'))[0] == main_repo.resolve()
