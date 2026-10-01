"""The import -> tweak -> solve -> import loop (`io/working_assignment.py`).

The properties that matter here are the ones the loop rests on: a constraint-violating
ballpark gets *in* (and is reported, not rejected), the solver pulls it back to
feasibility, and its own output is a valid starting point for the next iteration with
no conversion — so the loop is stable rather than drifting a little each time round.
"""

import pytest

from allocsolver.config import Weights, weights_for_adherence
from allocsolver.io.working_assignment import (
    WorkingAssignmentParseError,
    WorkingRow,
    audit,
    baseline_of,
    merged_allocation,
    parse_rows,
    permissive_bounds_for,
    to_csv,
)
from allocsolver.models.allocation import AllocationRow
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan


def _status(rows, project_id, person_id, month):
    return next(
        r.status for r in rows if r.project_id == project_id and r.person_id == person_id and r.month == month
    )


# --- parsing ---------------------------------------------------------------------


def test_csv_and_json_parse_identically():
    csv_text = (
        "project_id,person_id,month,hours,locked\n"
        "proj_a,alice,2027-01,100,true\n"
        "proj_b,bob,2027-01,80,false\n"
    )
    json_text = """
    [{"project_id": "proj_a", "person_id": "alice", "month": "2027-01", "hours": 100, "locked": true},
     {"project_id": "proj_b", "person_id": "bob", "month": "2027-01", "hours": 80, "locked": false}]
    """
    assert parse_rows(csv_text) == parse_rows(json_text)
    assert parse_rows(csv_text) == [
        WorkingRow("proj_a", "alice", Month(2027, 1), 100.0, True),
        WorkingRow("proj_b", "bob", Month(2027, 1), 80.0, False),
    ]


def test_hours_assigned_accepted_as_a_synonym_for_hours():
    """A sheet exported straight out of the Grist Allocation table uses the
    `AllocationRow` field name; it should import without being renamed first."""
    rows = parse_rows("project_id,person_id,month,hours_assigned,locked\nproj_a,alice,2027-01,42,x\n")
    assert rows == [WorkingRow("proj_a", "alice", Month(2027, 1), 42.0, True)]


def test_locked_column_is_optional_and_tolerant():
    rows = parse_rows("project_id,person_id,month,hours\nproj_a,alice,2027-01,42\n")
    assert rows[0].locked is False
    for text in ("yes", "Y", "TRUE", "1", "locked"):
        assert parse_rows(f"project_id,person_id,month,hours,locked\nproj_a,alice,2027-01,1,{text}\n")[0].locked
    for text in ("no", "N", "FALSE", "0", ""):
        assert not parse_rows(f"project_id,person_id,month,hours,locked\nproj_a,alice,2027-01,1,{text}\n")[0].locked


def test_parse_errors_name_the_offending_row():
    with pytest.raises(WorkingAssignmentParseError, match="line 3"):
        parse_rows(
            "project_id,person_id,month,hours\n"
            "proj_a,alice,2027-01,10\n"
            "proj_a,alice,nonsense,10\n"
        )
    with pytest.raises(WorkingAssignmentParseError, match="missing required column"):
        parse_rows("project_id,month,hours\nproj_a,2027-01,10\n")
    with pytest.raises(WorkingAssignmentParseError, match="negative"):
        parse_rows("project_id,person_id,month,hours\nproj_a,alice,2027-01,-5\n")


def test_csv_export_round_trips_through_the_parser():
    plan = two_person_two_project_plan()
    rows = [WorkingRow("proj_a", "alice", plan.horizon_start, 100.0, True)]
    plan = plan.model_copy(update={"allocation": merged_allocation(plan, rows, audit(plan, rows))})
    assert parse_rows(to_csv(plan)) == rows


# --- audit -----------------------------------------------------------------------


def test_audit_reports_violations_without_rejecting_them():
    """The whole point of the ballpark: it is allowed to be wrong, and told so."""
    plan = two_person_two_project_plan(hard_max=160.0)
    m1 = str(plan.horizon_start)
    rows = parse_rows(
        "project_id,person_id,month,hours\n"
        f"proj_a,alice,{m1},400\n"  # over this cell's hard_max of 160
        f"proj_a,carol,{m1},50\n"  # no such person
        f"proj_z,alice,{m1},50\n"  # no such project
        f"proj_a,alice,2099-01,50\n"  # outside the horizon
    )
    result = audit(plan, rows)

    assert _status(result, "proj_a", "alice", m1) == "above_hard_max"
    assert _status(result, "proj_a", "carol", m1) == "unknown_person"
    assert _status(result, "proj_z", "alice", m1) == "unknown_project"
    assert _status(result, "proj_a", "alice", "2099-01") == "out_of_horizon"

    # Only the out-of-bounds row is something the solver can act on; the other three
    # name cells it has no variable for.
    assert [r.applied for r in result if r.status == "above_hard_max"] == [True]
    assert all(not r.applied for r in result if r.status != "above_hard_max" and r.project_id)


