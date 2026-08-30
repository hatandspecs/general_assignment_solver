"""Per-month export bundle, including the completed-project-report copy."""

import csv
from pathlib import Path

from allocsolver.models.allocation import AllocationRow
from allocsolver.reports.exports import export_budget_summary, export_month_snapshot
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan


def test_completed_project_report_appears_one_cycle_after_pop_end(tmp_path: Path):
    """Regression: the final report must not be written during the PoP-end month's
    own cycle — that month's own actuals aren't known yet at that point, so a report
    written then would show its own last month blank. It should appear one cycle
    later, once those actuals are actually in, and show nothing blank."""
    plan = two_person_two_project_plan(months=2)  # both projects' pop_end is month 2
    result = solve(plan)
    assert result.feasible

    month1, month2 = plan.horizon()
    month3 = month2.add(1)  # outside the fixture's own horizon, used only as "as_of"
    output_dir = tmp_path / "output"
    completed_dir = output_dir / "completed_project_reports"

    export_month_snapshot(plan, result.hours_assigned, month1, output_dir / str(month1))
    assert not completed_dir.exists()  # month 1 isn't either project's pop_end yet

    export_month_snapshot(plan, result.hours_assigned, month2, output_dir / str(month2))
    assert not completed_dir.exists()  # month2 == pop_end, but its own actuals aren't known yet

    export_month_snapshot(plan, result.hours_assigned, month3, output_dir / str(month3))
    final_name_a = f"{month2.last_day()}_final_budget_proj_a.csv"
    assert (completed_dir / final_name_a).exists()

    rows = [r for r in csv.reader(open(completed_dir / final_name_a)) if r]
    by_label = {r[0]: r[1:] for r in rows}
    # Fully populated — including the project's own last month — nothing blank.
    for label in ("actual_spend", "cumulative_actual_spend", "actual_funds_remaining"):
        assert all(v != "" for v in by_label[label]), f"{label} should have no blanks in a final report"


def test_variance_is_for_the_previous_month_with_month_prefixed_filenames(tmp_path: Path):
    plan = two_person_two_project_plan(months=3)
    m1, m2, _m3 = plan.horizon()

    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(
                    project_id="proj_a", person_id="alice", month=m1, hours_assigned=77.0, hours_actual=60.0
                ),
            ],
        }
    )
    result = solve(plan)
    assert result.feasible

    output_dir = tmp_path / "output"
    export_month_snapshot(plan, result.hours_assigned, m2, output_dir / str(m2))

    # Work assignments for m2 are prefixed with m2 — the folder's own month.
    assert (output_dir / str(m2) / f"{m2}_work_assignments.csv").exists()

    # Variance is for m1 (the predecessor), not m2, and shows the *originally*
    # recorded hours_assigned (77.0) — not whatever the live solve shows for the
    # now-closed, fixed-to-actuals m1 cell (which would just be 60.0 again).
    variance_path = output_dir / str(m2) / f"{m1}_variance.csv"
    assert variance_path.exists()
    content = variance_path.read_text()
    assert "77.0" in content
    assert "60.0" in content
    assert "17.0" in content  # 77.0 - 60.0

    # No variance file when there's no predecessor month in the horizon.
    export_month_snapshot(plan, result.hours_assigned, m1, output_dir / str(m1))
    assert list((output_dir / str(m1)).glob("*_variance.csv")) == []


def test_budget_summary_planned_reflects_each_closed_months_own_history(tmp_path: Path):
    """Regression: every already-closed month must show *its own* recorded planned
    figure, not the live solve's value for that now-fixed-to-actual cell — which
    would make planned == actual identically for every historical month, with only
    the just-solved current month showing any real difference."""
    plan = two_person_two_project_plan(months=4)
    m1, m2, m3, _m4 = plan.horizon()

    plan = plan.model_copy(
        update={
            "closed_through": m3,
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=70.0, hours_actual=50.0),
                AllocationRow(project_id="proj_a", person_id="alice", month=m2, hours_assigned=90.0, hours_actual=95.0),
                AllocationRow(project_id="proj_a", person_id="alice", month=m3, hours_assigned=60.0, hours_actual=61.0),
            ],
        }
    )
    result = solve(plan)
    assert result.feasible

    out_path = tmp_path / "budget_proj_a.csv"
    export_budget_summary(plan, result.hours_assigned, "proj_a", out_path)

    rows = [r for r in csv.reader(open(out_path)) if r]  # drop the blank separator row
    month_row = next(r for r in rows if r[0] == "month")
    planned_row = next(r for r in rows if r[0] == "planned_spend")
    actual_row = next(r for r in rows if r[0] == "actual_spend")
    months_in_row = month_row[1:]

    def value_for(row: list[str], month_str: str) -> float:
        return float(row[1:][months_in_row.index(month_str)])

    # alice's rate is fixed in the fixture; check the *ratio* survives, confirming
    # distinct hours_assigned per month rather than a value that just tracks actual.
    assert value_for(planned_row, str(m1)) != value_for(actual_row, str(m1))
    assert value_for(planned_row, str(m2)) != value_for(actual_row, str(m2))
    assert value_for(planned_row, str(m3)) != value_for(actual_row, str(m3))

    # And each month's planned figure is genuinely distinct from the others —
    # not all collapsed to whatever the live solve currently shows.
    planned_m1 = value_for(planned_row, str(m1))
    planned_m2 = value_for(planned_row, str(m2))
    planned_m3 = value_for(planned_row, str(m3))
    assert len({planned_m1, planned_m2, planned_m3}) == 3


def test_as_of_month_blanks_only_the_actual_side(tmp_path: Path):
    plan = two_person_two_project_plan(months=4)
    m1, m2, m3, m4 = plan.horizon()

    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=70.0, hours_actual=65.0),
            ],
        }
    )
    result = solve(plan)
    assert result.feasible

    out_path = tmp_path / "budget_proj_a.csv"
    # as_of m2: m1 is known (before m2), m2 itself and everything after is not.
    export_budget_summary(plan, result.hours_assigned, "proj_a", out_path, as_of_month=m2)

    rows = [r for r in csv.reader(open(out_path)) if r]
    by_label = {r[0]: r[1:] for r in rows}
    months_in_row = [str(m1), str(m2), str(m3), str(m4)]
    idx = {m: months_in_row.index(m) for m in months_in_row}

    # The planned side — including its cumulative and remaining — stays populated
    # for the whole PoP, same as planned_spend itself: these are forward budget
    # figures, not something that needs elapsed time to be meaningful.
    for label in ("planned_spend", "cumulative_planned_spend", "planned_funds_remaining"):
        assert all(by_label[label][idx[str(m)]] != "" for m in (m1, m2, m3, m4)), label

    # Only the actual side blanks from m2 onward (not yet knowable), while m1
    # (strictly before as_of_month) still shows real values.
    for label in ("actual_spend", "delta", "cumulative_actual_spend", "actual_funds_remaining"):
        assert by_label[label][idx[str(m1)]] != "", f"{label} for m1 should be populated"
        for m in (m2, m3, m4):
            assert by_label[label][idx[str(m)]] == "", f"{label} for {m} should be blank"
