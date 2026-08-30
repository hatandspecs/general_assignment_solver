"""Staff spend-capacity balance assessment.

The business philosophy behind this (from the user): staff get held onto or pulled
in part-time from elsewhere in the org specifically so every project's `labor_budget`
gets spent out fully. That only works if there's actually enough total labor spend
capacity across the portfolio and horizon to cover it. This report is the check:
does total available spend capacity roughly match total spend demand, month by
month and overall — so a planner can see, concretely, whether they need to find
outside-portfolio work for surplus capacity, or pull in staff from outside the
current pool to cover a shortfall.

Measured in dollars, not raw hours: not all person-hours are equivalent — salary,
and which wrap rate applies, both vary person to person and month to month, so an
hour of capacity and an hour of demand aren't fungible units to compare directly.

This is an assessment, not a remediation — it surfaces the imbalance; finding the
actual outside work or the actual extra staff is the planner's call, same as an
infeasibility report names the binding constraint but doesn't relax it for you.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def _capacity_dollar_rate(plan: Plan, person_id: str, month: Month) -> float:
    """Values raw capacity at the standard "direct" project rate — most workers
    charge this; capacity itself isn't tied to any one project's rate_structure, so
    this is the reference rate for "what this person's available hours are worth if
    put to typical use," not a claim about which project they'll actually work on.
    """
    rate = plan.rate(person_id, month)
    wrap = plan.wrap_rate(month)
    base_hourly = rate.annual_salary / 12 / wrap.workable_hours
    return base_hourly * wrap.project_wrap_rate


@dataclass(frozen=True, slots=True)
class MonthBalance:
    month: Month
    capacity_dollars: float
    demand_dollars: float

    @property
    def balance_dollars(self) -> float:
        """Positive: surplus spend capacity (find outside-portfolio work).
        Negative: shortfall (pull in staff from elsewhere)."""
        return self.capacity_dollars - self.demand_dollars


def staffing_balance(plan: Plan, hours_assigned: dict[Cell, float] | None = None) -> list[MonthBalance]:
    """One row per month in the horizon.

    Pass `hours_assigned` (a solved plan) for the real demand; omit it to use
    `bounds.soft_max` as the planner's *intended* demand before any solve exists —
    e.g. right after `generate_data.py`, as an early sanity check.
    """
    capacity_by_month: dict[Month, float] = {}
    for c in plan.capacity:
        rate = _capacity_dollar_rate(plan, c.person_id, c.month)
        capacity_by_month[c.month] = capacity_by_month.get(c.month, 0.0) + c.available_hours * rate

    demand_by_month: dict[Month, float] = {}
    if hours_assigned is not None:
        for (p, w, m), hours in hours_assigned.items():
            demand_by_month[m] = demand_by_month.get(m, 0.0) + hours * loaded_rate(plan, w, m, p)
    else:
        for b in plan.bounds:
            if b.eligible:
                demand_by_month[b.month] = demand_by_month.get(b.month, 0.0) + b.soft_max * loaded_rate(
                    plan, b.person_id, b.month, b.project_id
                )

    return [
        MonthBalance(
            month=month,
            capacity_dollars=capacity_by_month.get(month, 0.0),
            demand_dollars=demand_by_month.get(month, 0.0),
        )
        for month in plan.horizon()
    ]


def export_staffing_balance(
    plan: Plan, out_path: Path, hours_assigned: dict[Cell, float] | None = None
) -> None:
    balances = staffing_balance(plan, hours_assigned)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["month", "capacity_dollars", "demand_dollars", "balance_dollars", "status"])
        for b in balances:
            status = (
                "surplus" if b.balance_dollars > 1e-6 else ("shortfall" if b.balance_dollars < -1e-6 else "balanced")
            )
            writer.writerow(
                [
                    str(b.month),
                    round(b.capacity_dollars, 2),
                    round(b.demand_dollars, 2),
                    round(b.balance_dollars, 2),
                    status,
                ]
            )

        total_capacity = sum(b.capacity_dollars for b in balances)
        total_demand = sum(b.demand_dollars for b in balances)
        writer.writerow([])
        writer.writerow(
            ["TOTAL", round(total_capacity, 2), round(total_demand, 2), round(total_capacity - total_demand, 2), ""]
        )
