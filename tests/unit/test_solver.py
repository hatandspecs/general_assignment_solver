"""Property tests from `04-solver-design.md`, "Testing the model"."""

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.calendar import Month
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan


def test_feasible():
    plan = two_person_two_project_plan()
    result = solve(plan)
    assert result.feasible


def test_capacity_respected():
    plan = two_person_two_project_plan()
    result = solve(plan)
    assert result.feasible

    by_person_month: dict[tuple[str, Month], float] = {}
    for (_, w, m), hours in result.hours_assigned.items():
        by_person_month[(w, m)] = by_person_month.get((w, m), 0.0) + hours

    capacity_index = {(c.person_id, c.month): c.available_hours for c in plan.capacity}
    for key, total_hours in by_person_month.items():
        assert total_hours <= capacity_index[key] + 1e-6


def test_semi_continuity():
    """Every nonzero x is at least its hard_min."""
    plan = two_person_two_project_plan(hard_min=10.0, soft_min=40.0, soft_max=120.0, hard_max=160.0)
    result = solve(plan)
    assert result.feasible
    for hours in result.hours_assigned.values():
        assert hours < 1e-6 or hours >= 10.0 - 1e-6


def test_fixed_cells_honored():
    """Locked cells match input exactly, and are excluded from the churn objective."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    plan = plan.model_copy(
        update={
            "allocation": [
                AllocationRow(
                    project_id="proj_a", person_id="alice", month=m1, hours_assigned=77.0, locked=True
                )
            ]
        }
    )
    result = solve(plan)
    assert result.feasible
    assert result.hours_assigned[("proj_a", "alice", m1)] == 77.0


def test_closed_month_fixes_to_actuals():
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(
                    project_id="proj_a",
                    person_id="alice",
                    month=m1,
                    hours_assigned=999.0,  # should be ignored: closed months fix to actuals
                    hours_actual=55.0,
                )
            ],
        }
    )
    result = solve(plan)
    assert result.feasible
    assert result.hours_assigned[("proj_a", "alice", m1)] == 55.0


def test_closed_month_actual_exceeding_hard_max_is_not_infeasible():
    """A closed month's actual is historical fact, not a new bound to satisfy — a
    true-up-style actual that landed above the cell's hard_max must not make the
    plan infeasible (regression: C1/C2 must not apply to fixed cells)."""
    plan = two_person_two_project_plan(soft_min=40.0, soft_max=90.0, hard_max=100.0)  # actual below will exceed hard_max
    m1 = plan.horizon_start
    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=90.0, hours_actual=110.0),
            ],
        }
    )
    result = solve(plan)
    assert result.feasible
    assert result.hours_assigned[("proj_a", "alice", m1)] == 110.0


def test_fragmentation_tiers():
    """No person exceeds hard_maxproj; exceeding soft_maxproj only with a nonzero frag charge."""
    plan = two_person_two_project_plan(hard_max_concurrent=1, soft_max_concurrent=1)
    result = solve(plan)
    assert result.feasible

    by_person_month: dict[tuple[str, Month], int] = {}
    for (_, w, m), hours in result.hours_assigned.items():
        if hours > 1e-6:
            by_person_month[(w, m)] = by_person_month.get((w, m), 0) + 1

    for count in by_person_month.values():
        assert count <= 1  # hard_max_concurrent_projects


def test_churn_sanity():
    """Re-solving with the prior solve's own result as baseline returns it unchanged."""
    plan = two_person_two_project_plan()
    first = solve(plan)
    assert first.feasible

    second = solve(plan, baseline=first.hours_assigned)
    assert second.feasible
    for cell, hours in first.hours_assigned.items():
        assert second.hours_assigned[cell] == hours
