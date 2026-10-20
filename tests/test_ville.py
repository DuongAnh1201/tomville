import json

import pytest

from tomville.cli import main
from tomville.core import ville
from tomville.core.settings import load_settings, settings_from_data


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith('TOMVILLE_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path / 'user.toml'))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'claude'))  # never the real ~/.claude
    calls = []

    def no_network(args, project):  # never gh or git remote from a test
        calls.append(args)
        if args[:2] in (['git', 'remote'], ['git', 'config']):
            raise OSError('no remote')
        raise AssertionError(f'unexpected command: {args}')

    monkeypatch.setattr(ville, 'run_command', no_network)
    return calls


def scripted(*answers):
    it = iter(answers)
    asked = []

    def ask(question, default):
        asked.append(question)
        value = next(it)
        return default if value is None else value

    ask.asked = asked
    return ask


def test_questions_for_lead_and_workers(tmp_path):
    ask = scripted('Tom ville', 'lead', 'boss', 'w1, w2', None, None, None, None, None, None, None, None, 'no', 'dog', 'sheep', 'cat', 'tasks-md', '30', 'no', None)
    a = ville.ask_answers(tmp_path, None, ask)
    assert (a.name, a.shape, a.lead, a.workers) == ('Tom ville', 'lead', 'boss', ['w1', 'w2'])
    assert a.pets == {'boss': 'dog', 'w1': 'sheep', 'w2': 'cat'}
    assert (a.source, a.check_seconds, a.style) == ('tasks-md', 30, 'ascii')
    settings = settings_from_data(a.data())
    assert settings.name == 'Tom ville' and settings.lead == 'boss' and settings.pets['w1'] == {'sprite': 'sheep'}
    assert settings.style == 'ascii' and settings.source == 'tasks-md'


def wizard(tmp_path, *agent_answers, tail=('dog', 'sheep', 'cat', 'tasks-md', '30', 'yes', None)):
    ask = scripted('V', 'lead', 'boss', 'w1,w2', *agent_answers, *tail)
    return ville.ask_answers(tmp_path, None, ask)


def test_agent_defaults_with_a_secretary(tmp_path, monkeypatch):
    monkeypatch.setattr(ville, 'run_command', lambda args, project: 'tom@example.com\n')
    a = wizard(tmp_path, *[None] * 8, None, None, tail=(None,) * 4 + ('tasks-md', '30', 'yes', None))
    assert list(a.agent_specs) == ['boss', 'w1', 'w2', 'secretary']
    assert a.agent_specs['boss'] == {'kind': 'claude', 'model': '', 'place': 'here'}
    assert a.agent_specs['w1'] == {'kind': 'codex', 'model': '', 'place': 'worktree'}
    assert a.agent_specs['secretary'] == {'kind': 'claude', 'model': 'claude-haiku-5-5', 'place': 'tab', 'role': 'secretary', 'email': 'tom@example.com'}
    settings = settings_from_data(a.data())
    assert list(settings.agents) == ['boss', 'w1', 'w2', 'secretary'] and settings.agents['secretary'].role == 'secretary'
    assert set(settings.pets) == {'boss', 'w1', 'w2', 'secretary'}


def test_custom_model_each_place_and_no_secretary(tmp_path):
    a = wizard(tmp_path, 'claude', 'claude-opus-5-5', 'gemini', 'gemini-x', 'tab', 'codex', '', 'pane', 'no', tail=(None,) * 3 + ('tasks-md', '30', 'yes', None))
    assert a.agent_specs == {
        'boss': {'kind': 'claude', 'model': 'claude-opus-5-5', 'place': 'here'},
        'w1': {'kind': 'gemini', 'model': 'gemini-x', 'place': 'tab'},
        'w2': {'kind': 'codex', 'model': '', 'place': 'pane'},
    }
    assert a.secretary == '' and 'secretary' not in settings_from_data(a.data()).agents


def test_bad_place_and_kind_are_asked_again(tmp_path):
    a = wizard(tmp_path, None, None, 'Bad Kind!', 'codex', '', 'moon', 'tab', None, None, None, 'no', tail=(None,) * 3 + ('tasks-md', '30', 'yes', None))
    assert a.agent_specs['w1'] == {'kind': 'codex', 'model': '', 'place': 'tab'}


def test_questions_for_a_pipeline_and_bad_answers_are_asked_again(tmp_path):
    ask = scripted(None, 'pipeline', 'plan coder test', None, None, None, 'github', None, 'x', '5', '15', None)
    a = ville.ask_answers(tmp_path, 'Pipe', ask)
    settings = settings_from_data(a.data())
    assert settings.team == 'pipeline' and settings.stages == ('plan', 'coder', 'test') and settings.lead is None
    assert set(settings.pets) == {'plan', 'coder', 'test'}
    assert a.check_seconds == 15 and a.style == 'emoji'


def test_repo_from_the_origin_remote(tmp_path, monkeypatch):
    for url, repo in [
        ('https://github.com/DuongAnh1201/tomville.git', 'DuongAnh1201/tomville'),
        ('git@github.com:owner/name.git', 'owner/name'),
        ('https://github.com/owner/name', 'owner/name'),
        ('https://example.com/owner/name.git', ''),
    ]:
        monkeypatch.setattr(ville, 'run_command', lambda args, project, url=url: url)
        assert ville.github_repo(tmp_path) == repo


def test_ville_file_must_load(tmp_path):
    with pytest.raises(ValueError):
        ville.write_ville(tmp_path, {'style': 'neon'})
    assert not ville.has_ville(tmp_path)


def settings(source='github', lead='claude', workers=('codex1',), repo=''):
    return ville.Answers('v', 'lead', lead, list(workers), source=source, repo=repo)


def make_settings(**kw):
    return settings_from_data(settings(**kw).data())


def test_labels_only_missing_ones_are_created(monkeypatch):
    seen = []

    def fake(args, project):
        seen.append(args)
        if args[:3] == ['gh', 'label', 'list']:
            return json.dumps([{'name': 'status:todo'}, {'name': 'agent:claude'}])
        return ''

    monkeypatch.setattr(ville, 'run_command', fake)
    created = ville.ensure_labels(None, make_settings(repo='o/r'))
    assert created == ['status:doing', 'status:review', 'agent:codex1']
    creates = [a for a in seen if a[:3] == ['gh', 'label', 'create']]
    assert [a[3] for a in creates] == created and all(a[-2:] == ['--repo', 'o/r'] for a in creates)


def test_no_labels_for_a_tasks_md_board(isolated):
    assert ville.ensure_labels(None, make_settings(source='tasks-md')) == []
    assert isolated == []


def test_rules_are_created_appended_and_refreshed(tmp_path):
    s = make_settings()
    assert ville.install_rules(tmp_path, s) == [tmp_path / 'AGENTS.md']  # neither file: AGENTS.md
    first = (tmp_path / 'AGENTS.md').read_text()
    assert 'tmv send' in first and 'tmv task take' in first
    assert ville.install_rules(tmp_path, s) == []  # again: nothing changes
    (tmp_path / 'CLAUDE.md').write_text('# Mine\n\nkeep this')
    changed = ville.install_rules(tmp_path, make_settings(source='tasks-md'))
    assert {p.name for p in changed} == {'AGENTS.md', 'CLAUDE.md'}
    claude = (tmp_path / 'CLAUDE.md').read_text()
    assert claude.startswith('# Mine\n\nkeep this\n\n') and 'TASKS.md' in claude and 'tmv task' not in claude
    assert (tmp_path / 'AGENTS.md').read_text().count(ville.RULES_START) == 1  # replaced in place


def test_hook_matches_the_one_in_claude_settings():
    assert ville.HOOK_COMMAND == 'd=$(cat); case "$d" in *"agent prompt"*) printf %s "$d" | tmv hook claude-pre-tool-use;; esac; exit 0'


def test_hook_added_kept_and_updated(tmp_path):
    path = tmp_path / 'settings.json'
    other = {'matcher': '^(startup)$', 'hooks': [{'type': 'command', 'command': 'echo hi'}]}
    path.write_text(json.dumps({'model': 'x', 'hooks': {'SessionStart': [other], 'PreToolUse': [{'matcher': 'Edit', 'hooks': []}]}}))
    assert ville.install_hook(path) == 'added'
    data = json.loads(path.read_text())
    assert data['model'] == 'x' and data['hooks']['SessionStart'] == [other]
    assert data['hooks']['PreToolUse'][1] == {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': ville.HOOK_COMMAND, 'timeout': 10}]}
    assert ville.install_hook(path) == 'unchanged'
    data['hooks']['PreToolUse'][1]['hooks'][0]['command'] = 'tmv hook claude-pre-tool-use # old'
    path.write_text(json.dumps(data))
    assert ville.install_hook(path) == 'updated'
    assert json.loads(path.read_text())['hooks']['PreToolUse'][1]['hooks'][0]['command'] == ville.HOOK_COMMAND
    assert len(json.loads(path.read_text())['hooks']['PreToolUse']) == 2


def test_hook_refuses_a_file_it_does_not_understand(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('[1]')
    with pytest.raises(ValueError):
        ville.install_hook(path)
    path.write_text('{oops')
    with pytest.raises(ValueError):
        ville.install_hook(path)
    assert path.read_text() == '{oops'


def test_new_yes_makes_a_working_ville(tmp_path, capsys, isolated):
    assert main(['new', 'Tom ville', '--yes', '-C', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    settings = load_settings(tmp_path)
    assert (settings.name, settings.source, settings.lead, settings.style) == ('Tom ville', 'tasks-md', 'claude', 'emoji')
    assert set(settings.pets) == {'claude', 'codex1', 'codex2', 'secretary'}
    assert list(settings.agents) == ['claude', 'codex1', 'codex2', 'secretary'] and settings.agents['claude'].place == 'here'
    assert 'labels: not needed' in out and 'rules: written to AGENTS.md' in out and 'hook: added' in out
    assert (tmp_path / 'AGENTS.md').exists()
    hook = json.loads((tmp_path / 'claude' / 'settings.json').read_text())
    assert hook['hooks']['PreToolUse'][0]['hooks'][0]['command'] == ville.HOOK_COMMAND
    with pytest.raises(SystemExit) as exit:  # already a ville
        main(['new', '--yes', '-C', str(tmp_path)])
    assert exit.value.code == 2


def test_new_asks_the_questions(tmp_path, monkeypatch):
    answers = iter(['Mine', 'lead', 'claude', 'codex1', '', '', '', '', 'worktree', 'no', 'cat', 'dog', 'tasks-md', '60', 'yes', 'no', 'no'])
    monkeypatch.setattr('builtins.input', lambda text: next(answers))
    assert main(['new', '-C', str(tmp_path), '--claude-settings', str(tmp_path / 'c.json')]) == 0
    assert load_settings(tmp_path).name == 'Mine' and (tmp_path / 'c.json').exists()


def test_cancelled_wizard_leaves_nothing_behind(tmp_path, monkeypatch, capsys):
    def eof(text):
        raise EOFError

    monkeypatch.setattr('builtins.input', eof)
    assert main(['new', '-C', str(tmp_path)]) == 1
    assert not ville.has_ville(tmp_path) and 'cancelled' in capsys.readouterr().err


def test_setup_needs_a_ville(tmp_path):
    with pytest.raises(SystemExit) as exit:
        main(['setup', '--yes', '-C', str(tmp_path)])
    assert exit.value.code == 2


def test_setup_redoes_parts_and_reports_failures(tmp_path, monkeypatch, capsys):
    assert main(['new', '--yes', '-C', str(tmp_path)]) == 0
    (tmp_path / 'AGENTS.md').unlink()
    (tmp_path / 'claude' / 'settings.json').unlink()
    capsys.readouterr()
    assert main(['setup', '--yes', '--style', 'ascii', '--theme', 'game-boy', '-C', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert 'rules: written to AGENTS.md' in out and 'hook: added' in out
    settings = load_settings(tmp_path)
    assert (settings.style, settings.theme) == ('ascii', 'game-boy')
    monkeypatch.setattr(ville, 'ensure_labels', lambda *a: (_ for _ in ()).throw(OSError('gh is not logged in')))
    assert main(['setup', '--yes', '-C', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert 'labels: FAILED: gh is not logged in' in out and 'hook: unchanged' in out  # the rest still ran


def test_setup_asks_per_part(tmp_path, monkeypatch, capsys):
    assert main(['new', '--yes', '-C', str(tmp_path)]) == 0
    (tmp_path / 'claude' / 'settings.json').unlink()
    capsys.readouterr()
    answers = iter(['no', 'no', 'no', 'yes'])  # emoji test, labels, rules, hook
    monkeypatch.setattr('builtins.input', lambda text: next(answers))
    assert main(['setup', '-C', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert 'hook: added' in out and 'rules:' not in out and 'labels:' not in out


def test_bare_tomville_offers_new_in_a_project_without_a_ville(tmp_path, monkeypatch):
    started = []

    class FakeApp:
        def __init__(self, **kw):
            started.append(kw['settings'])

        def run(self):
            pass

    monkeypatch.setattr('tomville.tui.app.TomvilleApp', FakeApp)
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('sys.stdout.isatty', lambda: True)
    answers = iter(['yes', 'Offered', 'lead', 'claude', 'codex1', '', '', '', '', 'worktree', 'no', 'cat', 'dog', 'tasks-md', '60', 'yes', 'no', 'no'])
    monkeypatch.setattr('builtins.input', lambda text: next(answers))
    assert main(['-C', str(tmp_path)]) == 0
    assert ville.has_ville(tmp_path) and started[0].name == 'Offered'
    started.clear()
    assert main(['-C', str(tmp_path)]) == 0  # has a ville now: no questions (input would raise)
    assert started[0].name == 'Offered'


def test_bare_tomville_does_not_ask_without_a_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr('tomville.tui.app.TomvilleApp', lambda **kw: type('A', (), {'run': lambda self: None})())
    assert main(['-C', str(tmp_path)]) == 0
    assert not ville.has_ville(tmp_path)


def test_telegram_question_defaults_to_no(tmp_path):
    ask = scripted('V', 'lead', 'boss', 'w1', *[None] * 8, 'dog', 'sheep', 'tasks-md', '30', 'yes', None)
    a = ville.ask_answers(tmp_path, None, ask)
    assert ask.asked[-1].startswith('Connect a Telegram chat to this ville?') and a.telegram is False


def test_telegram_question_yes_and_other_shapes(tmp_path, capsys):
    ask = scripted('V', 'lead', 'boss', 'w1', *[None] * 8, 'dog', 'sheep', 'tasks-md', '30', 'yes', 'yes')
    assert ville.ask_answers(tmp_path, None, ask).telegram is True
    ask = scripted(None, 'pipeline', 'plan coder', None, None, 'tasks-md', '15', None)
    a = ville.ask_answers(tmp_path, None, ask)
    assert a.telegram is False and not any('Telegram' in q for q in ask.asked)
    assert "Sorry, we haven't done Telegram for the pipeline team yet" in capsys.readouterr().out


def test_new_runs_telegram_setup_only_on_yes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('tomville.cli.telegram_setup', lambda project, args: calls.append(project))
    assert main(['new', '--yes', '-C', str(tmp_path)]) == 0  # --yes keeps no
    assert calls == []
    answers = iter(['Mine', 'lead', 'claude', 'codex1', '', '', '', '', 'worktree', 'no', 'cat', 'dog', 'tasks-md', '60', 'yes', 'yes', 'no'])
    monkeypatch.setattr('builtins.input', lambda text: next(answers))
    other = tmp_path / 'other'
    other.mkdir()
    assert main(['new', '-C', str(other), '--claude-settings', str(tmp_path / 'c.json')]) == 0
    assert calls == [other.resolve()]


def test_rules_mention_telegram_only_when_it_is_on(tmp_path):
    off = settings_from_data({'name': 'V', 'team': {'lead': 'claude'}, 'board': {'source': 'tasks-md'}})
    on = settings_from_data({'name': 'V', 'team': {'lead': 'claude'}, 'board': {'source': 'tasks-md'}, 'telegram': {'enabled': True, 'bot': '@v_bot', 'id': 'k3f9k3f9k3f9'}})
    assert 'Telegram' not in ville.rules_text(off) and 'tmv reply' not in ville.rules_text(off)
    text = ville.rules_text(on)
    assert '`📱 Tom (Telegram):`' in text and 'tmv reply "text"' in text and 'Agents not in `[telegram] from` never use `tmv reply`' in text
