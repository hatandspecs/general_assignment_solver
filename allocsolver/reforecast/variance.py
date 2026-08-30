"""Target-vs-actual variance for a closed month — `04-solver-design.md`, "Reforecasting"."""

from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def actual_cost(plan: Plan, project_id: str, month: Month) -> float:
    total = 0.0
    for row in plan.allocation:
        if row.project_id == project_id and row.month == month and row.hours_actual is not None:
            total += row.hours_actual * loaded_rate(plan, row.person_id, month, project_id)
    return total


def target_variance(plan: Plan, project_id: str, month: Month) -> float:
    """`T[p,M] - actual_cost[p,M]`. Positive means underspent, negative overspent."""
    target = next((t for t in plan.targets if t.project_id == project_id and t.month == month), None)
    if target is None:
        raise ValueError(f"no target for {project_id} in {month}")
    return target.labor_spend_target - actual_cost(plan, project_id, month)
