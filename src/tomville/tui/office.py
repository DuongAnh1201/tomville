"""The office floor widget: draws the team shape's map at the widget's size."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from tomville.core.shapes import LeadShape, OfficeMap, TeamShape


class OfficeView(Widget):
    DEFAULT_CSS = """
    OfficeView {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, shape: TeamShape | None = None, lead: str | None = None, workers: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shape = shape or LeadShape()
        self.lead = lead
        self.worker_names = workers or []
        self.office: OfficeMap | None = None

    def set_team(self, lead: str | None, workers: list[str]) -> None:
        self.lead, self.worker_names = lead, workers
        self.office = None
        self.refresh()

    def render(self) -> Text:
        w, h = self.size.width, self.size.height
        if self.office is None or (self.office.width, self.office.height) != (w, h):
            self.office = self.shape.layout(w, h, self.lead, self.worker_names)
        return Text(self.office.text(), no_wrap=True, overflow="crop")
