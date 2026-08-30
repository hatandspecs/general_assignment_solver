import pytest

from allocsolver.reports.staffing_balance import staffing_balance
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan

# Fixture rate: annual_salary=150,000, workable_hours=160, project_wrap_rate=1.8
# -> base_hourly = 150000/12/160 = 78.125, R = 78.125 * 1.8 = 140.625/hour.
_RATE = 140.625


def test_balance_demand_comes_from_targets_not_soft_max():
    # soft_max is set far away from the fixture's fixed $15,000-per-project target,
    # so a demand figure that leaked from bounds instead of targets would show up
    # immediately as a mismatch.
    plan = two_person_two_project_plan(soft_max=150.0, hard_max=160.0)
    balances = staffing_balance(plan)
    m1 = plan.horizon_start
    row = next(b for b in balances if b.month == m1)

    # Two projects x $15,000 target each -- independent of soft_max/bounds entirely.
    assert row.demand_dollars == pytest.approx(2 * 15_000)
    # Two people x 160h capacity, valued at the standard project rate.
    assert row.capacity_dollars == pytest.approx(2 * 160.0 * _RATE)
    assert row.balance_dollars == pytest.approx(row.capacity_dollars - row.demand_dollars)


def test_balance_can_show_a_genuine_shortfall_even_after_solving():
    """Regression: demand used to come from *realized* solved hours, which are
    physically capped at real capacity (C3) -- so demand could never exceed
    capacity no matter how the projects' targets were set, making a genuine
    shortfall mathematically impossible to ever report. Targets aren't
    capacity-capped, so a shortfall must still show even once the plan is solved
    and realized hours are themselves at (or below) full capacity."""
    plan = two_person_two_project_plan()
    # Fixture capacity is fixed at 2 people x 160h x _RATE = 45,000. Push each
    # project's target well above that combined total.
    high_targets = [t.model_copy(update={"labor_spend_target": 30_000}) for t in plan.targets]
    plan = plan.model_copy(update={"targets": high_targets})

    result = solve(plan)
    assert result.feasible

    balances = staffing_balance(plan)
    m1 = plan.horizon_start
    row = next(b for b in balances if b.month == m1)
    assert row.demand_dollars == pytest.approx(2 * 30_000)
    assert row.balance_dollars < 0  # a genuine shortfall, not clamped to zero
