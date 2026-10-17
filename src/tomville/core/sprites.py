"""Sprites: plain text files, one folder per pet, one file per style.

A frame is one line that is exactly two cells wide (every pet takes one 2-cell
tile, so styles can switch without the map shifting). Frames are separated by a
line with `---`. The first frame is used when standing still; all frames play in
a loop when walking or working.
"""

from __future__ import annotations

import re
from importlib.resources import files

from rich.cells import cell_len

STYLES = ("emoji", "ascii")  # what `S` cycles through
BLOCKS_NOTE = "Block pixels arrive in M12; using ASCII sprites"
TILE = 2  # cells per sprite
DEFAULT_PETS = {"claude": "cat", "codex": "dog"}  # by herdr agent kind
FALLBACK_PET = "sheep"  # every other kind


class SpriteError(ValueError):
    pass


def _root():
    return files("tomville") / "data" / "sprites"


def available_pets() -> list[str]:
    return sorted(p.name for p in _root().iterdir() if p.is_dir())


def parse_frames(text: str) -> list[str]:
    """Split a sprite file into frames; each must be one non-empty line."""
    frames = []
    for chunk in re.split(r"^---[ \t]*$", text, flags=re.MULTILINE):
        lines = chunk.strip("\n").split("\n")
        if lines == [""]:
            continue
        if len(lines) != 1:
            raise SpriteError("emoji and ascii frames must be one line each")
        frames.append(lines[0])
    if not frames:
        raise SpriteError("no frames")
    return frames


def load_frames(pet: str, style: str) -> list[str]:
    path = _root() / pet / f"{style}.txt"
    if not path.is_file():
        raise SpriteError(f"no {style} sprite for {pet}")
    return parse_frames(path.read_text(encoding="utf-8"))


def bad_width(frames: list[str]) -> list[str]:
    return [f for f in frames if cell_len(f) != TILE]


class Sprites:
    """Which pet each agent is, in which style, and its frames."""

    def __init__(self, style: str = "emoji", pets: dict[str, str] | None = None) -> None:
        self._notes: list[str] = []
        if style == "blocks":  # a valid setting, but not drawn until Part 2
            self._notes.append(BLOCKS_NOTE)
            style = "ascii"
        if style not in STYLES:
            raise SpriteError(f"unknown style {style!r}; choose from {', '.join(STYLES)}, blocks")
        self.style = style
        self.overrides = dict(pets or {})
        for pet in self.overrides.values():
            if pet not in available_pets():
                raise SpriteError(f"unknown pet {pet!r}; choose from {', '.join(available_pets())}")
        self._cache: dict[tuple[str, str], list[str]] = {}

    @classmethod
    def from_settings(cls, settings) -> Sprites:
        """From `OfficeSettings`: `style` and `[pets.AGENT] sprite = "cat"`."""
        pets = {name: table["sprite"] for name, table in (getattr(settings, "pets", None) or {}).items() if table.get("sprite")}
        return cls(getattr(settings, "style", "emoji"), pets)

    def pet_for(self, name: str, kind: str) -> str:
        return self.overrides.get(name) or DEFAULT_PETS.get(kind, FALLBACK_PET)

    def frames(self, name: str, kind: str) -> list[str]:
        return self._frames(self.pet_for(name, kind), self.style)

    def cycle_style(self) -> str:
        self.style = STYLES[(STYLES.index(self.style) + 1) % len(STYLES)]
        return self.style

    def take_notes(self) -> list[str]:
        """Messages for the Events panel, once each."""
        notes, self._notes = self._notes, []
        return notes

    def _frames(self, pet: str, style: str) -> list[str]:
        key = (pet, style)
        if key not in self._cache:
            frames = load_frames(pet, style)
            if bad_width(frames) and style != "ascii":
                self._notes.append(f"{pet}: {style} sprite is not {TILE} cells wide, using ASCII")
                frames = load_frames(pet, "ascii")
            self._cache[key] = frames
        return self._cache[key]
