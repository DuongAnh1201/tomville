"""Snapshot data shared by text and JSON status output."""
import asyncio
from dataclasses import asdict

from tomville.core.events import agent_list
from tomville.core.models import Agent, Card, Column, Status


def demo_data():
    return ([Agent('claude', 'claude', Status.WORKING, 'demo:1'), Agent('codex1', 'codex', Status.BLOCKED, 'demo:2'), Agent('codex2', 'codex', Status.IDLE, 'demo:3')], [Card('T1', 'Add login form', Column.DOING, 'codex1'), Card('T2', 'Review tests', Column.REVIEW, 'claude'), Card('T3', 'Write docs', Column.TODO)])


def snapshot(reader, project, settings, agent=None):
    errors = []
    if settings.demo:
        agents, cards = demo_data()
        reader.update_agents(agents)
        reader.cards = {c.id: c for c in cards}
    else:
        try:
            reader.update_agents(asyncio.run(agent_list()))
        except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError) as exc:
            errors.append(f'herdr: {exc}')
        reader.update_board()
        if reader.offline_since:
            errors.append('board unavailable')
    lead = settings.lead or next((a.name for a in reader.agents.values()), None)
    agents = [dict(asdict(a), role='stage' if settings.team == 'pipeline' else 'lead' if a.name == lead else 'worker') for a in reader.agents.values() if agent is None or a.name == agent]
    cards = [asdict(c) for c in reader.cards.values() if agent is None or c.agent == agent]
    return {'project': project.name, 'agents': agents, 'cards': cards, 'columns': {str(column): sum(c['column'] == column for c in cards) for column in Column}, 'offline_since': reader.offline_since.isoformat() if reader.offline_since else None, 'errors': errors}


def format_status(data, settings):
    lines = [f"{data['project']} · {len(data['agents'])} agents · {len(data['cards'])} tasks"]
    for a in data['agents']:
        role = a['role']
        tasks = ' · '.join(f"{c['id']} {c['title']}" for c in data['cards'] if c['agent'] == a['name'] and c['column'] != 'done')
        lines.append(f"  {a['name']}  {role}  {a['status']}  {tasks}".rstrip() + (' ← needs approval' if a['status'] == 'blocked' else ''))
    lines.append(' · '.join(f'{key.title()} {value}' for key, value in data['columns'].items()))
    lines.extend(data['errors'])
    return '\n'.join(lines)
