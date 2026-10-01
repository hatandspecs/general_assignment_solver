"""The working assignment's undo stack (`grist_planner/planner_api/history.py`).

Requirement 5 — "go back to a previous iteration" — is the one part of the loop whose
failure mode is silent and unrecoverable: if a snapshot is missed, nobody finds out
until a planner wants a version back and it isn't there. So the properties asserted here
are the ones that make the stack trustworthy rather than merely present: appending never
loses a later iteration, restoring is itself an append, and identical states don't pile
up as duplicate entries.

Runs against an in-memory store rather than a live Grist document, which `history.py`'s
`TableStore` protocol exists to allow — the planner-api container's `httpx`/`fastapi`
aren't in the environment this suite runs in.
"""

import sys
from pathlib import Path

import pytest

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.calendar import Month

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "grist_planner"))

from planner_api import history  # noqa: E402  - needs the sys.path line above


class FakeStore:
    """Enough of `GristClient` for `history.py`: tables of records, with Grist's
    1-based row ids, `add_records` appending and `replace_table` overwriting."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def fetch_records(self, table_id: str) -> list[dict]:
        return [dict(r) for r in self.tables.get(table_id, [])]

    def add_records(self, table_id: str, records: list[dict]) -> list[int]:
        rows = self.tables.setdefault(table_id, [])
        ids = []
        for record in records:
            row_id = len(rows) + 1
            rows.append({"id": row_id, **record})
            ids.append(row_id)
        return ids

    def replace_table(self, table_id: str, records: list[dict]) -> None:
        self.tables[table_id] = [{"id": i + 1, **r} for i, r in enumerate(records)]


M1 = Month(2027, 1)
M2 = Month(2027, 2)


def _row(project_id, person_id, hours, *, month=M1, locked=False):
    return AllocationRow(
        project_id=project_id, person_id=person_id, month=month, hours_assigned=hours, locked=locked
    )


def test_snapshots_number_from_one_and_increment():
    store = FakeStore()
    assert history.latest_iteration(store) is None

    first = history.snapshot(store, [_row("proj_a", "alice", 100)], source="import")
    second = history.snapshot(store, [_row("proj_a", "alice", 80)], source="solve")

    assert first["iteration"] == 1
    assert second["iteration"] == 2
    assert [i["iteration"] for i in history.list_iterations(store)] == [2, 1]  # newest first


def test_snapshot_records_its_own_summary():
    store = FakeStore()
    entry = history.snapshot(
        store,
        [_row("proj_a", "alice", 100, locked=True), _row("proj_b", "bob", 50)],
        source="solve",
        label="solved (loose adherence)",
        objective=0.1234,
        adherence="loose",
    )
    assert entry["num_cells"] == 2
    assert entry["num_locked"] == 1
    assert entry["total_hours"] == 150.0
    assert entry["adherence"] == "loose"
    assert entry["created_at"].endswith("Z")


def test_cells_round_trip_through_a_snapshot():
    store = FakeStore()
    rows = [
        _row("proj_a", "alice", 100.5, locked=True),
        _row("proj_b", "bob", 40, month=M2),
    ]
    history.snapshot(store, rows, source="import")
    restored = history.cells_of(store, 1)

    assert [(a.project_id, a.person_id, str(a.month), a.hours_assigned, a.locked) for a in restored] == [
        ("proj_a", "alice", "2027-01", 100.5, True),
        ("proj_b", "bob", "2027-02", 40.0, False),
    ]


def test_cells_are_scoped_to_their_own_iteration():
    store = FakeStore()
    history.snapshot(store, [_row("proj_a", "alice", 100)], source="import")
    history.snapshot(store, [_row("proj_a", "alice", 80), _row("proj_b", "bob", 20)], source="solve")

    assert [a.hours_assigned for a in history.cells_of(store, 1)] == [100.0]
    assert sorted(a.hours_assigned for a in history.cells_of(store, 2)) == [20.0, 80.0]


def test_only_if_changed_suppresses_a_duplicate():
    """A re-solve that lands on the same numbers shouldn't pad the history — otherwise
    the undo list fills with indistinguishable entries and stops being usable."""
    store = FakeStore()
    rows = [_row("proj_a", "alice", 100)]
    assert history.snapshot(store, rows, source="solve", only_if_changed=True) is not None
    assert history.snapshot(store, list(rows), source="solve", only_if_changed=True) is None
    assert len(history.list_iterations(store)) == 1

    changed = [_row("proj_a", "alice", 100.01)]
    assert history.snapshot(store, changed, source="solve", only_if_changed=True) is not None


def test_a_lock_flag_change_alone_counts_as_changed():
    """Locking a cell changes the plan's meaning even at identical hours, so it has to
    be snapshottable — otherwise a lock sweep would be unrecoverable."""
    store = FakeStore()
    history.snapshot(store, [_row("proj_a", "alice", 100)], source="solve")
    assert history.differs_from_latest(store, [_row("proj_a", "alice", 100, locked=True)])
    assert not history.differs_from_latest(store, [_row("proj_a", "alice", 100)])


def test_solve_id_and_lock_note_do_not_count_as_changed():
    """Every solve stamps a fresh `solve_id`. If that counted, `only_if_changed` would
    never suppress anything."""
    store = FakeStore()
    history.snapshot(store, [_row("proj_a", "alice", 100)], source="solve")
    same_numbers = AllocationRow(
        project_id="proj_a",
        person_id="alice",
        month=M1,
        hours_assigned=100,
        solve_id="deadbeef",
        lock_note="whatever",
    )
    assert not history.differs_from_latest(store, [same_numbers])


def test_differs_from_latest_on_an_empty_history():
    store = FakeStore()
    assert history.differs_from_latest(store, [_row("proj_a", "alice", 100)])
    assert not history.differs_from_latest(store, [])


def test_restoring_keeps_the_later_iterations():
    """The property that makes going back safe: restoring 1 appends 3 and leaves 2
    intact, so a planner who goes back and changes their mind loses nothing."""
    store = FakeStore()
    history.snapshot(store, [_row("proj_a", "alice", 100)], source="import")
    history.snapshot(store, [_row("proj_a", "alice", 20)], source="solve")

    # What the restore endpoint does: write iteration 1's cells back, then append them.
    revived = history.cells_of(store, 1)
    history.write_working_assignment(store, revived, [])
    history.snapshot(store, revived, source="restore", label="restored iteration 1")

    assert [i["iteration"] for i in history.list_iterations(store)] == [3, 2, 1]
    assert [a.hours_assigned for a in history.cells_of(store, 2)] == [20.0]  # still there
    assert [a.hours_assigned for a in history.cells_of(store, 3)] == [100.0]
    assert [r["hours_assigned"] for r in store.fetch_records("Allocation")] == [100.0]


def test_restoring_across_a_month_close_must_not_duplicate_cells():
    """Regression: an iteration saved before a month closed still holds that month's
    open rows. Writing them back alongside the now-closed ones put the same cell in
    `Allocation` twice — once carrying `hours_actual`, once not — silently corrupting
    the baseline and the variance report. `open_month_rows` against the *current*
    `closed_through` is what the restore endpoint filters with.
    """
    store = FakeStore()
    snapshot_rows = [_row("proj_a", "alice", 80, month=M1), _row("proj_a", "alice", 90, month=M2)]
    history.snapshot(store, snapshot_rows, source="solve")

    # M1 has since closed and carries actuals.
    closed_rows = [
        AllocationRow(
            project_id="proj_a", person_id="alice", month=M1, hours_assigned=80, hours_actual=78
        )
    ]
    restorable = history.open_month_rows(history.cells_of(store, 1), M1)
    assert [str(a.month) for a in restorable] == ["2027-02"]

    history.write_working_assignment(store, restorable, closed_rows)
    written = store.fetch_records("Allocation")
    keys = [(r["project_id"], r["person_id"], r["month"]) for r in written]
    assert len(keys) == len(set(keys))
    assert next(r for r in written if r["month"] == "2027-01")["hours_actual"] == 78


def test_write_working_assignment_preserves_closed_months():
    store = FakeStore()
    closed = [
        AllocationRow(
            project_id="proj_a", person_id="alice", month=M1, hours_assigned=50, hours_actual=55
        )
    ]
    history.write_working_assignment(store, [_row("proj_a", "alice", 70, month=M2)], closed)

    written = store.fetch_records("Allocation")
    assert len(written) == 2
    by_month = {r["month"]: r for r in written}
    assert by_month["2027-01"]["hours_actual"] == 55
    assert by_month["2027-02"]["hours_assigned"] == 70


def test_an_empty_snapshot_writes_a_header_but_no_cells():
    store = FakeStore()
    entry = history.snapshot(store, [], source="import")
    assert entry["num_cells"] == 0
    assert entry["total_hours"] == 0
    assert history.cells_of(store, 1) == []


def test_open_month_rows_splits_on_closed_through():
    allocation = [_row("proj_a", "alice", 50, month=M1), _row("proj_a", "alice", 70, month=M2)]
    assert len(history.open_month_rows(allocation, None)) == 2
    assert [a.month for a in history.open_month_rows(allocation, M1)] == [M2]
    assert history.open_month_rows(allocation, M2) == []


@pytest.mark.parametrize("source", ["import", "tweak", "solve", "locks", "restore", "commit"])
def test_every_documented_source_round_trips(source):
    """The `source` column is how a planner tells "my edits" from "the solver's output"
    in the undo list, so each documented value has to survive the round trip."""
    store = FakeStore()
    history.snapshot(store, [_row("proj_a", "alice", 10)], source=source)
    assert history.latest_iteration(store)["source"] == source
