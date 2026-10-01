"""Locks that can't hold, and the diagnostic that says so (`solve/locks.py`).

`AGENTS.md`: "An infeasible model needs to say why." Before this, locking cells into a
contradiction produced `INFEASIBLE. No binding constraints.` — the elastic relaxation
re-pins locked cells verbatim, so a lock-driven infeasibility makes the relaxation
infeasible too and its slack report comes back empty. Each test below locks cells into
one specific contradiction and asserts the report names it.
"""

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.plan import Plan
from allocsolver.models.targets import TargetType
from allocsolver.solve.locks import lock_conflicts
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan


def _with_locks(plan, *rows):
    return plan.model_copy(update={"allocation": list(rows)})


def _locked(project_id, person_id, month, hours):
    return AllocationRow(
        project_id=project_id, person_id=person_id, month=month, hours_assigned=hours, locked=True
    )


def test_locks_over_capacity_are_named():
    """320 locked hours against 160 of capacity. C3 is an equality with a non-negative
    idle term, so there is no feasible completion."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 160), _locked("proj_b", "alice", m1, 160))

    conflicts = lock_conflicts(plan)
    assert [c.kind for c in conflicts] == ["capacity"]
    assert conflicts[0].person_id == "alice"
    assert conflicts[0].locked_amount == 320.0
    assert conflicts[0].limit == 160.0
    assert "160" in conflicts[0].detail

    result = solve(plan)
    assert not result.feasible
    rendered = result.diagnostics.render()
    assert "cannot all hold" in rendered
    assert "alice" in rendered and "capacity" in rendered


def test_locks_over_the_concurrency_ceiling_are_named():
    """The case the elastic model structurally cannot report: C6's hard fragmentation
    ceiling has no slack variable in either model, so before `locks.py` this produced
    an empty diagnostic."""
    plan = two_person_two_project_plan(hard_max_concurrent=1, soft_max_concurrent=1)
    m1 = plan.horizon_start
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 40), _locked("proj_b", "alice", m1, 40))

    conflicts = lock_conflicts(plan)
    assert [c.kind for c in conflicts] == ["fragmentation"]
    assert conflicts[0].locked_amount == 2.0
    assert conflicts[0].limit == 1.0

    result = solve(plan)
    assert not result.feasible
    assert not result.diagnostics.is_empty()  # the regression this module exists for
    assert "fragmentation" in result.diagnostics.render()


def test_locks_over_a_hard_spend_target_are_named():
    plan = two_person_two_project_plan(target_type=TargetType.HARD)
    m1 = plan.horizon_start
    # Targets are $15k/project-month; 160h at this fixture's loaded rate blows past it.
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 160))

    conflicts = [c for c in lock_conflicts(plan) if c.kind == "hard_target"]
    assert len(conflicts) == 1
    assert conflicts[0].project_id == "proj_a"
    assert conflicts[0].limit == 15_000.0
    assert conflicts[0].locked_amount > 15_000.0


def test_a_soft_target_is_not_a_lock_conflict():
    """Only a HARD target carries the `spend <= target` ceiling. Overshooting a soft
    one is a penalty the objective absorbs, not a contradiction."""
    plan = two_person_two_project_plan(target_type=TargetType.SOFT)
    m1 = plan.horizon_start
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 160))
    assert [c for c in lock_conflicts(plan) if c.kind == "hard_target"] == []
    assert solve(plan).feasible


def test_a_lock_above_its_own_hard_max_is_not_a_conflict():
    """C1/C2 are skipped for fixed cells by design (`constraints.py`) — a lock
    overrides its cell's bounds rather than fighting them. Reporting it would be a
    false alarm, and the solve is genuinely feasible."""
    plan = two_person_two_project_plan(soft_max=90.0, hard_max=100.0)
    m1 = plan.horizon_start
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 150))

    assert lock_conflicts(plan) == []
    result = solve(plan)
    assert result.feasible
    assert result.hours_assigned[("proj_a", "alice", m1)] == 150.0


def test_a_lock_on_an_ineligible_cell_is_reported_on_a_feasible_solve():
    """Not an infeasibility — a silent no-op. `fixed_cells_and_values` iterates over
    eligible cells only, so this lock is dropped without comment, and a planner who set
    it has every reason to think it is holding."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    bounds = [
        b.model_copy(update={"eligible": False})
        if (b.project_id, b.person_id, b.month) == ("proj_a", "alice", m1)
        else b
        for b in plan.bounds
    ]
    plan = Plan.model_validate(
        {**plan.model_dump(mode="json"), "bounds": [b.model_dump(mode="json") for b in bounds]}
    )
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 100))

    conflicts = lock_conflicts(plan)
    assert [c.kind for c in conflicts] == ["ineligible"]
    assert conflicts[0].is_infeasible is False

    result = solve(plan)
    assert result.feasible
    assert [c.kind for c in result.lock_warnings] == ["ineligible"]
    assert ("proj_a", "alice", m1) not in result.hours_assigned


def test_closed_months_are_not_lock_conflicts():
    """C5 pins a closed month to `hours_actual` whatever its `locked` flag says, and an
    actual that overran capacity is history, not a conflict to resolve."""
    plan = two_person_two_project_plan(months=2)
    m1 = plan.horizon_start
    plan = plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(
                    project_id="proj_a",
                    person_id="alice",
                    month=m1,
                    hours_assigned=200,
                    hours_actual=200,
                    locked=True,
                ),
            ],
        }
    )
    assert lock_conflicts(plan) == []


def test_no_locks_means_no_conflicts():
    plan = two_person_two_project_plan()
    assert lock_conflicts(plan) == []
    result = solve(plan)
    assert result.feasible
    assert result.lock_warnings == []


def test_feasible_locks_produce_no_conflicts():
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    plan = _with_locks(plan, _locked("proj_a", "alice", m1, 80), _locked("proj_b", "alice", m1, 60))
    assert lock_conflicts(plan) == []
    result = solve(plan)
    assert result.feasible
    assert result.hours_assigned[("proj_a", "alice", m1)] == 80.0
    assert result.hours_assigned[("proj_b", "alice", m1)] == 60.0
