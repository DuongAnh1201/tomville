"""Formatting tests use recorded PR #67 output, never GitHub or Telegram I/O."""
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tomville.cli import build_parser, main
from tomville.core import telegram, telegram_text as text
from tomville.core.settings import settings_from_data

FIXTURES = Path(__file__).parent / 'fixtures'
DIFF = json.loads((FIXTURES / 'github_pr67.diff.json').read_text())
META = json.loads((FIXTURES / 'github_pr67.json').read_text())


class InspectHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.blocks, self.data = [], [], ''
    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        if tag == 'pre':
            self.blocks.append('')
    def handle_endtag(self, tag):
        assert self.stack.pop() == tag
    def handle_data(self, value):
        self.data += value
        if 'pre' in self.stack:
            self.blocks[-1] += value


def inspect(parts, size=4096):
    blocks = []
    for part in parts:
        assert text.units(part) <= size and len(part) <= size
        parser = InspectHTML()
        parser.feed(part)
        parser.close()
        assert not parser.stack
        blocks.extend(parser.blocks)
    return blocks


@pytest.mark.parametrize('language', ['python', 'toml', 'bash', 'diff', 'c++', 'c#'])
def test_code_blocks_escape_content_and_keep_language(language):
    source = 'if a < b and x & y:\n    print("<script>hi</script>")\n'
    message = f'<pre><code class="language-{language}">{source}</code></pre>'
    parts = text.chunks(message)
    assert len(parts) == 1
    assert f'class="language-{language}"' in parts[0]
    assert '&lt;script&gt;' in parts[0] and '&amp;' in parts[0]
    assert inspect(parts) == [source]
    assert text.chunks('<code>a &lt; b &amp; c</code>') == ['<code>a &lt; b &amp; c</code>']


@pytest.mark.parametrize('markup', [
    '<a href="https://example.com">link</a>', '<script>x</script>', '<u>x</u>',
    '<b onclick="x">x</b>', '<code class="language-python">x</code>',
    '<pre><code class="bad">x</code></pre>',
    '<pre><code class="language-python other">x</code></pre>',
    '<pre><code class="language-python" onclick="x">x</code></pre>',
    '<pre><code class="language-\" onclick=\"x">x</code></pre>',
    '<b><code>x</code></b>', '<pre><code>x</pre>', '<pre>x', '<code>x',
    '<!-- hidden -->', '<!DOCTYPE html>', '<?xml version="1.0"?>', '<br/>',
    '<b>&nbsp;</b>', '&#xD800;', '&#0;',
])
def test_allowlist_rejects_other_markup(markup):
    with pytest.raises(ValueError):
        text.chunks(markup)


def test_long_code_blocks_split_at_lines_and_reopen_language():
    source = ''.join(f'+line {n}: a < b && c > d\n' for n in range(200))
    parts = text.chunks('<pre><code class="language-diff">' + escape(source) + '</code></pre>', 400)
    assert len(parts) > 2
    assert all(p.startswith(text.CODE_OPEN) and p.endswith(text.CODE_CLOSE) for p in parts)
    blocks = inspect(parts, 400)
    assert ''.join(blocks) == source
    assert all(block.endswith('\n') for block in blocks)
    # A single line larger than a message cannot defeat the hard bound.
    source = '+' + '🐱<&' * 1000
    parts = text.chunks(text.CODE_OPEN + escape(source) + text.CODE_CLOSE, 400)
    assert ''.join(inspect(parts, 400)) == source


def test_short_code_block_moves_whole_to_the_next_message():
    block = '<pre><code class="language-python">print(1)</code></pre>'
    parts = text.chunks('x' * 80 + block, 100)
    assert parts == ['x' * 80, block]


