"""Manual pre-assignments — the planner's own input, kept clearly separate from
everything the solver or the simulation engine writes.

Most of the workforce is pre-assigned in whole or part to programs manually by
project planners, before the solver ever runs — a pre-assignment *is* a `Bounds`
row (hard/soft min/max for one project/person/month); this file is nothing more
than a staging area for them, reusing that model directly rather than inventing
a new shape.

Workflow: a planner edits `pre_assignments.json` by hand before running a solve for
an upcoming month. `advance-month` reads it, upserts each entry into the plan's
`bounds` (by project/person/month key — a pre-assignment overrides whatever bound
already existed for that cell), solves, and — once the cycle's saved — clears the
file back to empty. The override itself lives on permanently in `bounds.json`; the
inbox is only ever "this cycle's new manual decisions," not a running log.
"""

import json
from pathlib import Path

from allocsolver.models.bounds import Bounds
from allocsolver.models.plan import Plan

PRE_ASSIGNMENTS_FILENAME = "pre_assignments.json"


def load_pre_assignments(data_dir: Path) -> list[Bounds]:
    path = data_dir / PRE_ASSIGNMENTS_FILENAME
    if not path.exists():
        return []
    with open(path) as f:
        raw = json.load(f)
    return [Bounds.model_validate(row) for row in raw]


def clear_pre_assignments(data_dir: Path) -> None:
    with open(data_dir / PRE_ASSIGNMENTS_FILENAME, "w") as f:
        json.dump([], f, indent=2)


def apply_pre_assignments(plan: Plan, pre_assignments: list[Bounds]) -> Plan:
    """Upserts each pre-assignment into `plan.bounds`, keyed by (project, person, month).
    A pre-assignment for a cell that already has a bounds row replaces it outright;
    one for a new cell adds it (making that pair eligible for the first time).

    Goes through full `Plan` validation (`model_validate`), not `model_copy` — a
    pre-assignment is hand-edited planner input, exactly the kind of thing a typo'd
    person or project id can sneak into, and this should be caught immediately
    rather than silently accepted and only surfacing as a confusing error (or not
    at all) later.
    """
    if not pre_assignments:
        return plan
    bounds_by_key = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
    for pa in pre_assignments:
        bounds_by_key[(pa.project_id, pa.person_id, pa.month)] = pa
    data = plan.model_dump(mode="json")
    data["bounds"] = [b.model_dump(mode="json") for b in bounds_by_key.values()]
    return Plan.model_validate(data)
