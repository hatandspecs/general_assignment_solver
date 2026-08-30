"""Constraints C1 through C7 — `04-solver-design.md`, "Constraints"."""

from collections import defaultdict

from ortools.linear_solver import pywraplp

from allocsolver.costing.masks import Cell
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.models.targets import TargetType

from .variables import Variables


def _group_by_person_month(cells: list[Cell]) -> dict[tuple[str, Month], list[Cell]]:
    grouped: dict[tuple[str, Month], list[Cell]] = defaultdict(list)
    for p, w, m in cells:
        grouped[(w, m)].append((p, w, m))
    return grouped


def _group_by_project_month(cells: list[Cell]) -> dict[tuple[str, Month], list[Cell]]:
    grouped: dict[tuple[str, Month], list[Cell]] = defaultdict(list)
    for p, w, m in cells:
        grouped[(p, m)].append((p, w, m))
    return grouped


def add_constraints(
    solver: pywraplp.Solver,
    plan: Plan,
    v: Variables,
    cells: list[Cell],
    fixed: set[Cell],
    R: dict[Cell, float],
    baseline: dict[Cell, float],
) -> None:
    bounds_index = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
    by_person_month = _group_by_person_month(cells)
    by_project_month = _group_by_project_month(cells)

    # C1 + C2: semi-continuous assignment, soft bounds with elastic slack.
    # Skipped for cells in `fixed`: those are handled purely by C5's bound-fixing
    # (`apply_fixed`, below) — a closed month's actual is historical fact, not a new
    # assignment to bound against hard_max/soft_max. Applying C1/C2 to an already-
    # fixed cell would re-litigate what already happened, and can conflict outright
    # (e.g. a true-up actual that landed a hair above the cell's hard_max) with no
    # way to satisfy both — a manufactured infeasibility, not a real one.
    for cell in cells:
        if cell in fixed:
            continue
        b = bounds_index[cell]
        x, y, u, o = v.x[cell], v.y[cell], v.u[cell], v.o[cell]
        solver.Add(x >= b.hard_min * y)
        solver.Add(x <= b.hard_max * y)
        solver.Add(x + u >= b.soft_min * y)
        solver.Add(x - o <= b.soft_max * y)

    # C3: capacity, written as an equality with an explicit idle term.
    for (w, m), idle_var in v.idle.items():
        cells_wm = by_person_month.get((w, m), [])
        total = solver.Sum([v.x[c] for c in cells_wm]) if cells_wm else 0
        cap = plan.capacity_of(w, m).available_hours
        solver.Add(total + idle_var == cap)

    # C4: spend target, plus a ceiling for hard targets, plus tolerance-banded penalty vars.
    for t in plan.targets:
        key = (t.project_id, t.month)
        if key not in v.dp:
            continue
        cells_pm = by_project_month.get(key, [])
        spend = solver.Sum([R[c] * v.x[c] for c in cells_pm]) if cells_pm else 0
        dp_var, dm_var = v.dp[key], v.dm[key]
        solver.Add(spend - t.labor_spend_target == dp_var - dm_var)
        if t.target_type == TargetType.HARD:
            solver.Add(spend <= t.labor_spend_target)

        tol = t.target_tolerance or 0.0
        dp_prime, dm_prime = v.dp_prime[key], v.dm_prime[key]
        solver.Add(dp_prime >= dp_var - tol)
        solver.Add(dm_prime >= dm_var - tol)

    # C5 (fixed cells) is applied via `apply_fixed()` as bound-fixing, not a constraint row here.

    # C6: fragmentation, two-tiered.
    for (w, m), frag_var in v.frag.items():
        person = plan.person(w)
        cells_wm = by_person_month.get((w, m), [])
        count = solver.Sum([v.y[c] for c in cells_wm]) if cells_wm else 0
        solver.Add(count <= person.hard_max_concurrent_projects)
        solver.Add(count <= person.soft_max_concurrent_projects + frag_var)

    # C7: churn linearization, for cells not fixed.
    for cell, cp_var in v.cp.items():
        cm_var = v.cm[cell]
        base_val = baseline.get(cell, 0.0)
        solver.Add(v.x[cell] - base_val == cp_var - cm_var)


def apply_fixed(v: Variables, fix_values: dict[Cell, float]) -> None:
    """C5, the bound-fixing half: pin `x`/`y` for locked or closed-month cells."""
    for cell, value in fix_values.items():
        v.x[cell].SetBounds(value, value)
        v.y[cell].SetBounds(1, 1) if value > 0 else v.y[cell].SetBounds(0, 0)
