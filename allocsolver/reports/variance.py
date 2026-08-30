"""Spend variance derived value — `03-data-model.md`: plan against funding target.

Distinct from `reforecast/variance.py`'s target-vs-actual variance, which drives
redistribution; this is the plan-vs-target number shown in the views.
"""

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def spend_variance(
    plan: Plan, project_id: str, month: Month, hours_assigned: dict[Cell, float]
) -> float:
    """`assigned_cost - target`, at the project x month level."""
    target = next((t for t in plan.targets if t.project_id == project_id and t.month == month), None)
    if target is None:
        return 0.0
    assigned_cost = sum(
        hours * loaded_rate(plan, w, m, p)
        for (p, w, m), hours in hours_assigned.items()
        if p == project_id and m == month
    )
    return assigned_cost - target.labor_spend_target
