"""Local JSON file I/O for a `Plan` — the near-term substitute for a live Grist document.

`05-interfaces.md` specifies `GristClient` as the input path; there is no live Grist
document in this build yet, so this module is the practical stand-in used by the CLI
and the medium example. One file per table, mirroring the star schema directly, so a
planner can open any one file and see exactly what a Grist table would hold.
"""

import json
from pathlib import Path

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.capacity import Capacity
from allocsolver.models.people import Person
from allocsolver.models.plan import Plan
from allocsolver.models.projects import Project, RateStructure
from allocsolver.models.rates import Rate, WrapRate
from allocsolver.models.targets import Target

_TABLE_FILES: dict[str, tuple[str, type]] = {
    "people": ("people.json", Person),
    "projects": ("projects.json", Project),
    "rate_structures": ("rate_structures.json", RateStructure),
    "rates": ("rates.json", Rate),
    "wrap_rates": ("wrap_rates.json", WrapRate),
    "capacity": ("capacity.json", Capacity),
    "bounds": ("bounds.json", Bounds),
    "targets": ("targets.json", Target),
    "allocation": ("allocation.json", AllocationRow),
}


def save_plan(plan: Plan, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for field_name, (filename, _model) in _TABLE_FILES.items():
        rows = getattr(plan, field_name)
        with open(data_dir / filename, "w") as f:
            json.dump([row.model_dump(mode="json") for row in rows], f, indent=2, default=str)

    meta = {
        "horizon_start": str(plan.horizon_start),
        "horizon_end": str(plan.horizon_end),
        "closed_through": str(plan.closed_through) if plan.closed_through else None,
    }
    with open(data_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def load_plan(data_dir: Path) -> Plan:
    tables: dict[str, list] = {}
    for field_name, (filename, model) in _TABLE_FILES.items():
        path = data_dir / filename
        if not path.exists():
            tables[field_name] = []
            continue
        with open(path) as f:
            raw = json.load(f)
        tables[field_name] = [model.model_validate(row) for row in raw]

    with open(data_dir / "meta.json") as f:
        meta = json.load(f)

    return Plan(
        horizon_start=Month.parse(meta["horizon_start"]),
        horizon_end=Month.parse(meta["horizon_end"]),
        closed_through=Month.parse(meta["closed_through"]) if meta.get("closed_through") else None,
        **tables,
    )
