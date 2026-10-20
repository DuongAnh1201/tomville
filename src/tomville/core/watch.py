"""Read-only GitHub changes for the lead; each invocation exits on a change."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from tomville.core.commands import run_command
from tomville.core.ville import github_repo

STATE = Path('.tomville/watch.json')
ISSUE_FIELDS = 'number,title,state,url,author,updatedAt,labels,assignees'
PR_FIELDS = ('number,title,state,url,author,updatedAt,labels,isCrossRepository,'
             'headRepositoryOwner,reviewRequests,reviews,reviewDecision,statusCheckRollup')


def ci_state(checks):
    if not checks:
        return 'none'
    states = []
    for check in checks:
        value = check.get('conclusion') or check.get('state') or check.get('status') or 'PENDING'
        states.append(value.upper())
    if any(s in ('FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'STALE') for s in states):
        return 'red'
    if all(s in ('SUCCESS', 'NEUTRAL', 'SKIPPED') for s in states):
        return 'green'
    return 'pending'


def names(rows):
    return sorted({r.get('login') or r.get('name') or ('team:' + r['slug'] if r.get('slug') else r.get('id', 'unknown')) for r in rows})


def normalize(row, kind, repo):
    if (not isinstance(row, dict) or isinstance(row.get('number'), bool)
            or not isinstance(row.get('number'), int) or row['number'] <= 0
            or not isinstance(row.get('title'), str) or row.get('state') not in (('OPEN', 'CLOSED') if kind == 'issue' else ('OPEN', 'CLOSED', 'MERGED'))
            or not isinstance(row.get('url'), str)):
        raise ValueError(f'invalid GitHub {kind} response')
    author = (row.get('author') or {}).get('login', '')
    owner = repo.split('/')[-2]
    fork = bool(row.get('isCrossRepository')) if kind == 'pr' else False
    head_owner = (row.get('headRepositoryOwner') or {}).get('login', owner)
    # gh list exposes no author association. Unknown non-owner identities require
    # Tom's review too; labels alone must never grant merge permission.
    outside = fork or author.casefold() != owner.casefold() or head_owner.casefold() != owner.casefold()
    item = dict(number=row['number'], kind=kind, title=row['title'], state=row['state'], url=row['url'],
                author=author, outside=outside, fork=fork, labels=names(row.get('labels') or []),
                updated_at=row.get('updatedAt', ''))
    if kind == 'issue':
        item['assignees'] = names(row.get('assignees') or [])
    else:
        reviews = []
        for review in row.get('reviews') or []:
            reviewer = (review.get('author') or {}).get('login', 'unknown')
            submitted = review.get('submittedAt', '')
            state = review.get('state', '')
            reviews.append(dict(id=review.get('id') or f'{reviewer}:{submitted}', author=reviewer,
                                state=state, submitted_at=submitted))
        item.update(ci=ci_state(row.get('statusCheckRollup') or []),
                    requests=names(row.get('reviewRequests') or []),
                    reviews=sorted(reviews, key=lambda r: (r['id'], r['state'])),
                    decision=row.get('reviewDecision', ''))
    return item


def fetch(project, repo, limit):
    result = {}
    for kind, command, fields in [('issue', 'issue', ISSUE_FIELDS), ('pr', 'pr', PR_FIELDS)]:
        raw = run_command(['gh', command, 'list', '--state', 'all', '--limit', str(limit),
                           '--repo', repo, '--json', fields], project)
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError(f'invalid GitHub {kind} list')
        if len(rows) >= limit:
            raise ValueError(f'GitHub {kind} list reached --limit {limit}; restart tmv watch with a larger --limit')
        for row in rows:
            item = normalize(row, kind, repo)
            key = f'{kind}:{item["number"]}'
            if key in result:
                raise ValueError(f'duplicate GitHub item {key}')
            result[key] = item
    return result


def load_state(project, repo):
    path = project / STATE
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), dict):
        raise ValueError(f'invalid watch state: {path}')
    if data.get('repo', '').casefold() != repo.casefold():
        return None  # A different board starts with its own silent baseline.
    return data['items']


def save_state(project, repo, items):
    path = project / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.watch-', delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(dict(version=1, repo=repo, items=items), stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def changes(previous, current):
    if previous is None:
        return []
    found = []
    for key, item in sorted(current.items(), key=lambda pair: (pair[1]['number'], pair[1]['kind'])):
        old = previous.get(key)
        events = []
        if old is None:
            events.append(('new', ''))
        else:
            if old['state'] != item['state']:
                events.append(('merged' if item['state'] == 'MERGED' else 'closed' if item['state'] == 'CLOSED' else 'reopened', ''))
            if item['kind'] == 'pr':
                requested = sorted(set(item['requests']) - set(old['requests']))
                if requested:
                    events.append(('review_requested', ', '.join(requested)))
                old_reviews = {r['id']: r for r in old['reviews']}
                for review in item['reviews']:
                    if review['state'] != 'PENDING' and old_reviews.get(review['id']) != review:
                        action = ('changes_requested' if review['state'] == 'CHANGES_REQUESTED' else
                                  'review_dismissed' if review['state'] == 'DISMISSED' else 'review_submitted')
                        events.append((action, review['author'] + ': ' + review['state']))
                if old['decision'] != item['decision'] and not any(a in ('changes_requested', 'review_submitted') for a, _ in events):
                    if item['decision']:
                        events.append(('changes_requested' if item['decision'] == 'CHANGES_REQUESTED' else 'review_decision', item['decision']))
                if old['ci'] != item['ci'] and item['ci'] in ('red', 'green'):
                    events.append(('ci_' + item['ci'], ''))
            # Also surface edits, labels/assignments and comment activity. Ignore
            # pending CI alone: the actionable red/green result gets its own event.
            ignored = {'ci', 'reviews', 'requests', 'decision'}
            if not events and {k: v for k, v in item.items() if k not in ignored} != {k: v for k, v in old.items() if k not in ignored}:
                events.append(('changed', ''))
        found.extend(dict(item, action=action, detail=detail) for action, detail in events)
    return found


def format_change(change):
    label = 'PR' if change['kind'] == 'pr' else 'Issue'
    flags = []
    if change['outside']:
        flags.append('outside/unverified contributor')
    if change['fork']:
        flags.append('fork')
    suffix = ' [' + ', '.join(flags) + ']' if flags else ''
    action = change['action'].replace('_', ' ')
    detail = ': ' + change['detail'] if change['detail'] else ''
    # A title is untrusted text; one change must stay on one terminal line.
    line = f'{label} #{change["number"]} {action}{detail}{suffix} · {change["title"]} · {change["url"]}'
    return ' '.join(re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', line).split())


def run(project, settings, *, limit=1000, sleep=time.sleep, clock=time.monotonic):
    if settings.source != 'github':
        raise ValueError('tmv watch requires a GitHub board')
    if settings.demo:
        raise ValueError('tmv watch is unavailable in demo mode')
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2:
        raise ValueError('--limit must be at least 2')
    repo = settings.repo or github_repo(project)
    if not repo or len(repo.split('/')) < 2:
        raise ValueError('cannot identify GitHub repository; set board.repo or a GitHub origin')
    previous = load_state(project, repo)
    while True:
        started = clock()
        try:
            current = fetch(project, repo, limit)
            found = changes(previous, current)
            # Absence is not closure: a deleted/transferred/missing item must not
            # turn into an invented closed event or a repeat notification later.
            retained = {**(previous or {}), **current}
            save_state(project, repo, retained)
            previous = retained
            if found:
                return found
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
            print(f'{stamp} tmv watch: {" ".join(str(exc).split())}', file=sys.stderr, flush=True)
        sleep(max(0, settings.check_seconds - (clock() - started)))
