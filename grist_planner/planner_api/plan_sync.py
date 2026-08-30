"""Grist-backed equivalent of `allocsolver.io.local` (`Plan` <-> JSON files) and
`allocsolver.io.pre_assignments` (the manual pre-assignment inbox) — same shapes,
Grist tables instead of files. `allocsolver.io.pre_assignments.apply_pre_assignments`
itself is reused unchanged: it only operates on `Plan` + `list[Bounds]`, with no
idea whether either came from a file or a live document.
"""

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.capacity import Capacity
from allocsolver.models.people import Person
from allocsolver.models.plan import Plan
from allocsolver.models.projects import Project, RateStructure
from allocsolver.models.rates import Rate, WrapRate
from allocsolver.models.targets import Target

from .grist_client import GristClient

_TABLE_MAP: dict[str, tuple[str, type]] = {
    "people": ("People", Person),
    "projects": ("Projects", Project),
    "rate_structures": ("Rate_Structures", RateStructure),
    "rates": ("Rates", Rate),
    "wrap_rates": ("Wrap_Rates", WrapRate),
    "capacity": ("Capacity", Capacity),
    "bounds": ("Bounds", Bounds),
    "targets": ("Targets", Target),
    "allocation": ("Allocation", AllocationRow),
}


def _drop_row_id(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "id"}


def load_plan_from_grist(client: GristClient) -> Plan:
    tables: dict[str, list] = {}
    for field_name, (table_id, model) in _TABLE_MAP.items():
        records = client.fetch_records(table_id)
        tables[field_name] = [model.model_validate(_drop_row_id(r)) for r in records]

    meta_records = client.fetch_records("Meta")
    if not meta_records:
        raise RuntimeError(
            "The Meta table is empty — this document hasn't been seeded with a plan yet "
            "(see the tutorial's 'load starting data' step)."
        )
    meta = meta_records[0]

    return Plan(
        horizon_start=Month.parse(meta["horizon_start"]),
        horizon_end=Month.parse(meta["horizon_end"]),
        closed_through=Month.parse(meta["closed_through"]) if meta.get("closed_through") else None,
        **tables,
    )


def save_plan_to_grist(plan: Plan, client: GristClient) -> None:
    for field_name, (table_id, _model) in _TABLE_MAP.items():
        rows = getattr(plan, field_name)
        client.replace_table(table_id, [row.model_dump(mode="json") for row in rows])

    meta = {
        "horizon_start": str(plan.horizon_start),
        "horizon_end": str(plan.horizon_end),
        "closed_through": str(plan.closed_through) if plan.closed_through else None,
    }
    client.replace_table("Meta", [meta])


def load_pre_assignments_from_grist(client: GristClient) -> list[Bounds]:
    records = client.fetch_records("Pre_Assignments")
    return [Bounds.model_validate(_drop_row_id(r)) for r in records]


def write_pre_assignments_to_grist(client: GristClient, pre_assignments: list[Bounds]) -> None:
    """Used by the "load a pre-assignment JSON" upload: replaces whatever's
    currently in the table with the uploaded rows, so the planner can review or
    hand-edit them in Grist before Running Planning."""
    client.replace_table("Pre_Assignments", [b.model_dump(mode="json") for b in pre_assignments])


def clear_pre_assignments_in_grist(client: GristClient) -> None:
    """This cycle's manual decisions are now permanent in Bounds (once merged by
    `apply_pre_assignments` and saved) — same "inbox, not a log" posture as the
    file-based version."""
    client.replace_table("Pre_Assignments", [])
