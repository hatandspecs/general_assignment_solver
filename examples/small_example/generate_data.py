#!/usr/bin/env python
"""Generates the small example's data files: 8 people, 3 staggered projects, a
6-month horizon, with the first month already closed (bootstrap history) so
`run_example.py`'s reforecast demo has something to show immediately.

Deliberately explicit rather than randomly generated (contrast with
`examples/medium_example/generate_data.py`): every number here is a specific line
you can point to, not a seeded random draw. This is the smallest scenario in the
repo — meant to be read end to end in a few minutes, and the one
`docs/09-planner-tutorial.md` and the Grist planner UI (`grist_planner/`) both use.

Run once (writes to ./data/, mirroring `allocsolver/io/local.py`'s file layout):

    python generate_data.py
"""

import random
from collections import defaultdict
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
WORKABLE_HOURS = 168.0  # a round, easy-to-check number
CLOSED_THROUGH = Month(2027, 1)  # bootstrap: month 1 starts out already closed
SEED = 42

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

NORMAL_NOISE = (0.98, 1.03)  # matches io/synthetic.py's live-simulation noise band


def _bootstrap_closed_month_actuals(
    rng: random.Random, bounds: list[Bounds], capacity_index: dict[tuple[str, Month], float]
) -> list[AllocationRow]:
    """Synthetic actuals for `CLOSED_THROUGH`, scaled to never exceed a person's
    real capacity even when they're on multiple projects that month at once —
    same proportional-scaling approach as `examples/medium_example/generate_data.py`'s
    `generate_closed_month_actuals`, simplified to one bootstrap month."""
    by_person: dict[str, list[Bounds]] = defaultdict(list)
    for b in bounds:
        if b.month == CLOSED_THROUGH:
            by_person[b.person_id].append(b)

    rows = []
    for person_id, person_bounds in by_person.items():
        cap = capacity_index.get((person_id, CLOSED_THROUGH), 0.0)
        naive_actual = {b.project_id: b.soft_max * rng.uniform(*NORMAL_NOISE) for b in person_bounds}
        total = sum(naive_actual.values())
        scale = min(1.0, cap / total) if total > 0 else 1.0

        actuals = {pid: round(v * scale, 2) for pid, v in naive_actual.items()}
        excess = round(sum(actuals.values()) - cap, 2)
        if excess > 0:
            largest = max(actuals, key=actuals.get)
            actuals[largest] = round(actuals[largest] - excess, 2)

        for b in person_bounds:
            rows.append(
                AllocationRow(
                    project_id=b.project_id,
                    person_id=person_id,
                    month=CLOSED_THROUGH,
                    hours_assigned=b.soft_max,
                    hours_actual=actuals[b.project_id],
                    locked=False,
                    solve_id="bootstrap-history",
                )
            )
    return rows


def main() -> None:
    out_dir = Path(__file__).parent / "data"
    rng = random.Random(SEED)

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
    capacity_index = {(c.person_id, c.month): c.available_hours for c in capacity}

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
            # simple and legible, unlike the medium example's capacity-driven calibration.
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

    allocation = _bootstrap_closed_month_actuals(rng, bounds, capacity_index)

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
        allocation=allocation,
        closed_through=CLOSED_THROUGH,
    )

    from allocsolver.io.local import save_plan
    from allocsolver.io.pre_assignments import clear_pre_assignments

    save_plan(plan, out_dir)
    clear_pre_assignments(out_dir)
    print(
        f"Wrote small example data to {out_dir}: {len(people)} people, {len(projects)} projects, "
        f"{len(bounds)} bounds rows, closed through {CLOSED_THROUGH}."
    )


if __name__ == "__main__":
    main()
