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

Demand is deliberately each month's total `labor_spend_target` across projects —
what the projects need spent — not realized/solved hours. Realized hours are
physically capped at real capacity (C3: nobody can be assigned more hours than
they have), so demand computed from them can never exceed capacity by
construction — a genuine shortfall would be mathematically impossible to ever
show, which defeats the report's own purpose. Targets aren't capacity-capped, so
they can genuinely run ahead of capacity: that gap *is* the signal to pull in
staff from outside the pool, the same real pattern this report exists to surface.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

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


def staffing_balance(plan: Plan) -> list[MonthBalance]:
    """One row per month in the horizon. See the module docstring for why demand
    comes from `plan.targets` rather than any solved/realized hours."""
    capacity_by_month: dict[Month, float] = {}
    for c in plan.capacity:
        rate = _capacity_dollar_rate(plan, c.person_id, c.month)
        capacity_by_month[c.month] = capacity_by_month.get(c.month, 0.0) + c.available_hours * rate

    demand_by_month: dict[Month, float] = {}
    for t in plan.targets:
        demand_by_month[t.month] = demand_by_month.get(t.month, 0.0) + t.labor_spend_target

    return [
        MonthBalance(
            month=month,
            capacity_dollars=capacity_by_month.get(month, 0.0),
            demand_dollars=demand_by_month.get(month, 0.0),
        )
        for month in plan.horizon()
    ]


def export_staffing_balance(plan: Plan, out_path: Path) -> None:
    balances = staffing_balance(plan)
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
