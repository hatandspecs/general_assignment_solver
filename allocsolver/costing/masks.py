"""Eligibility, PoP windows, employment windows — builds `E` from `04-solver-design.md`."""

from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.models.projects import ProjectStatus

Cell = tuple[str, str, Month]


def eligible_cells(plan: Plan) -> list[Cell]:
    """E: the subset of P x W x M that is eligible, in-PoP, and in the employment window.

    Variables are generated only over this set, never the full cross product
    (`04-solver-design.md`, "Sets").
    """
    bounds_index = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
    horizon = set(plan.horizon())
    cells: list[Cell] = []

    for project in plan.projects:
        if project.status != ProjectStatus.ACTIVE:
            continue
        pop_months = set(project.months()) & horizon
        for person in plan.people:
            for month in pop_months:
                if not person.is_active(month):
                    continue
                b = bounds_index.get((project.project_id, person.person_id, month))
                if b is None or not b.eligible:
                    continue
                cells.append((project.project_id, person.person_id, month))

    return cells
