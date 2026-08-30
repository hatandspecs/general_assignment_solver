from enum import StrEnum

from pydantic import BaseModel, Field

from .calendar import Month


class TargetType(StrEnum):
    SOFT = "soft"
    HARD = "hard"


class Target(BaseModel):
    project_id: str
    month: Month
    labor_spend_target: float = Field(ge=0)
    target_tolerance: float | None = None
    target_type: TargetType = TargetType.SOFT
