"""Live data ingestion. Core emits the shared events and never imports the UI."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from tomville.core.board.base import BoardUnavailable
from tomville.core.board.github import GitHubBoard
from tomville.core.board.tasks_md import TasksMarkdownBoard
from tomville.core.models import (
    Agent, AgentAppeared, AgentLeft, AgentStatusChanged, BoardOffline,
    BoardOnline, CardChanged, CardRemoved, MessageSent, Status,
)
from tomville.core.messages import LogFollower, log_path
from tomville.core.settings import ReaderSettings


def parse_agents(payload):
    agents = []
    for row in payload['result']['agents']:
        row = dict(row)
        row['agent'] = row.get('agent') or (row.get('agent_session') or {}).get('agent')
        agents.append(Agent.from_herdr(row))
    return agents


async def agent_list():
    process = await asyncio.create_subprocess_exec('herdr', 'agent', 'list', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        if process.returncode:
            raise OSError(stderr.decode())
        return parse_agents(json.loads(stdout))
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class EventReader:
    def __init__(self, project, settings=None, board=None):
        self.settings = settings or ReaderSettings()
        self.board = board or (GitHubBoard(project, self.settings.repo) if self.settings.source == 'github' else TasksMarkdownBoard(project / ('TASKS.md' if self.settings.source == 'tasks-md' else self.settings.source)))
        self.agents = {}
        self.cards = {}
        self.offline_since = None
        self.messages = LogFollower(log_path(project))
        self.board_wake = asyncio.Event()
        # Optional: called as snapshot(agents, cards) once each source has read its
        # first state. That first state is not emitted as events (no "appeared" or
        # "changed" for everything that already existed).
        self.snapshot = None
        self._started = set()

    def _emit(self, source, events, emit):
        """Emit events; the first pass of a source goes to `snapshot` instead."""
        if self.snapshot is None or source in self._started:
            for event in events:
                emit(event)
            return
        self._started.add(source)
        kinds = (AgentAppeared, AgentLeft, AgentStatusChanged) if source == 'agents' else (CardChanged, CardRemoved)
        for event in events:
            if not isinstance(event, kinds):
                emit(event)
        self.snapshot(list(self.agents.values()), list(self.cards.values()))

    def update_agents(self, agents):
        current = {a.pane_id: a for a in agents}
        events = []
        for pane, agent in current.items():
            old = self.agents.get(pane)
            if old is None:
                events.append(AgentAppeared(agent))
            elif old.name != agent.name or old.kind != agent.kind:
                events.extend([AgentLeft(old.name), AgentAppeared(agent)])
            elif old.status != agent.status:
                events.append(AgentStatusChanged(agent.name, old.status, agent.status))
        events.extend(AgentLeft(a.name) for pane, a in self.agents.items() if pane not in current)
        self.agents = current
        return events

    def update_board(self):
        try:
            cards = {c.id: c for c in self.board.fetch()}
        except BoardUnavailable:
            if self.offline_since is None:
                self.offline_since = datetime.now(timezone.utc)
                return [BoardOffline(self.offline_since)]
            return []
        events = [BoardOnline()] if self.offline_since else []
        self.offline_since = None
        events.extend(CardChanged(c, self.cards[c.id].column if c.id in self.cards else None) for c in cards.values() if c != self.cards.get(c.id))
        events.extend(CardRemoved(key) for key in self.cards.keys() - cards.keys())
        self.cards = cards
        return events

    async def _agents(self, emit):
        async def refresh():
            events = []
            try:
                events = self.update_agents(await agent_list())
            finally:
                self._emit('agents', events, emit)

        while True:
            writer = None
            try:
                # Open before the snapshot so events during startup remain buffered.
                path = os.environ.get('HERDR_SOCKET_PATH', str(Path.home() / '.config/herdr/herdr.sock'))
                reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), 3)
                await refresh()
                subscriptions = [{'type': name} for name in ('pane.agent_detected', 'pane.closed')]
                subscriptions += [{'type': 'pane.agent_status_changed', 'pane_id': pane} for pane in self.agents]
                writer.write((json.dumps({'id': 'tomville', 'method': 'events.subscribe', 'params': {'subscriptions': subscriptions}}) + '\n').encode())
                await writer.drain()
                reply = json.loads(await asyncio.wait_for(reader.readline(), 3))
                if 'error' in reply:
                    raise OSError(str(reply['error']))
                # Reconcile again after subscription to cover the initial snapshot gap.
                await refresh()
                while line := await reader.readline():
                    envelope = json.loads(line)
                    data = envelope.get('data', {})
                    event = envelope.get('event', '')
                    pane = data.get('pane_id')
                    if event in ('pane.agent_status_changed', 'pane_agent_status_changed') and pane in self.agents:
                        agent = self.agents[pane]
                        new = Status.from_herdr(data.get('agent_status'))
                        self.agents[pane] = replace(agent, status=new)
                        if new != agent.status:
                            emit(AgentStatusChanged(agent.name, agent.status, new))
                    else:
                        previous = set(self.agents)
                        await refresh()
                        # New panes need a new per-pane subscription.
                        if set(self.agents) != previous:
                            break
                else:
                    raise OSError('herdr event stream closed')
            except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
                try:
                    await refresh()
                except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(self.settings.poll_seconds)
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass

    async def _board(self, emit):
        while True:
            self.board_wake.clear()
            self._emit('board', await asyncio.to_thread(self.update_board), emit)
            interval = self.settings.poll_seconds if self.board.name == 'tasks-md' else self.settings.check_seconds
            try:
                await asyncio.wait_for(self.board_wake.wait(), interval)
            except asyncio.TimeoutError:
                pass

    async def _messages(self, emit):
        # Only messages sent while the office is open; old ones are history.
        self.messages.skip_existing()
        while True:
            try:
                for message in self.messages.read_new():
                    emit(MessageSent(message))
            except OSError:
                pass
            await asyncio.sleep(self.settings.poll_seconds)

    async def run(self, emit):
        tasks = [asyncio.create_task(self._agents(emit)), asyncio.create_task(self._board(emit)), asyncio.create_task(self._messages(emit))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
