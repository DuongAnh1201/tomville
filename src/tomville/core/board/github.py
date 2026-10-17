"""GitHub Issues board, with a separate conditional cache for each API page."""
import json
import re
import subprocess

from tomville.core.board.base import BoardUnavailable
from tomville.core.models import Card, Column


def cards_from_issues(issues):
    cards = []
    for issue in issues:
        if 'pull_request' in issue:
            continue
        labels = [label['name'] for label in issue.get('labels', [])]
        column = Column.DONE if issue['state'] == 'closed' else next(
            (c for c in (Column.REVIEW, Column.DOING, Column.TODO) if f'status:{c}' in labels), Column.TODO)
        agent = next((s.removeprefix('agent:') for s in labels if s.startswith('agent:')), None)
        cards.append(Card(f"#{issue['number']}", issue['title'], column, agent, issue.get('html_url', '')))
    return cards


class GitHubBoard:
    name = 'github'

    def __init__(self, project, repo=''):
        self.project = project
        self.repo = repo
        self.pages = {}

    def _run(self, args):
        result = subprocess.run(args, cwd=self.project, capture_output=True, text=True, timeout=20)
        if result.returncode and not (result.stdout.startswith('HTTP/') and result.stdout.splitlines()[0].split()[1] == '304'):
            raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
        return result.stdout

    def fetch(self):
        try:
            if not self.repo:
                self.repo = self._run(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner']).strip()
            endpoint = f'repos/{self.repo}/issues?state=all&per_page=100'
            cards = []
            while endpoint:
                cached = self.pages.get(endpoint)
                args = ['gh', 'api', '--include', endpoint]
                if cached and cached[0]:
                    args += ['-H', f'If-None-Match: {cached[0]}']
                raw = self._run(args).replace('\r\n', '\n')
                head, _, body = raw.partition('\n\n')
                status = int(head.splitlines()[0].split()[1])
                if status == 304 and cached:
                    page = cached
                elif status == 200:
                    headers = dict(line.split(':', 1) for line in head.splitlines()[1:] if ':' in line)
                    headers = {k.lower(): v.strip() for k, v in headers.items()}
                    link = re.search(r'<https://api.github.com/([^>]+)>; rel="next"', headers.get('link', ''))
                    page = (headers.get('etag'), cards_from_issues(json.loads(body)), link[1] if link else '')
                    self.pages[endpoint] = page
                else:
                    raise ValueError(f'Unexpected HTTP status {status}')
                cards.extend(page[1])
                endpoint = page[2]
            return cards
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise BoardUnavailable(str(exc)) from exc
