"""Offline gh-list recordings plus explicit review/check transition scenarios."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tomville.cli import main
from tomville.core import doctor, ville, watch
from tomville.core.settings import OfficeSettings

FIXTURES = Path(__file__).parent / 'fixtures'
RECORDED = json.loads((FIXTURES / 'github_watch.json').read_text())
SCENARIOS = json.loads((FIXTURES / 'github_watch_changes.json').read_text())
REPO = 'DuongAnh1201/tomville'


def payload():
    data = copy.deepcopy(RECORDED)
    subject = SCENARIOS['baseline_pr']
    data['prs'] = [copy.deepcopy(subject) if p['number'] == subject['number'] else p for p in data['prs']]
    return data


def normalized(data):
    return {f'{kind}:{r["number"]}': watch.normalize(r, kind, REPO)
            for kind, rows in [('issue', data['issues']), ('pr', data['prs'])] for r in rows}


def scenario(name):
    data = payload()
    change = SCENARIOS['cases'][name]
    key = 'issues' if change['kind'] == 'issue' else 'prs'
    data[key] = [copy.deepcopy(change['item']) if row['number'] == change['item']['number'] else row for row in data[key]]
    return data


def settings(**kw):
    return OfficeSettings(repo=REPO, check_seconds=300, **kw)


def test_fetch_uses_only_read_only_list_calls(monkeypatch, tmp_path):
    data = payload()
    calls = []
    def run(args, project):
        calls.append(args)
        return json.dumps(data['issues' if args[1] == 'issue' else 'prs'])
    monkeypatch.setattr(watch, 'run_command', run)
    assert watch.fetch(tmp_path, REPO, 1000) == normalized(data)
    assert [args[:3] for args in calls] == [['gh', 'issue', 'list'], ['gh', 'pr', 'list']]
    assert all(args[args.index('--state') + 1] == 'all' for args in calls)
    assert all(args[args.index('--repo') + 1] == REPO for args in calls)


@pytest.mark.parametrize('case,action', [('review_requested','review_requested'), ('review_submitted','review_submitted'),
    ('changes_requested','changes_requested'), ('ci_red','ci_red'), ('ci_green','ci_green'),
    ('pr_closed','closed'), ('issue_closed','closed')])
def test_recorded_transitions(case, action):
    found = watch.changes(normalized(payload()), normalized(scenario(case)))
    assert [c['action'] for c in found] == [action]
    assert len(watch.format_change(found[0]).splitlines()) == 1


def test_new_issue_and_outside_fork_are_marked():
    data = payload()
    outside = next(p for p in data['prs'] if p['number'] == 69)
    before = normalized(dict(data, prs=[p for p in data['prs'] if p['number'] != 69]))
    issue = copy.deepcopy(data['issues'][0])
    issue.update(number=1001, title='Outside issue', author={'login':'another-user'})
    data['issues'].append(issue)
    found = watch.changes(before, normalized(data))
    assert [c['number'] for c in found] == [69, 1001]
    assert all(c['outside'] and c['action'] == 'new' for c in found)
    assert found[0]['fork'] and outside['isCrossRepository']
    assert 'outside/unverified contributor' in watch.format_change(found[0])
    assert 'fork' in watch.format_change(found[0])


def test_owner_is_team_but_unknown_or_non_owner_is_not():
    row = copy.deepcopy(SCENARIOS['baseline_pr'])
    assert not watch.normalize(row, 'pr', REPO)['outside']
    row.update(author=None)
    assert watch.normalize(row, 'pr', REPO)['outside']
    row.update(author={'login':'teammate'}, isCrossRepository=False)
    assert watch.normalize(row, 'pr', REPO)['outside']


def test_pending_ci_noop_reordering_and_no_invented_closures():
    data = payload()
    before = normalized(data)
    pr = data['prs'][0]
    pr['statusCheckRollup'] = [{'status':'IN_PROGRESS','conclusion':''}]
    assert watch.changes(before, normalized(data)) == []
    data['issues'][0]['labels'].reverse()
    assert watch.changes(before, normalized(data)) == []
    assert watch.changes(before, {}) == []
    assert watch.ci_state([{'state':'SUCCESS'}]) == 'green'
    assert watch.ci_state([{'state':'ERROR'},{'status':'IN_PROGRESS'}]) == 'red'
    assert watch.ci_state([{'conclusion':'SKIPPED'},{'conclusion':'NEUTRAL'}]) == 'green'


def test_edit_labels_comments_reopen_merge_and_review_decision():
    before = normalized(payload())
    for field, value in [('title','Changed'), ('updated_at','later'), ('labels',['agent:new'])]:
        current = copy.deepcopy(before)
        current[next(iter(current))][field] = value
        assert watch.changes(before, current)[0]['action'] == 'changed'
    key = f'pr:{SCENARIOS["subject_pr"]}'
    current = copy.deepcopy(before)
    current[key]['state'] = 'MERGED'
    assert watch.changes(before, current)[0]['action'] == 'merged'
    assert watch.changes(current, before)[0]['action'] == 'reopened'
    current = copy.deepcopy(before)
    current[key]['decision'] = 'CHANGES_REQUESTED'
    assert watch.changes(before, current)[0]['action'] == 'changes_requested'


def test_first_success_records_silently_then_exits_on_change(tmp_path, monkeypatch, capsys):
    first, changed = normalized(payload()), normalized(scenario('ci_red'))
    snapshots = iter([first, first, changed])
    monkeypatch.setattr(watch, 'fetch', lambda *args: next(snapshots))
    sleeps = []
    def sleep(seconds):
        assert capsys.readouterr().out == ''
        assert watch.load_state(tmp_path, REPO) == first
        sleeps.append(seconds)
    result = watch.run(tmp_path, settings(), sleep=sleep, clock=lambda:0)
    assert sleeps == [300, 300] and result[0]['action'] == 'ci_red'
    assert watch.load_state(tmp_path, REPO) == changed
    assert watch.changes(changed, changed) == []


def test_restart_uses_saved_baseline_and_missing_rows_stay_known(tmp_path, monkeypatch):
    baseline = normalized(payload())
    watch.save_state(tmp_path, REPO, baseline)
    snapshots = iter([{}, baseline, normalized(scenario('pr_closed'))])
    monkeypatch.setattr(watch, 'fetch', lambda *a: next(snapshots))
    sleeps=[]
    result = watch.run(tmp_path, settings(), sleep=sleeps.append, clock=lambda:0)
    assert sleeps == [300, 300]
    assert result[0]['action'] == 'closed'
    assert set(watch.load_state(tmp_path, REPO)) == set(baseline)


def test_failure_does_not_advance_baseline_and_retries_next_interval(tmp_path, monkeypatch, capsys):
    first = normalized(payload())
    watch.save_state(tmp_path, REPO, first)
    # A failed second list must not commit an updated first list.
    data = scenario('ci_red')
    calls=[]
    def run(args, project):
        calls.append(args)
        if len(calls) == 2:
            raise OSError('GitHub unavailable')
        return json.dumps(data['issues' if args[1]=='issue' else 'prs'])
    monkeypatch.setattr(watch, 'run_command', run)
    times=iter([0,5,300])
    def sleep(seconds):
        assert seconds == 295
        assert watch.load_state(tmp_path, REPO) == first
    found = watch.run(tmp_path, settings(), sleep=sleep, clock=lambda:next(times))
    assert found[0]['action'] == 'ci_red' and len(calls) == 4
    output=capsys.readouterr()
    assert output.out == '' and 'tmv watch: GitHub unavailable' in output.err


def test_failed_initial_read_does_not_create_baseline(tmp_path, monkeypatch):
    responses=iter([OSError('offline'), normalized(payload()), normalized(scenario('ci_green'))])
    def fetch(*args):
        value=next(responses)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(watch, 'fetch', fetch)
    sleeps=[]
    def sleep(seconds):
        if not sleeps: assert not (tmp_path/watch.STATE).exists()
        sleeps.append(seconds)
    found=watch.run(tmp_path, settings(), sleep=sleep, clock=lambda:0)
    assert sleeps == [300,300] and found[0]['action']=='ci_green'


def test_cap_invalid_payload_and_repo_change(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, 'run_command', lambda *a:json.dumps(payload()['issues']))
    with pytest.raises(ValueError, match='larger --limit'):
        watch.fetch(tmp_path, REPO, 2)
    monkeypatch.setattr(watch, 'run_command', lambda *a:'null')
    with pytest.raises(ValueError, match='invalid GitHub'):
        watch.fetch(tmp_path, REPO, 1000)
    watch.save_state(tmp_path, REPO, normalized(payload()))
    assert watch.load_state(tmp_path, 'other/repo') is None
    for value in ('[]', '{"version":99,"items":{}}'):
        (tmp_path/watch.STATE).write_text(value)
        with pytest.raises(ValueError, match='invalid watch state'):
            watch.load_state(tmp_path, REPO)


@pytest.mark.parametrize('config', [settings(source='tasks-md'), settings(demo=True)])
def test_watch_rejects_non_github_and_demo(tmp_path, config):
    with pytest.raises(ValueError):
        watch.run(tmp_path, config)


def test_cli_json_text_worktree_and_interval(tmp_path, monkeypatch, capsys):
    root=tmp_path/'main'; root.mkdir()
    project=tmp_path/'worktree'; project.mkdir()
    ville.write_ville(root, {'board':{'source':'github','repo':REPO,'check_seconds':300}})
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path/'user.toml'))
    monkeypatch.setattr('tomville.core.messages.repo_root', lambda p:root)
    found=watch.changes(normalized(payload()),normalized(scenario('ci_red')))
    run=Mock(return_value=found)
    monkeypatch.setattr(watch,'run',run)
    assert main(['-C',str(project),'watch','--json'])==0
    assert json.loads(capsys.readouterr().out)[0]['action']=='ci_red'
    assert run.call_args.args[0]==root and run.call_args.args[1].check_seconds==300
    assert main(['watch','-C',str(root),'--board-check','15'])==0
    assert run.call_args.args[1].check_seconds==15
    assert 'PR #' in capsys.readouterr().out


def test_rules_doctor_interval_and_ignored_cache(tmp_path, monkeypatch):
    rules=ville.rules_text(settings(watch=True))
    assert 'Lead only: keep `tmv watch` running in the background' in rules
    assert 'never merge without Tom' in rules and 'restart it' in rules
    assert 'tmv watch' not in ville.rules_text(settings())
    assert 'tmv watch' not in ville.rules_text(settings(source='tasks-md', watch=True))
    async def agents(): return []
    monkeypatch.setattr(doctor,'agent_list',agents)
    monkeypatch.setattr(doctor,'run_command',lambda *args:'[]')
    monkeypatch.setattr('tomville.core.events.EventReader.update_board',lambda self:[])
    result=doctor.diagnose(tmp_path,settings())
    row=next(r for r in result['checks'] if r['name']=='GitHub watch')
    assert row['ok'] and '300 seconds' in row['detail'] and 'off (opt-in)' in row['detail']
    assert '.tomville/watch.json' in (Path(__file__).parents[1]/'.gitignore').read_text()


def test_opt_in_config_updates_ville_and_refreshes_rules(tmp_path, monkeypatch, capsys):
    from tomville.core.settings import load_settings, settings_from_data
    monkeypatch.setenv('TOMVILLE_CONFIG', str(tmp_path/'user.toml'))
    monkeypatch.setattr('tomville.core.messages.repo_root', lambda p: tmp_path)
    ville.write_ville(tmp_path, {'board': {'source': 'github', 'watch': False}})
    assert not load_settings(tmp_path).watch
    assert not settings_from_data({}).watch
    for value, enabled in [('true', True), ('false', False)]:
        assert main(['-C', str(tmp_path), 'config', 'set', 'board.watch', value]) == 0
        assert load_settings(tmp_path).watch is enabled
        assert ('keep `tmv watch`' in (tmp_path/'AGENTS.md').read_text()) is enabled
        assert main(['-C', str(tmp_path), 'config', 'get', 'board.watch', '--json']) == 0
        capsys.readouterr()
    for invalid in ('yes', 1, None):
        with pytest.raises(ValueError, match='board.watch'):
            settings_from_data({'board': {'watch': invalid}})


@pytest.mark.parametrize('answer,enabled', [(None, False), ('yes', True)])
def test_wizard_asks_watch_default_no(tmp_path, monkeypatch, answer, enabled):
    monkeypatch.setattr(ville, 'github_repo', lambda p: REPO)
    questions = []
    def ask(question, default):
        questions.append((question, default))
        if question.startswith('Team shape'): return 'pipeline'
        if question.startswith('Should the lead check GitHub'):
            assert default == 'no'
            return default if answer is None else answer
        return default
    data = ville.ask_answers(tmp_path, None, ask).data()
    assert data['board']['watch'] is enabled
    assert any('every 60 s for new issues, PRs, reviews and CI' in q for q, _ in questions)