def test_audit_reports_over_capacity_across_rows():
    """No single row is wrong; the person-month total is. 320h against 160h of capacity."""
    plan = two_person_two_project_plan()
    m1 = str(plan.horizon_start)
    rows = parse_rows(
        f"project_id,person_id,month,hours\nproj_a,alice,{m1},160\nproj_b,alice,{m1},160\n"
    )
    over = [r for r in audit(plan, rows) if r.status == "over_capacity"]
    assert len(over) == 1
    assert over[0].person_id == "alice"
    assert over[0].hours == 320.0
    assert "160" in over[0].detail


def test_audit_reports_over_concurrent_projects():
    plan = two_person_two_project_plan(hard_max_concurrent=1, soft_max_concurrent=1)
    m1 = str(plan.horizon_start)
    rows = parse_rows(f"project_id,person_id,month,hours\nproj_a,alice,{m1},40\nproj_b,alice,{m1},40\n")
    over = [r for r in audit(plan, rows) if r.status == "over_concurrent"]
    assert len(over) == 1
    assert over[0].hours == 2.0


def test_audit_flags_an_ineligible_cell_as_unusable():
    """The one violation the solver can't resolve: with no eligible Bounds row,
    `eligible_cells` generates no variable, so the ballpark's intent is dropped."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    bounds = [
        b.model_copy(update={"eligible": False})
        if (b.project_id, b.person_id, b.month) == ("proj_a", "alice", m1)
        else b
        for b in plan.bounds
    ]
    plan = Plan.model_validate({**plan.model_dump(mode="json"), "bounds": [b.model_dump(mode="json") for b in bounds]})

    rows = [WorkingRow("proj_a", "alice", m1, 100.0)]
    result = audit(plan, rows)
    assert _status(result, "proj_a", "alice", str(m1)) == "not_eligible"
    assert not result[0].applied
    assert "eligible=False" in result[0].detail

    # ...and `permissive_bounds_for` is the opt-in that fixes it.
    new_bounds = permissive_bounds_for(plan, rows, result)
    assert len(new_bounds) == 1
    assert new_bounds[0].eligible is True
    assert new_bounds[0].hard_min == 0.0


def test_audit_leaves_a_clean_ballpark_clean():
    plan = two_person_two_project_plan()
    m1 = str(plan.horizon_start)
    rows = parse_rows(f"project_id,person_id,month,hours\nproj_a,alice,{m1},100\nproj_b,bob,{m1},100\n")
    assert all(r.status == "ok" and r.applied for r in audit(plan, rows))


# --- merge -----------------------------------------------------------------------


def test_merge_replaces_open_months_and_preserves_closed_ones():
    plan = two_person_two_project_plan(months=2)
    m1, m2 = plan.horizon_start, plan.horizon_start.add(1)
    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=50, hours_actual=55),
                AllocationRow(project_id="proj_a", person_id="alice", month=m2, hours_assigned=999),
                AllocationRow(project_id="proj_b", person_id="bob", month=m2, hours_assigned=999),
            ],
        }
    )
    rows = [WorkingRow("proj_a", "alice", m2, 70.0, True)]
    merged = merged_allocation(plan, rows, audit(plan, rows))

    closed = [a for a in merged if a.month == m1]
    assert len(closed) == 1 and closed[0].hours_actual == 55

    # The open month is replaced, not upserted: bob's stale 999 is gone, because an
    # imported ballpark is a statement about the whole open horizon.
    open_rows = {(a.project_id, a.person_id): a for a in merged if a.month == m2}
    assert set(open_rows) == {("proj_a", "alice")}
    assert open_rows[("proj_a", "alice")].hours_assigned == 70.0
    assert open_rows[("proj_a", "alice")].locked is True


def test_merge_drops_rows_the_solver_cannot_see():
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    rows = [WorkingRow("proj_a", "carol", m1, 100.0), WorkingRow("proj_a", "alice", m1, 100.0)]
    merged = merged_allocation(plan, rows, audit(plan, rows))
    assert [(a.project_id, a.person_id) for a in merged] == [("proj_a", "alice")]


# --- the loop --------------------------------------------------------------------


def test_solver_pulls_an_infeasible_ballpark_back_to_feasibility():
    """Requirement 1 + 3, together: import something over capacity, unlocked, and the
    solve succeeds by shedding the excess rather than refusing the input."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    rows = [WorkingRow("proj_a", "alice", m1, 160.0), WorkingRow("proj_b", "alice", m1, 160.0)]
    audit_rows = audit(plan, rows)
    assert any(r.status == "over_capacity" for r in audit_rows)

    plan = plan.model_copy(update={"allocation": merged_allocation(plan, rows, audit_rows)})
    result = solve(plan, baseline=baseline_of(plan))

    assert result.feasible
    alice_m1 = sum(h for (_, w, m), h in result.hours_assigned.items() if w == "alice" and m == m1)
    assert alice_m1 <= plan.capacity_of("alice", m1).available_hours + 1e-6