def test_recorded_diff_headers_counts_and_noise():
    files = text.parse_diff(DIFF)
    assert [f.path for f in files] == ['src/tomville/core/events.py', 'tests/test_events.py']
    assert sum(f.added for f in files) == META['additions']
    assert sum(f.removed for f in files) == META['deletions']
    parts = text.diff_messages(DIFF, 'PR #67 · cancellation fix')
    inspect(parts)
    combined = '\n'.join(parts)
    assert '📄 <code>src/tomville/core/events.py</code>' in combined
    assert f'(+{files[0].added} −{files[0].removed})' in combined
    assert 'diff --git' not in combined and '\nindex ' not in combined
    assert '@@ ' in combined
    expected = ''.join(''.join(f.preamble) + ''.join(f.hunks) for f in files)
    assert ''.join(inspect(parts)) == expected


def test_file_then_hunk_boundaries_take_priority():
    diff = ('diff --git a/one.py b/one.py\n--- a/one.py\n+++ b/one.py\n'
            '@@ -1 +1 @@\n-old one\n+new one\n'
            '@@ -10 +10 @@\n-old two\n+new two\n'
            'diff --git a/two.py b/two.py\n--- a/two.py\n+++ b/two.py\n'
            '@@ -1 +1 @@\n-old other\n+new other\n')
    parts = text.diff_messages(diff, 'PR #1', size=260)
    blocks = inspect(parts, 260)
    assert len(parts) >= 2
    assert all(not ('one.py</code>' in p and 'two.py</code>' in p) for p in parts)
    # Every hunk that fits is whole inside one block.
    assert any('@@ -1 +1 @@\n-old one\n+new one\n' in b for b in blocks)
    assert any('@@ -10 +10 @@\n-old two\n+new two\n' in b for b in blocks)


def test_large_recorded_diff_preserves_blocks_and_all_hunks():
    parts = text.diff_messages(DIFF, 'PR #67', prefix='🐱 <code>claude</code>: ', size=512)
    assert len(parts) > 5
    blocks = inspect(parts, 512)
    expected = ''.join(''.join(f.preamble) + ''.join(f.hunks) for f in text.parse_diff(DIFF))
    assert ''.join(blocks) == expected
    assert all('📄 <code>' in part for part in parts)
    assert all('class="language-diff"' in part for part in parts)


def test_diff_paths_source_and_metadata_are_escaped(monkeypatch, tmp_path):
    diff = 'diff --git a/x b/x\n--- a/x\n+++ b/<x>&.py\n@@ -1 +1 @@\n-<a>\n+<b>&amp;\n'
    parts = text.diff_messages(diff, 'PR #1')
    assert '&lt;x&gt;&amp;.py' in parts[0]
    assert inspect(parts) == ['--- a/x\n+++ b/<x>&.py\n@@ -1 +1 @@\n-<a>\n+<b>&amp;\n']
    responses = iter([json.dumps(dict(META, title='<Fix> & test', author={'login': 'a<b'})), DIFF])
    calls = []
    def run(args, project):
        calls.append(args)
        return next(responses)
    monkeypatch.setattr(text, 'run_command', run)
    headline, _ = text.pr_diff(tmp_path, 67, 'owner/repo')
    assert '&lt;Fix&gt; &amp; test' in headline and 'a&lt;b' in headline
    assert '#67' in headline and f'(+{META["additions"]} −{META["deletions"]})' in headline
    assert all(args[-2:] == ['--repo', 'owner/repo'] for args in calls)
    assert calls[1][:4] == ['gh', 'pr', 'diff', '67']


def test_deleted_renamed_quoted_and_binary_files():
    diff = ('diff --git a/deleted b/deleted\ndeleted file mode 100644\nindex 123..456\n--- a/deleted\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n'
            'diff --git a/old b/new\nsimilarity index 100%\nrename from old\nrename to new\n'
            'diff --git "a/sp ace" "b/sp ace"\n--- "a/sp ace"\n+++ "b/sp ace"\n@@ -0,0 +1 @@\n+new\n'
            'diff --git a/icon.png b/icon.png\nindex 123..456\nBinary files a/icon.png and b/icon.png differ\n')
    files = text.parse_diff(diff)
    assert [f.path for f in files] == ['deleted', 'new', 'sp ace', 'icon.png']
    assert (files[0].added, files[0].removed) == (0, 1)
    assert 'Binary files' in ''.join(text.diff_messages(diff, 'Saved diff'))


