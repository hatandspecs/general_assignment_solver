"""The single cost composition function — `03-data-model.md`'s "Rate composition" section.

Resolved [OPEN-2]/[OPEN-3]: selection, not stacking; annual_salary is the only entered rate input.
"""

from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.models.projects import RateType


def loaded_rate(plan: Plan, person_id: str, month: Month, project_id: str) -> float:
    """R[p,w,m]: the loaded hourly cost of `person_id` on `project_id` in `month`."""
    rate = plan.rate(person_id, month)
    wrap = plan.wrap_rate(month)
    project = plan.project(project_id)
    structure = plan.rate_structure(project.rate_structure)

    base_hourly = rate.annual_salary / 12 / wrap.workable_hours

    match structure.rate_type:
        case RateType.PROJECT:
            multiplier = wrap.project_wrap_rate
        case RateType.OH:
            multiplier = wrap.oh_wrap_rate
        case RateType.FEE:
            multiplier = wrap.fee_wrap_rate
        case _:  # pragma: no cover - StrEnum exhausts these
            raise ValueError(f"unknown rate_type {structure.rate_type}")

    return base_hourly * multiplier
