"""Small hand-checked planning scenarios — `06-code-structure-and-dependencies.md`, tests/fixtures/."""

from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.capacity import Capacity
from allocsolver.models.people import Person
from allocsolver.models.plan import Plan
from allocsolver.models.projects import Project, RateStructure, RateType
from allocsolver.models.rates import Rate, WrapRate
from allocsolver.models.targets import Target, TargetType


def two_person_two_project_plan(
    *,
    hard_min: float = 0.0,
    soft_min: float = 40.0,
    soft_max: float = 120.0,
    hard_max: float = 160.0,
    hard_max_concurrent: int = 4,
    soft_max_concurrent: int = 2,
    target_type: TargetType = TargetType.SOFT,
    months: int = 2,
) -> Plan:
    horizon_start = Month(2027, 1)
    horizon_end = horizon_start.add(months - 1)
    month_list = Month.range(horizon_start, horizon_end)

    people = [
        Person(
            person_id="alice",
            name="Alice",
            active_from=horizon_start,
            hard_max_concurrent_projects=hard_max_concurrent,
            soft_max_concurrent_projects=soft_max_concurrent,
        ),
        Person(
            person_id="bob",
            name="Bob",
            active_from=horizon_start,
            hard_max_concurrent_projects=hard_max_concurrent,
            soft_max_concurrent_projects=soft_max_concurrent,
        ),
    ]
    projects = [
        Project(project_id="proj_a", name="Project A", pop_start=horizon_start, pop_end=horizon_end, rate_structure="direct"),
        Project(project_id="proj_b", name="Project B", pop_start=horizon_start, pop_end=horizon_end, rate_structure="direct"),
    ]
    rate_structures = [RateStructure(structure_id="direct", rate_type=RateType.PROJECT)]

    rates = [
        Rate(person_id=p.person_id, month=m, annual_salary=150_000) for p in people for m in month_list
    ]
    wrap_rates = [
        WrapRate(month=m, workable_hours=160, project_wrap_rate=1.8, oh_wrap_rate=1.5, fee_wrap_rate=1.1)
        for m in month_list
    ]
    capacity = [
        Capacity(person_id=p.person_id, month=m, available_hours=160) for p in people for m in month_list
    ]
    bounds = [
        Bounds(
            project_id=proj.project_id,
            person_id=p.person_id,
            month=m,
            hard_min=hard_min,
            soft_min=soft_min,
            soft_max=soft_max,
            hard_max=hard_max,
        )
        for proj in projects
        for p in people
        for m in month_list
    ]
    targets = [
        Target(project_id=proj.project_id, month=m, labor_spend_target=15_000, target_type=target_type)
        for proj in projects
        for m in month_list
    ]

    return Plan(
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        people=people,
        projects=projects,
        rate_structures=rate_structures,
        rates=rates,
        wrap_rates=wrap_rates,
        capacity=capacity,
        bounds=bounds,
        targets=targets,
        allocation=[],
    )
