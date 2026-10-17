"""Steps of a pet's script: what a team shape asks a pet to do, in order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

Cell = tuple[int, int]


@dataclass
class Step:
    """One step of a pet's script: walk, say, wait for the bubble to end, or call."""

    kind: str  # "walk" | "say" | "wait" | "call"
    arg: object = None
    started: bool = False


def walk(cell: Cell) -> Step:
    return Step("walk", cell)


def say(text: str) -> Step:
    return Step("say", text)


def wait() -> Step:
    return Step("wait")


def call(fn: Callable[[], None]) -> Step:
    return Step("call", fn)
