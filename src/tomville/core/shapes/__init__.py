"""Team shapes: how the office is laid out for a kind of team."""

from tomville.core.shapes.base import OfficeMap, Rect, TeamShape
from tomville.core.shapes.lead import LeadShape
from tomville.core.shapes.lead_play import LeadPlay

SHAPES: dict[str, type] = {"lead": LeadShape}
# What a shape adds to the world model (see core/world.py `Play`), by shape name.
PLAYS: dict[str, type] = {"lead": LeadPlay}

__all__ = ["PLAYS", "SHAPES", "LeadPlay", "LeadShape", "OfficeMap", "Rect", "TeamShape"]
