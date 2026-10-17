"""The board plug-in interface.

A source only returns the current cards; the event reader compares two fetches
and turns the difference into CardChanged / CardRemoved events.
"""

from __future__ import annotations

from typing import Protocol

from tomville.core.models import Card


class BoardUnavailable(Exception):
    """The board can't be read right now (offline, auth, missing file)."""


class BoardSource(Protocol):
    name: str  # "github" or "tasks-md", as in `[board] source`

    def fetch(self) -> list[Card]:
        """Return every card on the board now. Raise BoardUnavailable on failure."""
        ...
