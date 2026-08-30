"""Variable generation over `E` — `04-solver-design.md`, "Decision variables"."""

from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from allocsolver.costing.masks import Cell
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan

PersonMonth = tuple[str, Month]
ProjectMonth = tuple[str, Month]


@dataclass
class Variables:
    x: dict[Cell, pywraplp.Variable] = field(default_factory=dict)
    y: dict[Cell, pywraplp.Variable] = field(default_factory=dict)
    u: dict[Cell, pywraplp.Variable] = field(default_factory=dict)
    o: dict[Cell, pywraplp.Variable] = field(default_factory=dict)
    dp: dict[ProjectMonth, pywraplp.Variable] = field(default_factory=dict)
    dm: dict[ProjectMonth, pywraplp.Variable] = field(default_factory=dict)
    dp_prime: dict[ProjectMonth, pywraplp.Variable] = field(default_factory=dict)
    dm_prime: dict[ProjectMonth, pywraplp.Variable] = field(default_factory=dict)
    idle: dict[PersonMonth, pywraplp.Variable] = field(default_factory=dict)
    cp: dict[Cell, pywraplp.Variable] = field(default_factory=dict)
    cm: dict[Cell, pywraplp.Variable] = field(default_factory=dict)
    frag: dict[PersonMonth, pywraplp.Variable] = field(default_factory=dict)


def build_variables(
    solver: pywraplp.Solver, plan: Plan, cells: list[Cell], fixed: set[Cell]
) -> Variables:
    inf = solver.infinity()
    v = Variables()

    for p, w, m in cells:
        cell = (p, w, m)
        v.x[cell] = solver.NumVar(0, inf, f"x_{p}_{w}_{m}")
        v.y[cell] = solver.BoolVar(f"y_{p}_{w}_{m}")
        v.u[cell] = solver.NumVar(0, inf, f"u_{p}_{w}_{m}")
        v.o[cell] = solver.NumVar(0, inf, f"o_{p}_{w}_{m}")
        if cell not in fixed:
            v.cp[cell] = solver.NumVar(0, inf, f"cp_{p}_{w}_{m}")
            v.cm[cell] = solver.NumVar(0, inf, f"cm_{p}_{w}_{m}")

    horizon = set(plan.horizon())
    for t in plan.targets:
        if t.month not in horizon:
            continue
        key = (t.project_id, t.month)
        v.dp[key] = solver.NumVar(0, inf, f"dp_{t.project_id}_{t.month}")
        v.dm[key] = solver.NumVar(0, inf, f"dm_{t.project_id}_{t.month}")
        v.dp_prime[key] = solver.NumVar(0, inf, f"dp'_{t.project_id}_{t.month}")
        v.dm_prime[key] = solver.NumVar(0, inf, f"dm'_{t.project_id}_{t.month}")

    for person in plan.people:
        for month in plan.horizon():
            if not person.is_active(month):
                continue
            key = (person.person_id, month)
            v.idle[key] = solver.NumVar(0, inf, f"idle_{person.person_id}_{month}")
            v.frag[key] = solver.NumVar(0, inf, f"frag_{person.person_id}_{month}")

    return v
