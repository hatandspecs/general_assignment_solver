"""Report row computation for the widget's report buttons.

Deliberately its own long/tabular shape (one row per project-month, one row per
worker-project-month, ...) rather than reusing `allocsolver.reports.exports`'s
metadata-block-plus-matrix CSV writers verbatim: that shape is right for a
standalone CSV file, but awkward for a Grist table a planner wants to sort and
filter. The underlying figures are computed the same way (`loaded_rate`, the same
cumulative/"as of" logic as `export_budget_summary`) — just emitted as rows
instead of formatted columns. `05-interfaces.md`'s three CSV export formats
remain available unchanged via the `allocsolver` CLI against the same data.
"""

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.reports.staffing_balance import staffing_balance


def work_assignment_rows(plan: Plan, hours_assigned: dict[Cell, float], month: Month) -> list[dict]:
    rows = []
    for (p, w, m), hours in hours_assigned.items():
        if m != month or hours <= 1e-9:
            continue
        rows.append(
            {
                "worker_name": plan.person(w).name,
                "project_name": plan.project(p).name,
                "month": str(month),
                "hours_assigned": round(hours, 2),
            }
        )
    rows.sort(key=lambda r: (r["worker_name"], r["project_name"]))
    return rows


def variance_rows_for_closed_month(plan: Plan, month: Month) -> list[dict]:
    rows = []
    for a in plan.allocation:
        if a.month != month or a.hours_actual is None:
            continue
        rows.append(
            {
                "worker_name": plan.person(a.person_id).name,
                "project_name": plan.project(a.project_id).name,
                "month": str(month),
                "hours_assigned": round(a.hours_assigned, 2),
                "actual_hours": round(a.hours_actual, 2),
                "delta": round(a.hours_assigned - a.hours_actual, 2),
            }
        )
    rows.sort(key=lambda r: (r["worker_name"], r["project_name"]))
    return rows


def budget_summary_rows(
    plan: Plan, hours_assigned: dict[Cell, float], project_id: str, as_of_month: Month | None
) -> list[dict]:
    project = plan.project(project_id)
    months = [m for m in project.months() if m in set(plan.horizon())]
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}

    planned_by_month: dict[Month, float] = {}
    actual_by_month: dict[Month, float] = {}
    for m in months:
        planned = 0.0
        actual = 0.0
        closed_people_this_month: set[str] = set()
        for (p, w, m2), alloc in alloc_index.items():
            if p == project_id and m2 == m and alloc.hours_actual is not None:
                planned += alloc.hours_assigned * loaded_rate(plan, w, m, p)
                actual += alloc.hours_actual * loaded_rate(plan, w, m, p)
                closed_people_this_month.add(w)
        for (p, w, m2), hours in hours_assigned.items():
            if p == project_id and m2 == m and w not in closed_people_this_month:
                planned += hours * loaded_rate(plan, w, m2, p)
        planned_by_month[m] = planned
        actual_by_month[m] = actual

    total_budget = project.labor_budget
    running_planned = 0.0
    running_actual = 0.0
    rows = []
    for m in months:
        running_planned += planned_by_month[m]
        running_actual += actual_by_month[m]
        known = as_of_month is None or m < as_of_month
        rows.append(
            {
                "project_id": project_id,
                "project_name": project.name,
                "month": str(m),
                "planned_spend": round(planned_by_month[m], 2),
                "actual_spend": round(actual_by_month[m], 2) if known else None,
                "delta": round(planned_by_month[m] - actual_by_month[m], 2) if known else None,
                "cumulative_planned_spend": round(running_planned, 2),
                "cumulative_actual_spend": round(running_actual, 2) if known else None,
                "planned_funds_remaining": round(total_budget - running_planned, 2),
                "actual_funds_remaining": round(total_budget - running_actual, 2) if known else None,
            }
        )
    return rows


def staffing_balance_rows(plan: Plan) -> list[dict]:
    rows = []
    for b in staffing_balance(plan):
        status = "surplus" if b.balance_dollars > 1e-6 else ("shortfall" if b.balance_dollars < -1e-6 else "balanced")
        rows.append(
            {
                "month": str(b.month),
                "capacity_dollars": round(b.capacity_dollars, 2),
                "demand_dollars": round(b.demand_dollars, 2),
                "balance_dollars": round(b.balance_dollars, 2),
                "status": status,
            }
        )
    return rows


def solve_diff_rows(pre_assignments: list[Bounds], hours_assigned: dict[Cell, float], month: Month) -> list[dict]:
    """Compares each pre-assignment's requested `soft_max` against the solver's
    actual `hours_assigned`, for one month — the "see how the solution differs
    from the pre-assignment" view."""
    pre_by_cell = {(b.project_id, b.person_id, b.month): b.soft_max for b in pre_assignments if b.eligible and b.month == month}
    solved_by_cell = {(p, w, m): h for (p, w, m), h in hours_assigned.items() if m == month and h > 1e-9}

    rows = []
    for cell in set(pre_by_cell) | set(solved_by_cell):
        p, w, m = cell
        pre_hours = pre_by_cell.get(cell)
        solved_hours = solved_by_cell.get(cell)
        if pre_hours is not None and solved_hours is not None:
            delta = round(solved_hours - pre_hours, 2)
            status = "matched" if abs(delta) < 0.01 else "solver_adjusted"
        elif pre_hours is not None:
            delta = round(-pre_hours, 2)
            status = "pre_assignment_unused"
        else:
            delta = round(solved_hours, 2)
            status = "solver_only"
        rows.append(
            {
                "project_id": p,
                "person_id": w,
                "month": str(m),
                "pre_assigned_hours": round(pre_hours, 2) if pre_hours is not None else None,
                "solved_hours": round(solved_hours, 2) if solved_hours is not None else None,
                "delta": delta,
                "status": status,
            }
        )
    rows.sort(key=lambda r: (r["status"], r["project_id"], r["person_id"]))
    return rows


def rows_to_csv(rows: list[dict], columns: list[str]) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()
