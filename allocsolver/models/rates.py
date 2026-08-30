from pydantic import BaseModel, Field

from .calendar import Month


class Rate(BaseModel):
    """Per person, per month. Resolved [OPEN-3]: annual_salary is the only stored input."""

    person_id: str
    month: Month
    annual_salary: float = Field(gt=0)


class WrapRate(BaseModel):
    """Global reference data, not per person (`03-data-model.md`)."""

    month: Month
    workable_hours: float = Field(gt=0)
    project_wrap_rate: float = Field(gt=0)
    oh_wrap_rate: float = Field(gt=0)
    fee_wrap_rate: float = Field(gt=0)
