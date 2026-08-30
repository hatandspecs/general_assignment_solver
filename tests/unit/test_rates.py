import pytest

from allocsolver.costing.rates import loaded_rate
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.capacity import Capacity
from allocsolver.models.people import Person
from allocsolver.models.plan import Plan
from allocsolver.models.projects import Project, RateStructure, RateType
from allocsolver.models.rates import Rate, WrapRate
from allocsolver.models.targets import Target


def _plan_with_rate_type(rate_type: RateType) -> Plan:
    m = Month(2027, 1)
    return Plan(
        horizon_start=m,
        horizon_end=m,
        people=[Person(person_id="alice", name="Alice", active_from=m)],
        projects=[Project(project_id="p", name="P", pop_start=m, pop_end=m, rate_structure="s")],
        rate_structures=[RateStructure(structure_id="s", rate_type=rate_type)],
        rates=[Rate(person_id="alice", month=m, annual_salary=192_000)],  # base_hourly = 192000/12/160 = 100
        wrap_rates=[WrapRate(month=m, workable_hours=160, project_wrap_rate=2.0, oh_wrap_rate=1.5, fee_wrap_rate=1.1)],
        capacity=[Capacity(person_id="alice", month=m, available_hours=160)],
        bounds=[Bounds(project_id="p", person_id="alice", month=m, soft_max=160, hard_max=160)],
        targets=[Target(project_id="p", month=m, labor_spend_target=1000)],
    )


@pytest.mark.parametrize(
    "rate_type, expected_multiplier",
    [(RateType.PROJECT, 2.0), (RateType.OH, 1.5), (RateType.FEE, 1.1)],
)
def test_selection_not_stacking(rate_type: RateType, expected_multiplier: float):
    """Resolved [OPEN-2]: exactly one wrap rate applies, never a combination."""
    plan = _plan_with_rate_type(rate_type)
    m = Month(2027, 1)
    rate = loaded_rate(plan, "alice", m, "p")
    base_hourly = 192_000 / 12 / 160
    assert rate == pytest.approx(base_hourly * expected_multiplier)
