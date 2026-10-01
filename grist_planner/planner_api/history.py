"""Iteration history for the working assignment — the undo stack behind "go back".

The tweak-and-solve loop is only safe to use if it is reversible. A planner who hand-
edits a dozen cells, presses Solve, and gets back something worse has lost the version
they liked unless something kept it, and `Allocation` is overwritten in place by every
solve.

So every state of the working assignment is appended here before it is replaced, as a
numbered iteration: a header row in `Assignment_History` and its cells in
`Assignment_History_Cells`. Append-only — restoring iteration 4 does not delete 5 and
6, it copies 4's cells back into `Allocation` and appends them as iteration 7. Nothing
is ever lost by going back, so there is no branch to strand and no way for a planner to
destroy a version by exploring away from it.

Snapshot points, each a state someone might want to return to:

| `source`  | Written when |
|---|---|
| `import`  | a ballpark CSV/JSON is imported |
| `tweak`   | a solve starts and `Allocation` differs from the last iteration — this is what captures hand-edits made directly in the Grist table, which nothing else observes |
| `solve`   | a solve succeeds |
| `locks`   | a bulk lock/unlock changes flags |
| `restore` | an earlier iteration is restored |
| `commit`  | the plan is exported to the workforce |

Open months only. Closed months carry `hours_actual` and are not part of the working
assignment (`io/working_assignment.py`), so versioning them would be versioning history.

The `objective` column is not comparable between iterations. Part of the objective is
the churn term — distance from the baseline — and the baseline is whatever the working
assignment held when that solve started, so two iterations are scored against different
reference points. Observed in practice: restoring an iteration and re-solving returns
the identical assignment with an objective of 10.54 where the original solve recorded
19.60, the whole difference being that the second solve started from the answer instead
of from a sparse ballpark. The column is a record of what each solve was minimizing,
useful against its own run; ranking iterations by it is meaningless.
"""

from datetime import datetime, timezone
from typing import Protocol

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.calendar import Month


class TableStore(Protocol):
    """The three `GristClient` methods this module needs.

    Typed as a protocol rather than importing `GristClient` so that none of the logic
    below depends on `httpx` — which lives only in the planner-api container image, not
    the `allocsolver` conda environment the test suite runs in. The undo stack is the
    newest and least-obvious code in the service, and this is what lets it be tested
    against an in-memory store instead of only against a live Grist document
    (`tests/unit/test_assignment_history.py`).
    """

    def fetch_records(self, table_id: str) -> list[dict]: ...

    def add_records(self, table_id: str, records: list[dict]) -> list[int]: ...

    def replace_table(self, table_id: str, records: list[dict]) -> None: ...


HISTORY_TABLE = "Assignment_History"
HISTORY_CELLS_TABLE = "Assignment_History_Cells"

HISTORY_COLUMNS = [
    "iteration",
    "created_at",
    "source",
    "label",
    "feasible",
    "objective",
    "adherence",
    "num_cells",
    "num_locked",
    "total_hours",
    "note",
]


def open_month_rows(allocation: list[AllocationRow], closed_through: Month | None) -> list[AllocationRow]:
    return [a for a in allocation if closed_through is None or a.month > closed_through]


def _cell_signature(rows: list[AllocationRow]) -> set[tuple[str, str, str, float, bool]]:
    """What counts as "changed" for snapshot-if-changed: the cells, their hours to the
    cent, and their lock flags. Deliberately ignores `solve_id` and `lock_note`, so a
    re-solve that lands on exactly the same numbers doesn't append a duplicate."""
    return {
        (a.project_id, a.person_id, str(a.month), round(a.hours_assigned, 2), bool(a.locked)) for a in rows
    }


def list_iterations(client: TableStore) -> list[dict]:
    """Newest first — the order an undo list is read in."""
    records = [{k: v for k, v in r.items() if k != "id"} for r in client.fetch_records(HISTORY_TABLE)]
    records.sort(key=lambda r: r.get("iteration") or 0, reverse=True)
    return records


def latest_iteration(client: TableStore) -> dict | None:
    iterations = list_iterations(client)
    return iterations[0] if iterations else None


def next_iteration_number(client: TableStore) -> int:
    latest = latest_iteration(client)
    return (latest["iteration"] + 1) if latest else 1


def cells_of(client: TableStore, iteration: int) -> list[AllocationRow]:
    """One iteration's cells, as `AllocationRow`s ready to write back to `Allocation`.

    `solve_id` is carried through so a restored iteration still says which solve
    produced it; `hours_actual` is always None here because only open months are
    versioned.
    """
    out: list[AllocationRow] = []
    for record in client.fetch_records(HISTORY_CELLS_TABLE):
        if record.get("iteration") != iteration:
            continue
        out.append(
            AllocationRow(
                project_id=record["project_id"],
                person_id=record["person_id"],
                month=Month.parse(record["month"]),
                hours_assigned=record.get("hours_assigned") or 0.0,
                hours_actual=None,
                locked=bool(record.get("locked")),
                lock_note=record.get("lock_note") or None,
                solve_id=record.get("solve_id") or None,
            )
        )
    out.sort(key=lambda a: (str(a.month), a.project_id, a.person_id))
    return out


def differs_from_latest(client: TableStore, rows: list[AllocationRow]) -> bool:
    """True if `rows` is not already the newest iteration — the guard that keeps
    snapshot-on-every-action from filling the history with identical entries."""
    latest = latest_iteration(client)
    if latest is None:
        return bool(rows)
    return _cell_signature(cells_of(client, latest["iteration"])) != _cell_signature(rows)


def snapshot(
    client: TableStore,
    rows: list[AllocationRow],
    *,
    source: str,
    label: str = "",
    feasible: bool | None = None,
    objective: float | None = None,
    adherence: str = "",
    note: str = "",
    only_if_changed: bool = False,
) -> dict | None:
    """Appends one iteration. Returns its header row, or None if `only_if_changed` and
    nothing changed."""
    if only_if_changed and not differs_from_latest(client, rows):
        return None

    iteration = next_iteration_number(client)
    header = {
        "iteration": iteration,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "source": source,
        "label": label,
        "feasible": True if feasible is None else bool(feasible),
        "objective": objective,
        "adherence": adherence,
        "num_cells": len(rows),
        "num_locked": sum(1 for a in rows if a.locked),
        "total_hours": round(sum(a.hours_assigned for a in rows), 2),
        "note": note,
    }
    client.add_records(HISTORY_TABLE, [header])

    if rows:
        client.add_records(
            HISTORY_CELLS_TABLE,
            [
                {
                    "iteration": iteration,
                    "project_id": a.project_id,
                    "person_id": a.person_id,
                    "month": str(a.month),
                    "hours_assigned": round(a.hours_assigned, 2),
                    "locked": bool(a.locked),
                    "lock_note": a.lock_note or "",
                    "solve_id": a.solve_id or "",
                }
                for a in rows
            ],
        )
    return header


def write_working_assignment(
    client: TableStore, open_rows: list[AllocationRow], closed_rows: list[AllocationRow]
) -> None:
    """Replaces `Allocation` with closed months plus a new set of open months.

    Closed rows are passed in rather than re-read so the caller controls what history
    is preserved — every caller here reads them out of the same plan it loaded, so a
    closed month's `hours_actual` survives every operation in this module untouched.
    """
    all_rows = sorted(closed_rows + open_rows, key=lambda a: (str(a.month), a.project_id, a.person_id))
    client.replace_table("Allocation", [a.model_dump(mode="json") for a in all_rows])
