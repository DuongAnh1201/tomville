"""GitHub task mutations; labels carry status and agent ownership."""
import asyncio
import json
import os

from tomville.core.commands import run_command
from tomville.core.events import agent_list


class Tasks:
    def __init__(self, project, settings):
        if settings.source != 'github':
            raise ValueError('task mutations require the GitHub board (--board github)')
        if settings.demo:
            raise ValueError('task mutations are unavailable in demo mode')
        self.project = project
        self.repo = settings.repo

    def gh(self, *args):
        command = ['gh', 'issue', *args]
        if self.repo:
            command += ['--repo', self.repo]
        return run_command(command, self.project)

    def current_agent(self):
        pane = os.environ.get('HERDR_PANE_ID')
        if pane:
            for agent in asyncio.run(agent_list()):
                if agent.pane_id == pane:
                    return agent.name
        raise ValueError('cannot identify this agent; use --agent NAME')

    def new(self, title, body='', agent=None):
        labels = 'status:todo' + (f',agent:{agent}' if agent else '')
        return self.gh('create', '--title', title, '--body', body, '--label', labels)

    def move(self, number, column, agent=None):
        try:
            issue = json.loads(self.gh('view', str(number), '--json', 'labels,state'))
            if not isinstance(issue['labels'], list) or issue['state'] not in ('OPEN', 'CLOSED'):
                raise ValueError('invalid issue state or labels')
            if any(not isinstance(label.get('name'), str) for label in issue['labels']):
                raise ValueError('invalid issue label')
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise OSError(f'invalid GitHub issue response: {exc}') from exc
        args = ['edit', str(number)]
        remove = [label['name'] for label in issue['labels'] if (label['name'].startswith('status:') and label['name'] != f'status:{column}') or (agent and label['name'].startswith('agent:') and label['name'] != f'agent:{agent}')]
        for label in remove:
            args += ['--remove-label', label]
        if column != 'done':
            args += ['--add-label', f'status:{column}']
        if agent:
            args += ['--add-label', f'agent:{agent}']
        if len(args) > 2:
            self.gh(*args)
        if column == 'done' and issue['state'].lower() != 'closed':
            return self.gh('close', str(number))
        if column != 'done' and issue['state'].lower() == 'closed':
            return self.gh('reopen', str(number))
        return f'#{number} → {column}'
