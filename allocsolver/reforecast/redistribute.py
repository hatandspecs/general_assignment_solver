"""Spreads variance across a project's remaining open months — resolved `[OPEN-11]`.

Proportional to each remaining month's existing target share, preserving the plan's
relative shape rather than flattening it.
"""

from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def remaining_open_months(plan: Plan, project_id: str, after: Month) -> list[Month]:
    project = plan.project(project_id)
    horizon = set(plan.horizon())
    return [m for m in project.months() if m > after and m in horizon]


def proportional_share(
    plan: Plan, project_id: str, variance: float, months: list[Month]
) -> dict[Month, float]:
    if not months:
        return {}

    target_by_month = {
        t.month: t.labor_spend_target for t in plan.targets if t.project_id == project_id
    }
    weights = {m: target_by_month.get(m, 0.0) for m in months}
    total_weight = sum(weights.values())

    if total_weight <= 0:
        even = variance / len(months)
        return dict.fromkeys(months, even)

    return {m: variance * (weights[m] / total_weight) for m in months}
