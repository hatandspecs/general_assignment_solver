from pydantic import BaseModel, Field, model_validator

from .calendar import Month


class Person(BaseModel):
    person_id: str
    name: str
    active_from: Month
    active_to: Month | None = None
    soft_max_concurrent_projects: int = Field(default=2, ge=0)
    hard_max_concurrent_projects: int = Field(default=4, ge=0)

    @model_validator(mode="after")
    def _check_limits(self) -> "Person":
        if self.soft_max_concurrent_projects > self.hard_max_concurrent_projects:
            raise ValueError(
                f"{self.person_id}: soft_max_concurrent_projects "
                f"({self.soft_max_concurrent_projects}) exceeds "
                f"hard_max_concurrent_projects ({self.hard_max_concurrent_projects})"
            )
        if self.active_to is not None and self.active_to < self.active_from:
            raise ValueError(f"{self.person_id}: active_to precedes active_from")
        return self

    def is_active(self, month: Month) -> bool:
        if month < self.active_from:
            return False
        return self.active_to is None or month <= self.active_to
