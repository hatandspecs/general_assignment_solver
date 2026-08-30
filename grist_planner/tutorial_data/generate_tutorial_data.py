#!/usr/bin/env python
"""Generates the small, hand-legible dataset `docs/09-planner-tutorial.md` walks
through: 8 people, 3 projects, a 6-month horizon, nothing pre-closed — a planner
starts the tutorial from the very first month.

Deliberately explicit rather than randomly generated (contrast with
`examples/medium_example/generate_data.py`): every number in the tutorial doc
should be traceable back to a specific line here, not a seeded random draw.

Run once (writes to ./data/, mirroring `allocsolver/io/local.py`'s file layout —
`deploy_planner.sh up` mounts this directory read-only and provisioning.py loads
it straight into Grist):

    python generate_tutorial_data.py
"""

from pathlib import Path

from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.capacity import Capacity
from allocsolver.models.people import Person
from allocsolver.models.plan import Plan
from allocsolver.models.projects import Project, ProjectStatus, RateStructure, RateType
from allocsolver.models.rates import Rate, WrapRate
from allocsolver.models.targets import Target, TargetType

HORIZON_START = Month(2027, 1)
HORIZON_END = Month(2027, 6)
MONTHS = Month.range(HORIZON_START, HORIZON_END)
WORKABLE_HOURS = 168.0  # a round, easy-to-check number for the tutorial

PEOPLE = [
    ("person_1", "Alicia Chen", 130_000),
    ("person_2", "Ben Torres", 115_000),
    ("person_3", "Carmen Ruiz", 140_000),
    ("person_4", "Dev Patel", 108_000),
    ("person_5", "Elena Kim", 122_000),
    ("person_6", "Farid Osei", 118_000),
    ("person_7", "Grace Liu", 135_000),
    ("person_8", "Hassan Ali", 110_000),
]

# (project_id, name, pop_start, pop_end, rate_structure, labor_budget, crew: [(person_id, monthly_hours)])
PROJECTS = [
    (
        "project_alpha",
        "Project Alpha",
        HORIZON_START,
        HORIZON_END,
        "direct",
        # 5 people at ~120h/month x 6 months x ~direct rate, rounded to a clean number.
        396_000.0,
        [("person_1", 140.0), ("person_2", 120.0), ("person_3", 100.0), ("person_4", 80.0), ("person_5", 60.0)],
    ),
    (
        "project_beta",
        "Project Beta",
        HORIZON_START,
        Month(2027, 4),
        "direct",
        # Ends mid-horizon — the tutorial's example of a project's final-month true-up.
        168_000.0,
        [("person_2", 40.0), ("person_6", 120.0), ("person_7", 100.0)],
    ),
    (
        "project_gamma",
        "Project Gamma",
        Month(2027, 3),
        HORIZON_END,
        "oh_charged",
        # Starts mid-horizon — the tutorial's example of onboarding a fresh crew.
        120_000.0,
        [("person_5", 60.0), ("person_8", 130.0)],
    ),
]


def main() -> None:
    out_dir = Path(__file__).parent / "data"

    people = [Person(person_id=pid, name=name, active_from=HORIZON_START, active_to=None) for pid, name, _ in PEOPLE]
    salary_by_person = {pid: salary for pid, _, salary in PEOPLE}

    rate_structures = [
        RateStructure(structure_id="direct", rate_type=RateType.PROJECT),
        RateStructure(structure_id="oh_charged", rate_type=RateType.OH),
    ]

    rates = [Rate(person_id=pid, month=m, annual_salary=salary_by_person[pid]) for pid in salary_by_person for m in MONTHS]

    wrap_rates = [
        WrapRate(month=m, workable_hours=WORKABLE_HOURS, project_wrap_rate=2.9, oh_wrap_rate=1.65, fee_wrap_rate=1.1)
        for m in MONTHS
    ]

    capacity = [Capacity(person_id=pid, month=m, available_hours=WORKABLE_HOURS) for pid in salary_by_person for m in MONTHS]

    projects = [
        Project(
            project_id=pid,
            name=name,
            pop_start=pop_start,
            pop_end=pop_end,
            rate_structure=rate_structure,
            labor_budget=labor_budget,
            travel_budget=10_000.0,
            odc_budget=5_000.0,
            status=ProjectStatus.ACTIVE,
        )
        for pid, name, pop_start, pop_end, rate_structure, labor_budget, _crew in PROJECTS
    ]

    bounds = []
    targets = []
    for pid, _name, pop_start, pop_end, _rs, labor_budget, crew in PROJECTS:
        pop_months = [m for m in Month.range(pop_start, pop_end) if m in set(MONTHS)]
        n_months = len(pop_months)
        for m in pop_months:
            target_dollars = 0.0
            for person_id, monthly_hours in crew:
                soft_min = round(0.85 * monthly_hours, 2)
                soft_max = monthly_hours
                hard_max = round(1.15 * monthly_hours, 2)
                bounds.append(
                    Bounds(
                        project_id=pid,
                        person_id=person_id,
                        month=m,
                        hard_min=0.0,
                        soft_min=soft_min,
                        soft_max=soft_max,
                        hard_max=hard_max,
                        eligible=True,
                    )
                )
            # Even split of the project's labor_budget across its own PoP months —
            # simple and legible for a tutorial, unlike the medium example's
            # capacity-driven calibration.
            target_dollars = labor_budget / n_months
            targets.append(
                Target(
                    project_id=pid,
                    month=m,
                    labor_spend_target=round(target_dollars, 2),
                    target_tolerance=round(0.05 * target_dollars, 2),
                    target_type=TargetType.SOFT,
                )
            )

    plan = Plan(
        horizon_start=HORIZON_START,
        horizon_end=HORIZON_END,
        people=people,
        projects=projects,
        rate_structures=rate_structures,
        rates=rates,
        wrap_rates=wrap_rates,
        capacity=capacity,
        bounds=bounds,
        targets=targets,
        allocation=[],
        closed_through=None,
    )

    from allocsolver.io.local import save_plan
    from allocsolver.io.pre_assignments import clear_pre_assignments

    save_plan(plan, out_dir)
    clear_pre_assignments(out_dir)
    print(f"Wrote tutorial data to {out_dir}: {len(people)} people, {len(projects)} projects, {len(bounds)} bounds rows.")


if __name__ == "__main__":
    main()
