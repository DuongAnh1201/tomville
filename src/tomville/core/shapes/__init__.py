"""Team shapes: how the office is laid out for a kind of team."""

from tomville.core.shapes.base import OfficeMap, Rect, TeamShape
from tomville.core.shapes.lead import LeadShape
from tomville.core.shapes.lead_play import LeadPlay
from tomville.core.shapes.pipeline import PipelineShape
from tomville.core.shapes.pipeline_play import PipelinePlay

SHAPES: dict[str, type] = {"lead": LeadShape, "pipeline": PipelineShape}
# What a shape adds to the world model (see core/world.py `Play`), by shape name.
PLAYS: dict[str, type] = {"lead": LeadPlay, "pipeline": PipelinePlay}

__all__ = ["PLAYS", "SHAPES", "LeadPlay", "LeadShape", "OfficeMap", "PipelinePlay", "PipelineShape", "Rect", "TeamShape"]
