"""The office floor widget: draws the world's map, then its pets, names and bubbles."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widget import Widget

from tomville.core.models import Status
from tomville.core.shapes import OfficeMap
from tomville.core.world import World

# One letter per agent kind until sprites arrive (M4).
GLYPHS = {"claude": "C", "codex": "X"}
STATUS_STYLE = {
    Status.WORKING: "bold green",
    Status.BLOCKED: "bold red",
    Status.DONE: "bold cyan",
    Status.IDLE: "bold yellow",
    Status.UNKNOWN: "bold magenta",
}
BUBBLE_STYLE = "black on white"


class OfficeView(Widget):
    DEFAULT_CSS = """
    OfficeView {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, world: World | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.world = world or World()

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

        apps = self.world.appearances()
        for a in apps:
            style = STATUS_STYLE[a.status]
            put(a.x, a.y, GLYPHS.get(a.kind, a.kind[:1].upper() or "?"), style)
            put(a.x + 2, a.y, a.label, "dim" if a.status is not Status.BLOCKED else style)
        for a in apps:
            rect = self.world.bubble_rect(a.name)
            if rect is not None:
                put(rect.x, rect.y, f" {a.bubble[:28]} ", BUBBLE_STYLE)
        return rows
