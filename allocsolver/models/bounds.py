from pydantic import BaseModel, Field, model_validator

from .calendar import Month


class Bounds(BaseModel):
    """Resolved [OPEN-7]: hours, not FTE fraction. Resolved [OPEN-5]: per month."""

    project_id: str
    person_id: str
    month: Month
    hard_min: float = Field(ge=0, default=0)
    soft_min: float = Field(ge=0, default=0)
    soft_max: float = Field(ge=0)
    hard_max: float = Field(ge=0)
    eligible: bool = True

    @model_validator(mode="after")
    def _check_order(self) -> "Bounds":
        if not (self.hard_min <= self.soft_min <= self.soft_max <= self.hard_max):
            raise ValueError(
                f"{self.project_id}/{self.person_id}/{self.month}: "
                f"bounds out of order: {self.hard_min} <= {self.soft_min} <= "
                f"{self.soft_max} <= {self.hard_max} does not hold"
            )
        return self
