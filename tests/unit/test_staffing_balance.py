import pytest

from allocsolver.reports.staffing_balance import staffing_balance
from allocsolver.solve.run import solve
from tests.fixtures import two_person_two_project_plan

# Fixture rate: annual_salary=150,000, workable_hours=160, project_wrap_rate=1.8
# -> base_hourly = 150000/12/160 = 78.125, R = 78.125 * 1.8 = 140.625/hour.
_RATE = 140.625


def test_pre_solve_balance_uses_soft_max_as_demand_proxy_in_dollars():
    plan = two_person_two_project_plan(soft_max=100.0)
    balances = staffing_balance(plan)
    m1 = plan.horizon_start
    row = next(b for b in balances if b.month == m1)

    # Two people x two projects x soft_max 100h x rate 140.625 of intended demand.
    assert row.demand_dollars == pytest.approx(2 * 2 * 100.0 * _RATE)
    # Two people x 160h capacity, valued at the standard project rate.
    assert row.capacity_dollars == pytest.approx(2 * 160.0 * _RATE)
    assert row.balance_dollars == pytest.approx(row.capacity_dollars - row.demand_dollars)


def test_post_solve_balance_uses_real_hours_assigned_in_dollars():
    plan = two_person_two_project_plan()
    result = solve(plan)
    assert result.feasible

    balances = staffing_balance(plan, hours_assigned=result.hours_assigned)
    m1 = plan.horizon_start
    row = next(b for b in balances if b.month == m1)
    expected_demand_dollars = sum(h * _RATE for (_p, _w, m), h in result.hours_assigned.items() if m == m1)
    assert row.demand_dollars == pytest.approx(expected_demand_dollars)
