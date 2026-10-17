"""The Tomville app: office floor plus Team and Events panels and a key bar."""

from __future__ import annotations

import time
from pathlib import Path
from datetime import datetime
from rich.text import Text

from tomville.core.events import EventReader
from tomville.core.models import AgentAppeared, AgentLeft, AgentStatusChanged, CardChanged, CardRemoved, BoardOffline, BoardOnline, Column, Event
from tomville.core.settings import load_reader_settings

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from tomville.core.world import World
from tomville.tui.office import OfficeView

# Below this width the sidebar moves under the office floor.
PORTRAIT_BELOW = 100

FPS_CHOICES = (5, 10, 15, 30)
DEFAULT_FPS = 10
MAX_DT = 0.5  # a stalled frame never makes pets jump across the office


class TeamPanel(Static):
    DEFAULT_CSS = """
    TeamPanel { height: auto; min-height: 5; border: round $secondary; padding: 0 1; }
    """

    def on_mount(self) -> None:
        self.border_title = "Team"
        self.update("No agents yet")


class BoardPanel(Static):
    DEFAULT_CSS = """
    BoardPanel { height: auto; max-height: 15; border: round $secondary; padding: 0 1; }
    """

    def on_mount(self):
        self.border_title = "Board"
        self.update("No cards yet")


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
        Binding("g", "board_interval", "Board interval"),
        Binding("q", "quit", "Quit"),
        Binding("f", "cycle_fps", "FPS"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    def __init__(
        self,
        project: Path | None = None,
        ville: str = "Tomville",
        settings=None,
        live: bool = True,
        lead: str | None = "claude",
        fps: int = DEFAULT_FPS,
    ) -> None:
        super().__init__()
        self.project = (project or Path.cwd()).resolve()
        self.ville = ville
        self.reader = EventReader(self.project, settings or load_reader_settings(self.project))
        self.reader.snapshot = self.load_snapshot
        self.live = live
        self.world = World(lead=lead)
        self.fps = fps
        self._frame_timer = None
        self._last_frame = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            yield OfficeView(self.world)
            with Vertical(id="sidebar"):
                yield TeamPanel()
                yield BoardPanel()
                yield EventsPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"{self.ville} · {self.project.name}"
        self._apply_layout(self.size.width)
        self.query_one(EventsPanel).write("Office open. Waiting for agents…")
        self._start_timer()
        if self.live:
            self.run_worker(self.reader.run(self.handle_event), name="live-data")

    def _start_timer(self) -> None:
        if self._frame_timer is not None:
            self._frame_timer.stop()
        self._last_frame = time.monotonic()
        self._frame_timer = self.set_interval(1 / self.fps, self._frame)

    def _frame(self) -> None:
        now = time.monotonic()
        self.world.tick(min(now - self._last_frame, MAX_DT))
        self._last_frame = now
        for view in self.query(OfficeView):  # none left while the app shuts down
            view.refresh()

    def on_unmount(self) -> None:
        if self._frame_timer is not None:
            self._frame_timer.stop()

    def action_cycle_fps(self) -> None:
        i = FPS_CHOICES.index(self.fps) if self.fps in FPS_CHOICES else -1
        self.fps = FPS_CHOICES[(i + 1) % len(FPS_CHOICES)]
        self._start_timer()
        self.notify(f"{self.fps} fps", title="Frame rate", timeout=2)

    def on_resize(self, event) -> None:
        self._apply_layout(event.size.width)

    def _apply_layout(self, width: int) -> None:
        self.query_one("#main").set_class(width < PORTRAIT_BELOW, "portrait")

    def action_help(self) -> None:
        self.notify("q quit · G board interval · ? help.", title="Keys")

    def action_board_interval(self):
        choices = (15, 30, 60, 120)
        current = self.reader.settings.check_seconds
        self.reader.settings.check_seconds = next((n for n in choices if n > current), choices[0])
        self.reader.board_wake.set()
        self.query_one(BoardPanel).border_title = f"Board · {self.reader.settings.check_seconds:g} s"
        self.notify(f"Board check: {self.reader.settings.check_seconds} s")

    def load_snapshot(self, agents, cards) -> None:
        """The reader's first state: pets and cards appear in place, with no handovers."""
        self.world.load(agents, cards)
        self._show_state()

    def handle_event(self, event: Event) -> None:
        """Every event from the reader: the world moves pets, the panels show it."""
        self.world.apply(event)
        if isinstance(event, AgentAppeared):
            message = f"{event.agent.name} appeared ({event.agent.status})"
        elif isinstance(event, AgentStatusChanged):
            message = f"{event.name} became {event.new}"
        elif isinstance(event, AgentLeft):
            message = f"{event.name} left"
        elif isinstance(event, CardChanged):
            message = f"{event.card.id} → {event.card.column}" + (f" ({event.card.agent})" if event.card.agent else "")
        elif isinstance(event, CardRemoved):
            message = f"{event.id} removed"
        elif isinstance(event, BoardOffline):
            message = f"Board offline since {event.since:%H:%M:%S}"
        elif isinstance(event, BoardOnline):
            message = "Board online"
        else:
            return
        self.query_one(EventsPanel).write(Text(f"{datetime.now():%H:%M:%S} {message}"))
        self._show_state()

    def _show_state(self) -> None:
        self.query_one(TeamPanel).update(Text("\n".join(f"{a.name}  {a.kind}  {a.status}" for a in self.reader.agents.values()) or "No agents yet"))
        board = self.query_one(BoardPanel)
        board.border_title = f"Board · {self.reader.settings.check_seconds:g} s"
        text = "\n".join(f"{c.id} {c.column} {c.title}" + (f" ({c.agent})" if c.agent else "") for c in sorted(self.reader.cards.values(), key=lambda c: list(Column).index(c.column))) or "No cards yet"
        if self.reader.offline_since:
            text = f"offline since {self.reader.offline_since:%H:%M:%S} UTC\n" + text
        board.update(Text(text))
