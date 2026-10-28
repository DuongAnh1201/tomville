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
    (tmp_path / '.tomville').mkdir()
    (tmp_path / '.tomville/ville.toml').write_text('[docs]\nroots=["notes"]\n')
    (tmp_path / 'r.md').write_text('# R\n')
    assert main(['doc', 'read', 'r.md', *base]) == 2
