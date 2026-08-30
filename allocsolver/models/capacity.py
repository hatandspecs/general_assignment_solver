from pydantic import BaseModel, Field

from .calendar import Month


class Capacity(BaseModel):
    person_id: str
    month: Month
    available_hours: float = Field(ge=0)
