"""Month value object: the atomic time unit throughout this schema (`03-data-model.md`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import total_ordering
from typing import Any

import holidays
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


@total_ordering
@dataclass(frozen=True, slots=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"month must be 1-12, got {self.month}")

    @classmethod
    def parse(cls, text: str) -> "Month":
        year_str, month_str = text.split("-")
        return cls(int(year_str), int(month_str))

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def __repr__(self) -> str:
        return f"Month('{self}')"

    def __lt__(self, other: "Month") -> bool:
        return (self.year, self.month) < (other.year, other.month)

    def as_of_index(self) -> int:
        """Zero-based index from an arbitrary epoch, for arithmetic."""
        return self.year * 12 + (self.month - 1)

    @classmethod
    def from_index(cls, index: int) -> "Month":
        return cls(index // 12, index % 12 + 1)

    def add(self, n: int) -> "Month":
        return Month.from_index(self.as_of_index() + n)

    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    def is_ufy_start(self) -> bool:
        """True if this month opens a corporate fiscal year (UFY), which starts July 1."""
        return self.month == 7

    def ufy(self) -> int:
        """The UFY this month falls in, named by the calendar year it starts in."""
        return self.year if self.month >= 7 else self.year - 1

    @classmethod
    def range(cls, start: "Month", end_inclusive: "Month") -> list["Month"]:
        if end_inclusive < start:
            return []
        return [cls.from_index(i) for i in range(start.as_of_index(), end_inclusive.as_of_index() + 1)]

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: Any) -> "Month":
            return value if isinstance(value, Month) else Month.parse(str(value))

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )


_US_FEDERAL_HOLIDAYS = holidays.US(years=range(2000, 2100))


def workable_hours(month: Month, hours_per_workday: float = 8.0) -> float:
    """Standard workable hours in a month: weekdays minus US federal holidays, at 8h/day.

    This is the `wrap_rates.workable_hours` reference figure (`03-data-model.md`) —
    a global, month-level standard, distinct from any one person's `capacity.available_hours`.
    """
    year, month = month.year, month.month
    next_month = Month(year, month).add(1).first_day()
    day = Month(year, month).first_day()
    workdays = 0
    while day < next_month:
        if day.weekday() < 5 and day not in _US_FEDERAL_HOLIDAYS:
            workdays += 1
        day = date.fromordinal(day.toordinal() + 1)
    return workdays * hours_per_workday
