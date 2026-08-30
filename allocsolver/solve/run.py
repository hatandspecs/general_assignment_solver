"""Solve, timeout, gap, and the feasible/infeasible branch — `02-architecture.md`, "Control flow"."""

import time
import uuid

from ortools.linear_solver import pywraplp

from allocsolver.config import DEFAULT_MIP_GAP, DEFAULT_TIME_LIMIT_SECONDS, Weights
from allocsolver.costing.masks import Cell
from allocsolver.models.plan import Plan

from .build import ModelBundle, build_model
from .diagnostics import diagnose
from .result import ObjectiveBreakdown, SolveResult


def _objective_breakdown(bundle: ModelBundle) -> ObjectiveBreakdown:
    w, n, v = bundle.weights, bundle.norms, bundle.variables

    target = sum(var.solution_value() for var in [*v.dp_prime.values(), *v.dm_prime.values()])
    target *= w.target / n.dollars
    soft = sum(var.solution_value() for var in [*v.u.values(), *v.o.values()]) * w.soft / n.hours
    idle = sum(var.solution_value() for var in v.idle.values()) * w.idle / n.hours
    churn = sum(var.solution_value() for var in [*v.cp.values(), *v.cm.values()]) * w.churn / n.hours
    headcount = sum(var.solution_value() for var in v.y.values()) * w.headcount / n.count
    frag = sum(var.solution_value() for var in v.frag.values()) * w.frag / n.count

    return ObjectiveBreakdown(
        target=target,
        soft=soft,
        idle=idle,
        churn=churn,
        headcount=headcount,
        frag=frag,
        total=target + soft + idle + churn + headcount + frag,
    )


def solve(
    plan: Plan,
    baseline: dict[Cell, float] | None = None,
    weights: Weights | None = None,
    time_limit_seconds: int = DEFAULT_TIME_LIMIT_SECONDS,
    mip_gap: float = DEFAULT_MIP_GAP,
) -> SolveResult:
    """`allocsolver solve` — see `05-interfaces.md` for the CLI surface this backs."""
    bundle = build_model(plan, baseline=baseline, weights=weights)
    bundle.solver.SetTimeLimit(time_limit_seconds * 1000)
    bundle.solver.SetSolverSpecificParametersAsString(f"limits/gap = {mip_gap}\n")

    solve_id = uuid.uuid4().hex[:12]
    start = time.monotonic()
    status = bundle.solver.Solve()
    wall_time = time.monotonic() - start

    if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        # Clip solver noise (e.g. -1e-13 for a variable that's mathematically 0).
        hours_assigned = {
            cell: (0.0 if abs(var.solution_value()) < 1e-6 else var.solution_value())
            for cell, var in bundle.variables.x.items()
        }
        return SolveResult(
            feasible=True,
            hours_assigned=hours_assigned,
            objective=_objective_breakdown(bundle),
            mip_gap=None,  # OR-Tools' generic MPSolver wrapper doesn't expose the achieved gap.
            wall_time_seconds=wall_time,
            solve_id=solve_id,
            diagnostics=None,
        )

    return SolveResult(
        feasible=False,
        hours_assigned={},
        objective=None,
        mip_gap=None,
        wall_time_seconds=wall_time,
        solve_id=solve_id,
        diagnostics=diagnose(plan),
    )
