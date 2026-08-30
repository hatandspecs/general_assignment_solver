"""Objective terms, normalization, weights — `04-solver-design.md`, "Objective"."""

from dataclasses import dataclass

from ortools.linear_solver import pywraplp

from allocsolver.config import Weights
from allocsolver.costing.masks import Cell
from allocsolver.models.plan import Plan

from .variables import Variables


@dataclass(frozen=True, slots=True)
class Norms:
    dollars: float
    hours: float
    count: float


def compute_norms(plan: Plan, cells: list[Cell]) -> Norms:
    horizon = set(plan.horizon())
    dollars = sum(t.labor_spend_target for t in plan.targets if t.month in horizon) or 1.0
    hours = sum(c.available_hours for c in plan.capacity if c.month in horizon) or 1.0
    count = len(cells) or 1
    return Norms(dollars=dollars, hours=hours, count=count)


def build_objective(
    solver: pywraplp.Solver, v: Variables, cells: list[Cell], weights: Weights, norms: Norms
) -> None:
    terms: list[pywraplp.LinearExpr] = []

    for var in v.dp_prime.values():
        terms.append((weights.target / norms.dollars) * var)
    for var in v.dm_prime.values():
        terms.append((weights.target / norms.dollars) * var)

    for var in v.u.values():
        terms.append((weights.soft / norms.hours) * var)
    for var in v.o.values():
        terms.append((weights.soft / norms.hours) * var)

    for var in v.idle.values():
        terms.append((weights.idle / norms.hours) * var)

    for var in v.cp.values():
        terms.append((weights.churn / norms.hours) * var)
    for var in v.cm.values():
        terms.append((weights.churn / norms.hours) * var)

    for var in v.y.values():
        terms.append((weights.headcount / norms.count) * var)

    for var in v.frag.values():
        terms.append((weights.frag / norms.count) * var)

    solver.Minimize(solver.Sum(terms))
