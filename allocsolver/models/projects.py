from enum import StrEnum

from pydantic import BaseModel, model_validator

from .calendar import Month


class RateType(StrEnum):
    PROJECT = "project"
    OH = "oh"
    FEE = "fee"


class RateStructure(BaseModel):
    """Selects exactly one wrap rate — `03-data-model.md`'s resolution of [OPEN-2]."""

    structure_id: str
    rate_type: RateType


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    CLOSED = "closed"


class Project(BaseModel):
    project_id: str
    name: str
    pop_start: Month
    pop_end: Month
    rate_structure: str  # RateStructure.structure_id
    labor_budget: float = 0.0
    """The total funded labor amount for the whole PoP — the fixed ceiling
    `targets.labor_spend_target` is planned (and reforecast) against. Distinct from the
    monthly targets themselves: reforecasting redistributes *how* this total lands
    across months, but conserves the total itself (see the reforecast conservation
    test in `04-solver-design.md`)."""
    travel_budget: float = 0.0
    odc_budget: float = 0.0
    status: ProjectStatus = ProjectStatus.ACTIVE

    @model_validator(mode="after")
    def _check_pop(self) -> "Project":
        if self.pop_end < self.pop_start:
            raise ValueError(f"{self.project_id}: pop_end precedes pop_start")
        return self

    def months(self) -> list[Month]:
        return Month.range(self.pop_start, self.pop_end)