def test_the_solved_result_is_a_fixed_point_of_the_next_iteration():
    """Requirement 4: the solve's output *is* the next pre-assignment, so feeding it
    straight back must return it unchanged. Without this the loop would drift on every
    round trip and a planner could never tell their own edits from solver churn.
    """
    plan = two_person_two_project_plan()
    first = solve(plan, baseline=baseline_of(plan))
    assert first.feasible

    rows = [
        WorkingRow(p, w, m, hours)
        for (p, w, m), hours in first.hours_assigned.items()
        if hours > 1e-9
    ]
    next_plan = plan.model_copy(update={"allocation": merged_allocation(plan, rows, audit(plan, rows))})
    second = solve(next_plan, baseline=baseline_of(next_plan))

    assert second.feasible
    for cell, hours in first.hours_assigned.items():
        assert second.hours_assigned[cell] == pytest.approx(hours, abs=0.01)


def _ballpark_plan():
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    ballpark = [
        WorkingRow("proj_a", "alice", m1, 100.0),
        WorkingRow("proj_b", "alice", m1, 50.0),
        WorkingRow("proj_a", "bob", m1, 50.0),
        WorkingRow("proj_b", "bob", m1, 100.0),
    ]
    plan = plan.model_copy(update={"allocation": merged_allocation(plan, ballpark, audit(plan, ballpark))})
    target = {r.cell: r.hours for r in ballpark}

    def distance(hours_assigned):
        return sum(abs(hours_assigned.get(cell, 0.0) - hours) for cell, hours in target.items())

    return plan, distance


def test_adherence_dial_moves_the_solve_toward_the_ballpark():
    """Requirement 1's actual payload: the ballpark has to *steer* the solve, and how
    hard is the planner's call. Monotone in the adherence weight, and `exact` reaches
    the ballpark itself."""
    plan, distance = _ballpark_plan()
    base = baseline_of(plan)

    distances = []
    for level in ("free", "loose", "close", "exact"):
        result = solve(plan, baseline=base, weights=weights_for_adherence(level))
        assert result.feasible, level
        distances.append(distance(result.hours_assigned))

    assert distances == sorted(distances, reverse=True), distances
    assert distances[0] > distances[-1]
    assert distances[-1] == pytest.approx(0.0, abs=0.01)  # `exact` reproduces it


def test_a_baseline_pins_the_orientation_even_at_the_default_weight():
    """At `free` the churn term only breaks ties — it does not reshape the plan. It
    still matters: with no baseline at all the solver is free to return the mirror
    image, which is the revision-to-revision instability `AGENTS.md` calls out.
    """
    plan, distance = _ballpark_plan()
    no_baseline = solve(plan, weights=weights_for_adherence("free"))
    churn_off = solve(plan, baseline=baseline_of(plan), weights=Weights(churn=0.0))
    with_baseline = solve(plan, baseline=baseline_of(plan), weights=weights_for_adherence("free"))

    assert no_baseline.feasible and churn_off.feasible and with_baseline.feasible
    assert distance(with_baseline.hours_assigned) < distance(churn_off.hours_assigned)
    assert distance(with_baseline.hours_assigned) == pytest.approx(
        distance(no_baseline.hours_assigned), abs=0.01
    )


def test_exact_adherence_can_cost_the_spend_target():
    """The honest cost of the top of the dial, asserted so it can't be forgotten: at
    `exact` the ballpark wins over the spend targets this tool exists to hit."""
    plan, _ = _ballpark_plan()
    base = baseline_of(plan)
    loose = solve(plan, baseline=base, weights=weights_for_adherence("loose"))
    exact = solve(plan, baseline=base, weights=weights_for_adherence("exact"))
    assert loose.feasible and exact.feasible
    assert exact.objective.target > loose.objective.target


def test_baseline_excludes_closed_months():
    """C5 pins closed months to actuals regardless, so charging churn against them
    would bill the objective for history it cannot change."""
    plan = two_person_two_project_plan(months=2)
    m1, m2 = plan.horizon_start, plan.horizon_start.add(1)
    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=50, hours_actual=55),
                AllocationRow(project_id="proj_a", person_id="alice", month=m2, hours_assigned=70),
            ],
        }
    )
    assert baseline_of(plan) == {("proj_a", "alice", m2): 70.0}
