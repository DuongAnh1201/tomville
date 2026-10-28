"""Shared types used by every part of Tomville.

These are the contract between the event reader (M2), the world model (M3) and
the renderer. Change them only through the lead (see AGENTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    """An agent's lifecycle state, exactly as herdr reports it."""

    WORKING = "working"
    BLOCKED = "blocked"
    DONE = "done"
    IDLE = "idle"
    UNKNOWN = "unknown"

    @classmethod
    def from_herdr(cls, value: str | None) -> Status:
        """Map a herdr `agent_status` string; anything unexpected is UNKNOWN."""
        try:
            return cls(value or "")
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class Agent:
    """One agent in a herdr pane."""

    name: str
    kind: str
    status: Status
    pane_id: str
    tab_id: str = ""
    workspace_id: str = ""
    cwd: str = ""
    focused: bool = False
    title: str = ""

    @classmethod
    def from_herdr(cls, data: dict[str, Any]) -> Agent:
        """Build from one entry of `herdr agent list` (`result.agents[]`)."""
        kind = data.get("agent") or "unknown"
        return cls(
            name=data.get("name") or kind,
            kind=kind,
            status=Status.from_herdr(data.get("agent_status")),
            pane_id=data["pane_id"],
            tab_id=data.get("tab_id", ""),
            workspace_id=data.get("workspace_id", ""),
            cwd=data.get("cwd", ""),
            focused=bool(data.get("focused", False)),
            title=data.get("terminal_title_stripped", ""),
        )


class Column(StrEnum):
    """A board column. GitHub labels `status:<column>`; a closed issue is DONE."""

    TODO = "todo"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"


@dataclass(frozen=True)
class Card:
    """One task on the board: a GitHub issue or a TASKS.md row."""

    id: str  # "#12" for an issue, "T1" for a TASKS.md row
    title: str
    column: Column
    agent: str | None = None  # from an `agent:<name>` label
    url: str = ""


@dataclass(frozen=True)
class Message:
    """One prompt from one agent to another, from the message log."""

    time: datetime
    sender: str | None  # None when the sender is unknown (shown as "?")
    to: str
    text: str
    via: str  # "send" (tmv send), "hook" (Claude hook) or "guess" (timing)


# Events: what the event reader hands to the world model.


@dataclass(frozen=True)
class AgentAppeared:
    agent: Agent


@dataclass(frozen=True)
class AgentStatusChanged:
    name: str
    old: Status
    new: Status


@dataclass(frozen=True)
class AgentLeft:
    name: str


@dataclass(frozen=True)
class CardChanged:
    card: Card
    old_column: Column | None  # None for a new card


@dataclass(frozen=True)
class CardRemoved:
    id: str


@dataclass(frozen=True)
class MessageSent:
    message: Message


@dataclass(frozen=True)
class DocChanged:
    """One line of the doc change log: `who` did `op` to `path` (maybe one section)."""
    who: str
    path: str
    op: str
    section: str | None = None


@dataclass(frozen=True)
class BoardOffline:
    since: datetime


@dataclass(frozen=True)
class BoardOnline:
    pass


Event = (
    AgentAppeared
    | AgentStatusChanged
    | AgentLeft
    | CardChanged
    | CardRemoved
    | MessageSent
    | DocChanged
    | BoardOffline
    | BoardOnline
)
