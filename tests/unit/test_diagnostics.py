"""A bare `infeasible` is useless — `04-solver-design.md`, "Infeasibility diagnostics"."""

from allocsolver.models.allocation import AllocationRow
from allocsolver.solve.diagnostics import diagnose
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan


def test_infeasible_scenario_reports_capacity_binding():
    """Two locked cells for the same person/month alone demand more than their capacity."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    plan = plan.model_copy(
        update={
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=150, locked=True),
                AllocationRow(project_id="proj_b", person_id="alice", month=m1, hours_assigned=150, locked=True),
            ]
        }
    )  # alice's capacity that month is 160h; the two locked cells alone demand 300h.

    result = solve(plan)
    assert not result.feasible
    assert result.diagnostics is not None
    assert not result.diagnostics.is_empty()
    assert any(b.kind == "capacity" for b in result.diagnostics.binding)


def test_diagnose_is_always_feasible_and_returns_a_report():
    plan = two_person_two_project_plan()
    report = diagnose(plan)
    assert report is not None  # the elastic model is always feasible by construction
