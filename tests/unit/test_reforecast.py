import pytest

from allocsolver.models.allocation import AllocationRow
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.reforecast.variance import target_variance
from tests.fixtures import two_person_two_project_plan


def _plan_with_actuals(hours_actual_alice: float, hours_actual_bob: float):
    plan = two_person_two_project_plan(months=3)
    m1 = plan.horizon_start
    return plan.model_copy(
        update={
            "closed_through": m1,
            "allocation": [
                AllocationRow(project_id="proj_a", person_id="alice", month=m1, hours_assigned=80, hours_actual=hours_actual_alice),
                AllocationRow(project_id="proj_a", person_id="bob", month=m1, hours_assigned=80, hours_actual=hours_actual_bob),
            ],
        }
    )


def test_variance_is_target_minus_actual():
    plan = _plan_with_actuals(hours_actual_alice=40, hours_actual_bob=40)
    m1 = plan.horizon_start
    # target = 15_000; actual_cost = (40 + 40) * R (R = base_hourly * project_wrap_rate)
    variance = target_variance(plan, "proj_a", m1)
    assert variance < 15_000  # some actual cost was incurred, so variance is less than the full target


def test_proportional_split_sums_to_variance():
    plan = _plan_with_actuals(hours_actual_alice=40, hours_actual_bob=40)
    m1 = plan.horizon_start
    proposal = propose_reforecast(plan, "proj_a", m1)
    original_totals = sum(
        t.labor_spend_target for t in plan.targets if t.project_id == "proj_a" and t.month > m1
    )
    new_total = sum(proposal.updated_targets.values())
    assert new_total == pytest.approx(original_totals + proposal.variance)
