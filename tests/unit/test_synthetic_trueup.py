"""The final-month true-up in `io/synthetic.py`: a project should never be left
with unspent labor_budget once its PoP ends — landing at most 0.1%-1% over it."""

import random

from allocsolver.costing.rates import loaded_rate
from allocsolver.io.synthetic import simulate_actuals_for_month
from allocsolver.models.plan import Plan
from tests.fixtures import two_person_two_project_plan


def _with_labor_budgets(plan: Plan, budgets: dict[str, float]) -> Plan:
    data = plan.model_dump(mode="json")
    for p in data["projects"]:
        if p["project_id"] in budgets:
            p["labor_budget"] = budgets[p["project_id"]]
    return Plan.model_validate(data)


def test_final_month_trues_up_within_tolerance_in_both_directions():
    """Both fixture projects share the same pop_end (month 2), so this exercises the
    true-up pushing hours *up* to avoid underspend (proj_a, budget above its natural
    2-month cost) and *down* to avoid overspend beyond the tolerance (proj_b, budget
    below it) in the same run."""
    plan = two_person_two_project_plan(months=2)
    m1, m2 = plan.horizon()
    # Natural 2-month cost at ~1.0x noise: proj_a ~160h/mo, proj_b ~80h/mo, at ~140.625/h
    # -> proj_a ~45,000 naturally, proj_b ~22,500 naturally.
    plan = _with_labor_budgets(plan, {"proj_a": 50_000.0, "proj_b": 18_000.0})

    hours_assigned_m1 = {
        ("proj_a", "alice", m1): 80.0,
        ("proj_a", "bob", m1): 80.0,
        ("proj_b", "alice", m1): 40.0,
        ("proj_b", "bob", m1): 40.0,
    }
    rng = random.Random(0)
    rows_m1 = simulate_actuals_for_month(plan, m1, hours_assigned_m1, rng)
    plan = plan.model_copy(update={"allocation": rows_m1})

    hours_assigned_m2 = {
        ("proj_a", "alice", m2): 80.0,
        ("proj_a", "bob", m2): 80.0,
        ("proj_b", "alice", m2): 40.0,
        ("proj_b", "bob", m2): 40.0,
    }
    rows_m2 = simulate_actuals_for_month(plan, m2, hours_assigned_m2, rng)

    for project_id, budget in (("proj_a", 50_000.0), ("proj_b", 18_000.0)):
        cumulative = sum(
            r.hours_actual * loaded_rate(plan, r.person_id, r.month, project_id)
            for r in [*rows_m1, *rows_m2]
            if r.project_id == project_id
        )
        assert cumulative >= budget - 1e-3, f"{project_id} left budget unspent: {cumulative} < {budget}"
        assert cumulative <= budget * 1.011, f"{project_id} overspent past tolerance: {cumulative} > {budget * 1.011}"

    # Capacity wasn't the binding constraint for either direction in this scenario.
    for r in rows_m2:
        assert r.hours_actual <= plan.capacity_of(r.person_id, m2).available_hours + 1e-6