def test_invalid_or_unrepresentable_diff_fails_before_sending():
    with pytest.raises(ValueError, match='expected a git unified diff'):
        text.diff_messages('not a diff', 'Saved diff')
    with pytest.raises(ValueError, match='title is too long'):
        text.diff_messages(DIFF, 'x' * 4096)
    assert 'No changes.' in text.diff_messages('', 'PR #1')[0]


@pytest.fixture
def reply_runtime(tmp_path, monkeypatch):
    settings = settings_from_data({'team': {'lead': 'claude'}, 'telegram': {'enabled': True, 'from': ['lead']}})
    monkeypatch.setattr(telegram.messages, 'sender_name', lambda: 'claude')
    monkeypatch.setattr(telegram, 'load_config', lambda s: {'token': '123:fake', 'chat_id': 42})
    bot = Mock()
    return tmp_path, settings, bot


def test_reply_pr_diff_builds_messages_and_logs_once(reply_runtime, monkeypatch):
    project, settings, bot = reply_runtime
    replies = iter([json.dumps(META), DIFF])
    monkeypatch.setattr(text, 'run_command', lambda *a: next(replies))
    telegram.reply(project, settings, diff=67, bot_factory=lambda t: bot)
    payloads = [c.args[1] for c in bot.send.call_args_list]
    inspect(payloads)
    assert all(c.args[0] == 42 for c in bot.send.call_args_list)
    assert 'PR #67' in payloads[0] and META['title'] in payloads[0]
    records = (project / '.tomville/messages.jsonl').read_text().splitlines()
    assert len(records) == 1
    record = json.loads(records[0])
    assert record['from'] == 'claude' and record['to'] == 'tom' and DIFF in record['text']


def test_reply_saved_diff_and_normal_html(reply_runtime):
    project, settings, bot = reply_runtime
    (project / 'saved.diff').write_text(DIFF)
    telegram.reply(project, settings, diff_file=Path('saved.diff'), bot_factory=lambda t: bot)
    assert 'Saved diff: <code>saved.diff</code>' in bot.send.call_args_list[0].args[1]
    bot.reset_mock()
    telegram.reply(project, settings, 'Use <code>uv run pytest</code>', bot_factory=lambda t: bot)
    assert '<code>uv run pytest</code>' in bot.send.call_args.args[1]


def test_unauthorized_or_invalid_reply_never_fetches_or_posts(reply_runtime, monkeypatch):
    project, settings, bot = reply_runtime
    fetch = Mock(side_effect=AssertionError('must not fetch'))
    monkeypatch.setattr(text, 'run_command', fetch)
    monkeypatch.setattr(telegram.messages, 'sender_name', lambda: 'worker')
    with pytest.raises(ValueError, match='not allowed'):
        telegram.reply(project, settings, diff=67, bot_factory=lambda t: bot)
    monkeypatch.setattr(telegram.messages, 'sender_name', lambda: 'claude')
    with pytest.raises(ValueError):
        telegram.reply(project, settings, 'hello', diff=67, bot_factory=lambda t: bot)
    with pytest.raises(ValueError):
        telegram.reply(project, settings, 'hello <a href="x">bad</a>', bot_factory=lambda t: bot)
    bot.send.assert_not_called()


@pytest.mark.parametrize('args', [[], ['--diff', '0'], ['hello', '--diff', '67'], ['--diff', '67', '--diff-file', 'x']])
def test_reply_cli_rejects_missing_or_conflicting_sources(args):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(['reply', *args])
    assert exc.value.code == 2


def test_reply_cli_resolves_saved_file_from_worktree(tmp_path, monkeypatch):
    project = tmp_path / 'worktree'
    project.mkdir()
    root = tmp_path / 'main'
    root.mkdir()
    monkeypatch.setattr(telegram.messages, 'repo_root', lambda p: root)
    send = Mock()
    monkeypatch.setattr(telegram, 'reply', send)
    assert main(['-C', str(project), 'reply', '--diff-file', 'saved.diff']) == 0
    assert send.call_args.args[0] == root
    assert send.call_args.kwargs['diff_file'] == project / 'saved.diff'
