"""The office floor widget: draws the world's map, then its pets, names and bubbles."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widget import Widget

from tomville.core.models import Status
from tomville.core.shapes import OfficeMap
from tomville.core.sprites import Sprites
from tomville.core.world import World

ANIM_HZ = 4  # sprite frames per second, whatever the frame rate
STATUS_STYLE = {
    Status.WORKING: "bold green",
    Status.BLOCKED: "bold red",
    Status.DONE: "bold cyan",
    Status.IDLE: "bold yellow",
    Status.UNKNOWN: "bold magenta",
}
BUBBLE_STYLE = "black on white"
PARCEL_STYLE = "bold white on blue"


class OfficeView(Widget):
    DEFAULT_CSS = """
    OfficeView {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, world: World | None = None, sprites: Sprites | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.world = world or World()
        self.sprites = sprites or Sprites()

    @property
    def office(self) -> OfficeMap | None:
        return self.world.office

    def render(self) -> Text:
        self.world.resize(self.size.width, self.size.height)
        office = self.world.office
        if office is None:
            return Text("")
        overlays = self._overlays()
        out = Text(no_wrap=True, overflow="crop")
        for y, row in enumerate(office.rows):
            if y:
                out.append("\n")
            if y not in overlays:
                out.append(row)
                continue
            cells: list[tuple[str, str]] = [(ch, "") for ch in row]
            for x, s, style in overlays[y]:
                for ch in s:
                    if 0 <= x < len(cells):
                        cells[x] = (ch, style)
                    x += 1
                    if cell_len(ch) == 2 and 0 <= x < len(cells):
                        cells[x] = ("", style)  # the second half of a wide character
                        x += 1
            for ch, style in cells:
                out.append(ch, style or None)
        return out

    def _overlays(self) -> dict[int, list[tuple[int, str, str]]]:
        """Everything drawn over the map, by row; later items win."""
        rows: dict[int, list[tuple[int, str, str]]] = {}

        def put(x: int, y: int, s: str, style: str) -> None:
            rows.setdefault(y, []).append((x, s, style))

        for x, y, label in self.world.parcel_cells():
            text = f"[{label}]"
            put(x - cell_len(text) // 2, y, text, PARCEL_STYLE)
        apps = self.world.appearances()
        for a in apps:
            style = STATUS_STYLE[a.status]
            frames = self.sprites.frames(a.name, a.kind)
            moving = a.moving or a.status is Status.WORKING
            frame = frames[int(self.world.time * ANIM_HZ) % len(frames)] if moving else frames[0]
            put(a.x, a.y, frame, style)
            put(a.x + 2, a.y, a.label, "dim" if a.status is not Status.BLOCKED else style)
        for a in apps:
            rect = self.world.bubble_rect(a.name)
            if rect is not None:
                put(rect.x, rect.y, f" {a.bubble[:28]} ", BUBBLE_STYLE)
        return rows
