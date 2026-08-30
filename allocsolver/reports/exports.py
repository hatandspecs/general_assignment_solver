"""The three confirmed exports — `05-interfaces.md`, "Exports".

Workforce, planners, and analysts see fundamentally different things (`01-system-overview.md`).
The workforce sheet is a hard column allowlist: cost, rate, and salary never appear in it.
"""

import csv
from pathlib import Path

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def export_workforce_sheet(
    plan: Plan, hours_assigned: dict[Cell, float], month: Month, out_path: Path
) -> None:
    """Sent to the workforce by the 1st of each month. Hours only — no cost, rate, or salary."""
    rows = [
        (plan.person(w).name, plan.project(p).name, round(hours, 2))
        for (p, w, m), hours in hours_assigned.items()
        if m == month and hours > 1e-9
    ]
    rows.sort()
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["worker_name", "project_name", "hours_assigned"])
        writer.writerows(rows)


def export_variance_sheet(plan: Plan, hours_assigned: dict[Cell, float], out_path: Path) -> None:
    """For planners. One row per (worker, project, month) with actuals recorded."""
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}
    rows = []
    for cell, hours in hours_assigned.items():
        p, w, m = cell
        alloc = alloc_index.get(cell)
        actual = alloc.hours_actual if alloc else None
        if actual is None:
            continue
        rows.append(
            (
                plan.person(w).name,
                plan.project(p).name,
                str(m),
                round(hours, 2),
                round(actual, 2),
                round(hours - actual, 2),
            )
        )
    rows.sort()
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["worker_name", "project_name", "month", "hours_assigned", "actual_hours", "delta"])
        writer.writerows(rows)


def export_budget_summary(
    plan: Plan, hours_assigned: dict[Cell, float], project_id: str, out_path: Path
) -> None:
    """For planners, one per project: metadata block plus a monthly matrix."""
    project = plan.project(project_id)
    months = [m for m in project.months() if m in set(plan.horizon())]
    target_by_month = {t.month: t.labor_spend_target for t in plan.targets if t.project_id == project_id}
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}

    planned_by_month: dict[Month, float] = {}
    actual_by_month: dict[Month, float] = {}
    for m in months:
        planned = sum(
            hours * loaded_rate(plan, w, m2, p)
            for (p, w, m2), hours in hours_assigned.items()
            if p == project_id and m2 == m
        )
        actual = 0.0
        for (p, w, m2), alloc in alloc_index.items():
            if p == project_id and m2 == m and alloc.hours_actual is not None:
                actual += alloc.hours_actual * loaded_rate(plan, w, m, p)
        planned_by_month[m] = planned
        actual_by_month[m] = actual

    total_target = sum(target_by_month.get(m, 0.0) for m in months)
    planned_to_date = sum(planned_by_month.values())
    actual_to_date = sum(actual_by_month.values())

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["project_name", project.name])
        writer.writerow(["pop_start", str(project.pop_start)])
        writer.writerow(["pop_end", str(project.pop_end)])
        writer.writerow(["budget_expended_planned", round(planned_to_date, 2)])
        writer.writerow(["budget_expended_actual", round(actual_to_date, 2)])
        writer.writerow(["budget_remaining_planned", round(total_target - planned_to_date, 2)])
        writer.writerow(["budget_remaining_actual", round(total_target - actual_to_date, 2)])
        writer.writerow([])
        writer.writerow(["month", *[str(m) for m in months]])
        writer.writerow(["planned_spend", *[round(planned_by_month[m], 2) for m in months]])
        writer.writerow(["actual_spend", *[round(actual_by_month[m], 2) for m in months]])
        writer.writerow(
            ["delta", *[round(planned_by_month[m] - actual_by_month[m], 2) for m in months]]
        )
