"""Team shapes: how the office is laid out for a kind of team."""

from tomville.core.shapes.base import OfficeMap, Rect, TeamShape
from tomville.core.shapes.lead import LeadShape

SHAPES: dict[str, type] = {"lead": LeadShape}

__all__ = ["SHAPES", "LeadShape", "OfficeMap", "Rect", "TeamShape"]
