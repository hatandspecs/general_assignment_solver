"""Task view, resource view pivots — `03-data-model.md`. Neither is a stored table."""

from dataclasses import dataclass

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


@dataclass(frozen=True, slots=True)
class ViewRow:
    project_id: str
    person_id: str
    month: Month
    hard_min: float
    soft_min: float
    soft_max: float
    hard_max: float
    hours_assigned: float
    assigned_cost: float
    hours_actual: float | None
    actual_cost: float | None
    delta_hours: float | None
    delta_cost: float | None


def build_rows(plan: Plan, hours_assigned: dict[Cell, float]) -> list[ViewRow]:
    """The row set both the task view and resource view pivot over."""
    bounds_index = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}
    rows: list[ViewRow] = []

    for cell, hours in hours_assigned.items():
        p, w, m = cell
        b = bounds_index.get(cell)
        rate = loaded_rate(plan, w, m, p)
        assigned_cost = hours * rate
        alloc = alloc_index.get(cell)
        hours_actual = alloc.hours_actual if alloc else None
        actual_cost = hours_actual * rate if hours_actual is not None else None
        rows.append(
            ViewRow(
                project_id=p,
                person_id=w,
                month=m,
                hard_min=b.hard_min if b else 0.0,
                soft_min=b.soft_min if b else 0.0,
                soft_max=b.soft_max if b else 0.0,
                hard_max=b.hard_max if b else 0.0,
                hours_assigned=hours,
                assigned_cost=assigned_cost,
                hours_actual=hours_actual,
                actual_cost=actual_cost,
                delta_hours=(hours - hours_actual) if hours_actual is not None else None,
                delta_cost=(assigned_cost - actual_cost) if actual_cost is not None else None,
            )
        )
    return rows


def group_by_project(rows: list[ViewRow]) -> dict[str, list[ViewRow]]:
    grouped: dict[str, list[ViewRow]] = {}
    for row in rows:
        grouped.setdefault(row.project_id, []).append(row)
    return grouped


def group_by_person(rows: list[ViewRow]) -> dict[str, list[ViewRow]]:
    grouped: dict[str, list[ViewRow]] = {}
    for row in rows:
        grouped.setdefault(row.person_id, []).append(row)
    return grouped


@dataclass(frozen=True, slots=True)
class Totals:
    hours_assigned: float
    assigned_cost: float
    hours_actual: float | None
    actual_cost: float | None
    delta_hours: float | None
    delta_cost: float | None


def totals_of(rows: list[ViewRow]) -> Totals:
    has_actuals = any(r.hours_actual is not None for r in rows)
    return Totals(
        hours_assigned=sum(r.hours_assigned for r in rows),
        assigned_cost=sum(r.assigned_cost for r in rows),
        hours_actual=sum(r.hours_actual or 0.0 for r in rows) if has_actuals else None,
        actual_cost=sum(r.actual_cost or 0.0 for r in rows) if has_actuals else None,
        delta_hours=sum(r.delta_hours or 0.0 for r in rows) if has_actuals else None,
        delta_cost=sum(r.delta_cost or 0.0 for r in rows) if has_actuals else None,
    )


def assigned_fte(plan: Plan, hours_assigned: dict[Cell, float], person_id: str, month: Month) -> float:
    """`assigned_fte[w,m]` — the reporting-side check for [OPEN-7], never a solver input."""
    total_hours = sum(h for (_, w, m), h in hours_assigned.items() if w == person_id and m == month)
    cap = plan.capacity_of(person_id, month).available_hours
    return total_hours / cap if cap else 0.0
