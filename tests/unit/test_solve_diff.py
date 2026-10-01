"""The before/after diff a planner reads after every solve
(`grist_planner/planner_api/reports.py`'s `working_diff_rows`).

Like `test_assignment_history.py`, this runs against plain data rather than a live
Grist document — `reports.py` depends only on `allocsolver`, never on `httpx`.
"""

import sys
from pathlib import Path

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.calendar import Month

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "grist_planner"))

from planner_api.reports import working_diff_rows  # noqa: E402  - needs the sys.path line above

M1 = Month(2027, 1)
M2 = Month(2027, 2)


def _row(project_id, person_id, hours, *, month=M2, locked=False):
    return AllocationRow(
        project_id=project_id, person_id=person_id, month=month, hours_assigned=hours, locked=locked
    )


def _by_cell(rows):
    return {(r["project_id"], r["person_id"], r["month"]): r for r in rows}


def test_the_four_statuses():
    before = [
        _row("proj_a", "alice", 100),  # adjusted
        _row("proj_a", "bob", 50),  # dropped
        _row("proj_b", "alice", 40),  # unchanged
    ]
    after = {
        ("proj_a", "alice", M2): 80.0,
        ("proj_b", "alice", M2): 40.0,
        ("proj_b", "bob", M2): 25.0,  # added
    }
    rows = _by_cell(working_diff_rows(before, after, None))

    assert rows[("proj_a", "alice", "2027-02")]["status"] == "adjusted"
    assert rows[("proj_a", "alice", "2027-02")]["delta"] == -20.0
    assert rows[("proj_a", "bob", "2027-02")]["status"] == "dropped"
    assert rows[("proj_a", "bob", "2027-02")]["delta"] == -50.0
    assert rows[("proj_b", "alice", "2027-02")]["status"] == "unchanged"
    assert rows[("proj_b", "bob", "2027-02")]["status"] == "added"
    assert rows[("proj_b", "bob", "2027-02")]["delta"] == 25.0


def test_a_cell_locked_at_zero_does_not_crash_the_diff():
    """Regression: a cell pinned deliberately empty is in `before` (a row exists) but
    not in `after` (it has no hours), so both sides read as None. That combination used
    to fall through to the `added` branch and raise `TypeError: type NoneType doesn't
    define __round__`, turning every solve after an empty-lock into a 500.
    """
    before = [_row("proj_a", "alice", 0.0, locked=True), _row("proj_a", "bob", 60)]
    after = {("proj_a", "bob", M2): 60.0}

    rows = _by_cell(working_diff_rows(before, after, None))
    pinned = rows[("proj_a", "alice", "2027-02")]
    assert pinned["status"] == "unchanged"
    assert pinned["delta"] == 0.0
    assert pinned["locked"] is True
    assert rows[("proj_a", "bob", "2027-02")]["status"] == "unchanged"


def test_near_zero_solver_output_is_not_an_assignment():
    """Where `hard_min` is 0 the solver may return a fraction of an hour. A cell holding
    0.004h is stored and displayed as 0.00, so listing it as `added` with a delta of
    0.0 is noise in the report read after every solve."""
    rows = working_diff_rows([], {("proj_a", "alice", M2): 0.004}, None)
    assert rows == []

    kept = working_diff_rows([], {("proj_a", "alice", M2): 0.006}, None)
    assert [r["status"] for r in kept] == ["added"]
    assert kept[0]["solved_hours"] == 0.01


def test_closed_months_are_excluded():
    """The diff describes the plan, and a closed month is history pinned to actuals."""
    before = [_row("proj_a", "alice", 50, month=M1), _row("proj_a", "alice", 70, month=M2)]
    after = {("proj_a", "alice", M1): 50.0, ("proj_a", "alice", M2): 90.0}

    rows = working_diff_rows(before, after, M1)
    assert [r["month"] for r in rows] == ["2027-02"]
    assert rows[0]["delta"] == 20.0


def test_locked_flag_is_carried_through():
    """A zero delta on a locked cell means something different from a zero delta on a
    free one: pinned, versus the solver independently agreeing."""
    before = [_row("proj_a", "alice", 100, locked=True), _row("proj_a", "bob", 100)]
    after = {("proj_a", "alice", M2): 100.0, ("proj_a", "bob", M2): 100.0}

    rows = _by_cell(working_diff_rows(before, after, None))
    assert rows[("proj_a", "alice", "2027-02")]["locked"] is True
    assert rows[("proj_a", "bob", "2027-02")]["locked"] is False


def test_mip_noise_is_not_reported_as_a_change():
    """The solver runs to a 1% gap, so re-solving a large model moves hundreds of cells
    by a hundredth of an hour. Reporting those as `adjusted` buries the changes a
    planner actually made."""
    before = [_row("proj_a", "alice", 100), _row("proj_a", "bob", 100)]
    after = {("proj_a", "alice", M2): 100.03, ("proj_a", "bob", M2): 106.0}

    rows = _by_cell(working_diff_rows(before, after, None))
    assert rows[("proj_a", "alice", "2027-02")]["status"] == "unchanged"
    assert rows[("proj_a", "bob", "2027-02")]["status"] == "adjusted"


def test_biggest_movers_sort_first_within_a_status():
    before = [_row("proj_a", "alice", 100), _row("proj_a", "bob", 100)]
    after = {("proj_a", "alice", M2): 95.0, ("proj_a", "bob", M2): 40.0}

    adjusted = [r for r in working_diff_rows(before, after, None) if r["status"] == "adjusted"]
    assert [r["person_id"] for r in adjusted] == ["bob", "alice"]
