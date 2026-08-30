"""Assembles the model — `04-solver-design.md`; solver choice per `06-code-structure-and-dependencies.md`."""

from dataclasses import dataclass

from ortools.linear_solver import pywraplp

from allocsolver.config import Weights
from allocsolver.costing.masks import Cell, eligible_cells
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.plan import Plan

from .constraints import add_constraints, apply_fixed
from .objective import Norms, build_objective, compute_norms
from .variables import Variables, build_variables


@dataclass
class ModelBundle:
    solver: pywraplp.Solver
    plan: Plan
    cells: list[Cell]
    fixed: set[Cell]
    variables: Variables
    rates: dict[Cell, float]
    baseline: dict[Cell, float]
    weights: Weights
    norms: Norms


def fixed_cells_and_values(plan: Plan, cells: list[Cell]) -> dict[Cell, float]:
    """`F`: locked cells pinned to their value, closed-month cells pinned to actuals."""
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}
    fixed: dict[Cell, float] = {}
    for cell in cells:
        _, _, month = cell
        row = alloc_index.get(cell)
        if row is None:
            continue
        if row.locked:
            fixed[cell] = row.hours_assigned
        elif plan.closed_through is not None and month <= plan.closed_through:
            if row.hours_actual is not None:
                fixed[cell] = row.hours_actual
    return fixed


def build_model(
    plan: Plan,
    baseline: dict[Cell, float] | None = None,
    weights: Weights | None = None,
    solver_backend: str = "SCIP",
) -> ModelBundle:
    solver = pywraplp.Solver.CreateSolver(solver_backend)
    if solver is None:
        raise RuntimeError(f"OR-Tools could not create a '{solver_backend}' solver instance")

    weights = weights or Weights()
    baseline = baseline or {}

    cells = eligible_cells(plan)
    fixed_values = fixed_cells_and_values(plan, cells)
    fixed = set(fixed_values.keys())
    rates = {cell: loaded_rate(plan, cell[1], cell[2], cell[0]) for cell in cells}

    variables = build_variables(solver, plan, cells, fixed)
    add_constraints(solver, plan, variables, cells, fixed, rates, baseline)
    apply_fixed(variables, fixed_values)

    norms = compute_norms(plan, cells)
    build_objective(solver, variables, cells, weights, norms)

    return ModelBundle(
        solver=solver,
        plan=plan,
        cells=cells,
        fixed=fixed,
        variables=variables,
        rates=rates,
        baseline=baseline,
        weights=weights,
        norms=norms,
    )
