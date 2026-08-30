"""Synthetic actuals — a fixture dataset shaped like the eventual real timekeeping
export, for development and simulation before real integration access exists
(`06-code-structure-and-dependencies.md`).

Used by the `advance-month` CLI command to "simulate worker activity" for a month:
perturbing that month's solved `hours_assigned` to produce a plausible `hours_actual`,
standing in for a real timekeeping import.

Business philosophy behind the numbers here (from the user directly, not derived):
a project should never be planned to finish with money left on the table. Staff get
held onto or pulled in part-time from elsewhere in the org specifically to spend a
project's `labor_budget` out fully, landing at most 0.1%-1% *over* it, never under.
So: ordinary months carry tight, slightly overspend-leaning noise (no reason for a
big swing most months), and a project's *final* PoP month true's up to close
whatever gap remains between cumulative actual spend and `labor_budget` — capped by
real capacity, since that's a physical limit synthetic noise can't wish away. When
capacity can't support the true-up, that's a real staffing shortfall, and it's
exactly what `reports/staffing_balance.py` is for surfacing, not something to paper
over here.
"""

import random
from collections import defaultdict

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.allocation import AllocationRow
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan

NORMAL_NOISE = (0.98, 1.03)  # tight, and leaning slightly toward overspend, not under
FINAL_MONTH_OVERSPEND = (0.001, 0.01)  # true-up target: 0.1% to 1% over labor_budget


def simulate_actuals_for_month(
    plan: Plan,
    month: Month,
    hours_assigned: dict[Cell, float],
    rng: random.Random,
) -> list[AllocationRow]:
    """Perturbs a solved month's `hours_assigned` into plausible `hours_actual`.

    A person's simultaneous projects share one monthly capacity, so cell-by-cell
    noise is generated per person, then scaled down together if their sum would
    oversubscribe the month — generating each cell independently can otherwise
    silently make next month's solve infeasible against its own "actuals".
    """
    by_person: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (project_id, person_id, m), hours in hours_assigned.items():
        if m != month or hours <= 1e-9:
            continue
        by_person[person_id].append((project_id, hours))

    trueup_factor = _trueup_factors_for_ending_projects(plan, month, hours_assigned, rng)

    rows = []
    for person_id, project_hours in by_person.items():
        cap = plan.capacity_of(person_id, month).available_hours
        naive_actual = {}
        for project_id, hours in project_hours:
            if project_id in trueup_factor:
                naive_actual[project_id] = hours * trueup_factor[project_id]
            else:
                naive_actual[project_id] = hours * rng.uniform(*NORMAL_NOISE)
        total = sum(naive_actual.values())
        # This is a real physical limit, unlike the removed hard_max clamp: a
        # person only has so many hours in a month, however staffing is arranged.
        # If this scale-down bites on a true-up project, the true-up under-delivers
        # — the staffing balance report is where that shortfall should be caught.
        scale = min(1.0, cap / total) if total > 0 else 1.0

        for project_id, hours in project_hours:
            actual = round(naive_actual[project_id] * scale, 2)
            rows.append(
                AllocationRow(
                    project_id=project_id,
                    person_id=person_id,
                    month=month,
                    hours_assigned=round(hours, 2),
                    hours_actual=actual,
                    locked=False,
                    solve_id="simulated-actuals",
                )
            )
    return rows


def _trueup_factors_for_ending_projects(
    plan: Plan, month: Month, hours_assigned: dict[Cell, float], rng: random.Random
) -> dict[str, float]:
    """For each project whose PoP ends this month, the multiplier this month's
    planned hours need scaling by so cumulative actual cost lands within
    `FINAL_MONTH_OVERSPEND` of `labor_budget` — never short of it.
    """
    ending = [p for p in plan.projects if p.pop_end == month]
    if not ending:
        return {}

    factors: dict[str, float] = {}
    for project in ending:
        cumulative_actual_cost = sum(
            a.hours_actual * loaded_rate(plan, a.person_id, a.month, project.project_id)
            for a in plan.allocation
            if a.project_id == project.project_id and a.hours_actual is not None
        )
        this_month_planned_cost = sum(
            hours * loaded_rate(plan, w, m, p)
            for (p, w, m), hours in hours_assigned.items()
            if p == project.project_id and m == month
        )
        if this_month_planned_cost <= 0:
            continue

        overspend = rng.uniform(*FINAL_MONTH_OVERSPEND)
        target_total = project.labor_budget * (1 + overspend)
        remaining_needed_cost = target_total - cumulative_actual_cost
        factors[project.project_id] = max(0.0, remaining_needed_cost / this_month_planned_cost)

    return factors
