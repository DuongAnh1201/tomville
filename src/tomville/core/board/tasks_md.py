"""Offline board: a Markdown table with id, title, status and agent columns."""
from tomville.core.board.base import BoardUnavailable
from tomville.core.models import Card, Column


class TasksMarkdownBoard:
    name = 'tasks-md'

    def __init__(self, path):
        self.path = path
        self.stamp = None
        self.cards = []

    def fetch(self):
        try:
            stat = self.path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp == self.stamp:
                return list(self.cards)
            cards = []
            headers = None
            for line in self.path.read_text().splitlines():
                if not line.strip().startswith('|'):
                    continue
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                if headers is None:
                    headers = [c.lower() for c in cells]
                    if not {'id', 'title', 'status', 'agent'} <= set(headers):
                        raise ValueError('TASKS.md needs id, title, status, agent columns')
                    continue
                if all(not c.strip('-: ') for c in cells):
                    continue
                row = dict(zip(headers, cells, strict=True))
                cards.append(Card(row['id'], row['title'], Column(row['status'].lower()), row['agent'] if row['agent'] not in ('', '-') else None))
            self.cards, self.stamp = cards, stamp
            return list(cards)
        except (OSError, ValueError, KeyError) as exc:
            raise BoardUnavailable(str(exc)) from exc
