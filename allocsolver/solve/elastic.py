"""Always-feasible relaxation — `04-solver-design.md`, "Infeasibility diagnostics"."""

from dataclasses import dataclass

from ortools.linear_solver import pywraplp

from allocsolver.costing.masks import Cell, eligible_cells
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.models.targets import TargetType

from .build import fixed_cells_and_values
from .constraints import _group_by_person_month, _group_by_project_month
from .variables import Variables, build_variables

PersonMonth = tuple[str, Month]
ProjectMonth = tuple[str, Month]


@dataclass
class ElasticBundle:
    solver: pywraplp.Solver
    variables: Variables
    s_hmin: dict[Cell, pywraplp.Variable]
    s_hmax: dict[Cell, pywraplp.Variable]
    s_cap: dict[PersonMonth, pywraplp.Variable]
    s_target: dict[ProjectMonth, pywraplp.Variable]


def build_elastic_model(plan: Plan) -> ElasticBundle:
    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        raise RuntimeError("OR-Tools could not create a SCIP solver instance")

    cells = eligible_cells(plan)
    fixed_values = fixed_cells_and_values(plan, cells)
    fixed = set(fixed_values.keys())
    rates = {cell: loaded_rate(plan, cell[1], cell[2], cell[0]) for cell in cells}

    v = build_variables(solver, plan, cells, fixed)
    bounds_index = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
    by_person_month = _group_by_person_month(cells)
    by_project_month = _group_by_project_month(cells)
    inf = solver.infinity()

    # C1': hard min/max, relaxed with slack.
    s_hmin: dict[Cell, pywraplp.Variable] = {}
    s_hmax: dict[Cell, pywraplp.Variable] = {}
    for cell in cells:
        p, w, m = cell
        b = bounds_index[cell]
        x, y, u, o = v.x[cell], v.y[cell], v.u[cell], v.o[cell]
        s_lo = solver.NumVar(0, inf, f"s_hmin_{p}_{w}_{m}")
        s_hi = solver.NumVar(0, inf, f"s_hmax_{p}_{w}_{m}")
        s_hmin[cell] = s_lo
        s_hmax[cell] = s_hi
        solver.Add(x >= b.hard_min * y - s_lo)
        solver.Add(x <= b.hard_max * y + s_hi)
        # C2 unchanged: already elastic via u/o.
        solver.Add(x + u >= b.soft_min * y)
        solver.Add(x - o <= b.soft_max * y)

    # C3': capacity, relaxed with slack.
    s_cap: dict[PersonMonth, pywraplp.Variable] = {}
    for (w, m), idle_var in v.idle.items():
        cells_wm = by_person_month.get((w, m), [])
        total = solver.Sum([v.x[c] for c in cells_wm]) if cells_wm else 0
        cap = plan.capacity_of(w, m).available_hours
        s = solver.NumVar(0, inf, f"s_cap_{w}_{m}")
        s_cap[(w, m)] = s
        solver.Add(total + idle_var - s == cap)

    # C4': hard targets get slack; soft targets are unconstrained here (they can never bind).
    s_target: dict[ProjectMonth, pywraplp.Variable] = {}
    for t in plan.targets:
        key = (t.project_id, t.month)
        if key not in v.dp:
            continue
        cells_pm = by_project_month.get(key, [])
        spend = solver.Sum([rates[c] * v.x[c] for c in cells_pm]) if cells_pm else 0
        dp_var, dm_var = v.dp[key], v.dm[key]
        solver.Add(spend - t.labor_spend_target == dp_var - dm_var)
        if t.target_type == TargetType.HARD:
            s = solver.NumVar(0, inf, f"s_target_{t.project_id}_{t.month}")
            s_target[key] = s
            solver.Add(spend <= t.labor_spend_target + s)

    # C6 unchanged: hard fragmentation ceiling is a real constraint even here, since the
    # slack budget above is meant to explain capacity/bound infeasibility, not headcount policy.
    for (w, m), frag_var in v.frag.items():
        person = plan.person(w)
        cells_wm = by_person_month.get((w, m), [])
        count = solver.Sum([v.y[c] for c in cells_wm]) if cells_wm else 0
        solver.Add(count <= person.hard_max_concurrent_projects)
        solver.Add(count <= person.soft_max_concurrent_projects + frag_var)

    # C5: fixed cells still pinned.
    for cell, value in fixed_values.items():
        v.x[cell].SetBounds(value, value)

    slack_terms = list(s_hmin.values()) + list(s_hmax.values()) + list(s_cap.values()) + list(s_target.values())
    solver.Minimize(solver.Sum(slack_terms))

    return ElasticBundle(solver=solver, variables=v, s_hmin=s_hmin, s_hmax=s_hmax, s_cap=s_cap, s_target=s_target)
