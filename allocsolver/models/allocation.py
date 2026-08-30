from pydantic import BaseModel, Field

from .calendar import Month


class AllocationRow(BaseModel):
    project_id: str
    person_id: str
    month: Month
    hours_assigned: float = Field(ge=0, default=0)
    hours_actual: float | None = Field(ge=0, default=None)
    locked: bool = False
    lock_note: str | None = None
    solve_id: str | None = None


class AllocationWrite(BaseModel):
    """The solver's write allowlist — `hours_assigned` only (`02-architecture.md`)."""

    project_id: str
    person_id: str
    month: Month
    hours_assigned: float = Field(ge=0)
    solve_id: str
