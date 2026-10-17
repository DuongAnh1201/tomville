"""The Tomville app: office floor plus Team and Events panels and a key bar."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from tomville.tui.office import OfficeView

# Below this width the sidebar moves under the office floor.
PORTRAIT_BELOW = 100


class TeamPanel(Static):
    DEFAULT_CSS = """
    TeamPanel { height: auto; min-height: 5; border: round $secondary; padding: 0 1; }
    """

    def on_mount(self) -> None:
        self.border_title = "Team"
        self.update("No agents yet")


class EventsPanel(RichLog):
    DEFAULT_CSS = """
    EventsPanel { height: 1fr; border: round $secondary; }
    """

    def on_mount(self) -> None:
        self.border_title = "Events"


class TomvilleApp(App):
    CSS = """
    #main { layout: horizontal; }
    #sidebar { width: 36; }
    #main.portrait { layout: vertical; }
    #main.portrait OfficeView { height: 2fr; }
    #main.portrait #sidebar { width: 1fr; height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(self, project: Path | None = None, ville: str = "Tomville") -> None:
        super().__init__()
        self.project = (project or Path.cwd()).resolve()
        self.ville = ville

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            yield OfficeView()
            with Vertical(id="sidebar"):
                yield TeamPanel()
                yield EventsPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"{self.ville} · {self.project.name}"
        self._apply_layout(self.size.width)
        self.query_one(EventsPanel).write("Office open. Waiting for agents…")

    def on_resize(self, event) -> None:
        self._apply_layout(event.size.width)

    def _apply_layout(self, width: int) -> None:
        self.query_one("#main").set_class(width < PORTRAIT_BELOW, "portrait")

    def action_help(self) -> None:
        self.notify("q quit · ? help. More keys arrive with later milestones.", title="Keys")
