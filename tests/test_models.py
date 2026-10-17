import json
from pathlib import Path

from tomville.core.models import Agent, Status

FIXTURES = Path(__file__).parent / "fixtures"


def test_status_from_herdr():
    assert Status.from_herdr("blocked") is Status.BLOCKED
    assert Status.from_herdr("something-new") is Status.UNKNOWN
    assert Status.from_herdr(None) is Status.UNKNOWN


def test_agent_from_recorded_herdr_list():
    data = json.loads((FIXTURES / "herdr_agent_list.json").read_text())
    agents = [Agent.from_herdr(a) for a in data["result"]["agents"]]
    assert len(agents) == 1
    a = agents[0]
    assert (a.name, a.kind, a.pane_id) == ("claude", "claude", "w1:p1")
    assert a.status is Status.WORKING


def test_agent_name_wins_over_kind():
    a = Agent.from_herdr({"agent": "codex", "name": "codex1", "pane_id": "w1:p2", "agent_status": "idle"})
    assert (a.name, a.kind, a.status) == ("codex1", "codex", Status.IDLE)
