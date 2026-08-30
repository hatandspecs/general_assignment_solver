#!/usr/bin/env python
"""Generates the medium example's data files, per `unstructured_notes_medium_example.md`.

Run once (or whenever you want a fresh random scenario):

    python generate_data.py [--seed 42]

Writes one JSON file per table into ./data/, mirroring the star schema in
`03-data-model.md` so each file maps to what would be one Grist table.

A few numbers in the spec weren't given precisely and are documented here as this
generator's assumptions, flagged so they're easy to find and change:

  - OH and fee wrap rates: only the project wrap rate was given a distribution
    (~2.9% +/- 2%). OH and fee are illustrative government-contracting-typical
    magnitudes (~50% and ~8%), not specified numbers from the notes.
  - Ramp-up: the first month of every project's PoP is staffed by roughly 40% of
    its eventual crew (rounded up, at least one person), matching the "PIs and key
    technical contributors first" pattern in `01-system-overview.md`.
  - Assignment intensity: each person's role on a project is either "primary"
    (60-100% of that month's personal capacity) or "secondary" (20-40%), which
    only matters for generating plausible bounds/targets — the solver decides
    actual hours.
"""

import argparse
import random
from pathlib import Path

from allocsolver.costing.rates import loaded_rate
from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month, workable_hours
from allocsolver.models.capacity import Capacity
from allocsolver.models.people import Person
from allocsolver.models.plan import Plan
from allocsolver.models.projects import Project, ProjectStatus, RateStructure, RateType
from allocsolver.models.rates import Rate, WrapRate
from allocsolver.models.targets import Target, TargetType

HORIZON_START = Month(2027, 1)
HORIZON_END = Month(2031, 12)  # 5 calendar years
NUM_PEOPLE = 50
NUM_PROJECT_SLOTS_RANGE = (10, 12)
POP_LENGTH_RANGE_MONTHS = (6, 18)
SALARY_RANGE = (100_000, 250_000)
OCTOBER_RAISE_RANGE = (0.01, 0.04)
PROJECT_WRAP_RATE_MEAN, PROJECT_WRAP_RATE_STDEV = 1.029, 0.02
OH_WRAP_RATE_MEAN, OH_WRAP_RATE_STDEV = 1.50, 0.05  # assumption, not in the spec
FEE_WRAP_RATE_MEAN, FEE_WRAP_RATE_STDEV = 1.08, 0.01  # assumption, not in the spec
CLOSED_THROUGH = Month(2027, 2)  # first two months treated as already-closed, actualed


def generate_people(rng: random.Random) -> tuple[list[Person], dict[str, float]]:
    """35 people at 100% FTE availability to this portfolio, 10 at 75%, 5 at 25%."""
    fte_levels = [1.0] * 35 + [0.75] * 10 + [0.25] * 5
    rng.shuffle(fte_levels)

    first_names = [f"firstname_{i}" for i in range(1, NUM_PEOPLE + 1)]
    last_names = [f"lastname_{i}" for i in range(1, NUM_PEOPLE + 1)]
    rng.shuffle(last_names)

    people = []
    fte_by_person: dict[str, float] = {}
    for i in range(NUM_PEOPLE):
        person_id = f"person_{i + 1}"
        people.append(
            Person(
                person_id=person_id,
                name=f"{first_names[i]} {last_names[i]}",
                active_from=HORIZON_START,
                active_to=None,
            )
        )
        fte_by_person[person_id] = fte_levels[i]
    return people, fte_by_person


def generate_wrap_rates(rng: random.Random) -> list[WrapRate]:
    """Dense per month; the three multipliers change only at each UFY boundary (July 1)."""
    months = Month.range(HORIZON_START, HORIZON_END)
    ufy_draws: dict[int, tuple[float, float, float]] = {}
    rows = []
    for month in months:
        ufy = month.ufy()
        if ufy not in ufy_draws:
            ufy_draws[ufy] = (
                max(1.001, rng.gauss(PROJECT_WRAP_RATE_MEAN, PROJECT_WRAP_RATE_STDEV)),
                max(1.001, rng.gauss(OH_WRAP_RATE_MEAN, OH_WRAP_RATE_STDEV)),
                max(1.001, rng.gauss(FEE_WRAP_RATE_MEAN, FEE_WRAP_RATE_STDEV)),
            )
        project_wr, oh_wr, fee_wr = ufy_draws[ufy]
        rows.append(
            WrapRate(
                month=month,
                workable_hours=workable_hours(month),
                project_wrap_rate=project_wr,
                oh_wrap_rate=oh_wr,
                fee_wrap_rate=fee_wr,
            )
        )
    return rows


def generate_rates(rng: random.Random, people: list[Person]) -> list[Rate]:
    """Dense per person per month; annual_salary steps up at each October."""
    months = Month.range(HORIZON_START, HORIZON_END)
    rows = []
    for person in people:
        salary = rng.uniform(*SALARY_RANGE)
        raise_by_year: dict[int, float] = {}
        for month in months:
            if month.month == 10 and month.year not in raise_by_year:
                raise_by_year[month.year] = rng.uniform(*OCTOBER_RAISE_RANGE)
                salary *= 1 + raise_by_year[month.year]
            rows.append(Rate(person_id=person.person_id, month=month, annual_salary=round(salary, 2)))
    return rows


def generate_capacity(people: list[Person], fte_by_person: dict[str, float], wrap_rates: list[WrapRate]) -> list[Capacity]:
    workable_by_month = {wr.month: wr.workable_hours for wr in wrap_rates}
    rows = []
    for person in people:
        fte = fte_by_person[person.person_id]
        for month, hours in workable_by_month.items():
            rows.append(Capacity(person_id=person.person_id, month=month, available_hours=round(fte * hours, 2)))
    return rows


def generate_project_chains(rng: random.Random) -> list[Project]:
    """~10-12 concurrent "slots", each a chain of back-to-back contracts covering the horizon."""
    num_slots = rng.randint(*NUM_PROJECT_SLOTS_RANGE)
    rate_structures_by_slot = {}
    for slot in range(num_slots):
        roll = rng.random()
        if roll < 0.08:
            rate_structures_by_slot[slot] = "oh_charged"
        elif roll < 0.14:
            rate_structures_by_slot[slot] = "fee_charged"
        else:
            rate_structures_by_slot[slot] = "direct"

    projects: list[Project] = []
    for slot in range(num_slots):
        # Naming per the spec: project_1, then project_1b, project_1c, ... (skip "a").
        suffix_chars = iter("bcdefghijklmnopqrstuvwxyz")
        cursor = HORIZON_START
        first = True
        while cursor <= HORIZON_END:
            pop_len = rng.randint(*POP_LENGTH_RANGE_MONTHS)
            pop_end = min(HORIZON_END, cursor.add(pop_len - 1))
            name_suffix = "" if first else next(suffix_chars)
            project_id = f"project_{slot + 1}{name_suffix}"
            projects.append(
                Project(
                    project_id=project_id,
                    name=f"Project {slot + 1}{name_suffix.upper()}",
                    pop_start=cursor,
                    pop_end=pop_end,
                    rate_structure=rate_structures_by_slot[slot],
                    travel_budget=round(rng.uniform(5_000, 50_000), 2),
                    odc_budget=round(rng.uniform(2_000, 30_000), 2),
                    status=ProjectStatus.ACTIVE,
                )
            )
            cursor = pop_end.add(1)
            first = False
    return projects


def assign_crews(rng: random.Random, projects: list[Project], people: list[Person]) -> dict[str, list[tuple[str, str]]]:
    """Per project chain (slot), a stable crew that carries across its own continuations.

    Returns {project_id: [(person_id, role), ...]} where role is "primary" or "secondary".
    """
    person_ids = [p.person_id for p in people]
    slot_of = {}
    for project in projects:
        slot = project.project_id.split("_")[1].rstrip("abcdefghijklmnopqrstuvwxyz")
        slot_of.setdefault(slot, []).append(project)

    concurrent_count: dict[str, int] = {pid: 0 for pid in person_ids}
    assignments: dict[str, list[tuple[str, str]]] = {}

    for slot, chain in slot_of.items():
        crew_size = rng.randint(3, 7)
        # Respect each person's hard fragmentation limit (default 4) when forming crews,
        # so the synthetic input data itself doesn't force a hard-constraint violation.
        eligible_candidates = [pid for pid in person_ids if concurrent_count[pid] < 4]
        candidates = sorted(eligible_candidates, key=lambda pid: (concurrent_count[pid], rng.random()))
        crew = candidates[:crew_size]
        for pid in crew:
            concurrent_count[pid] += 1
        roles = ["primary"] * max(1, crew_size // 2) + ["secondary"] * (crew_size - max(1, crew_size // 2))
        rng.shuffle(roles)
        crew_roles = list(zip(crew, roles))
        for project in chain:
            assignments[project.project_id] = crew_roles

    return assignments


def generate_bounds_and_targets(
    rng: random.Random,
    projects: list[Project],
    crews: dict[str, list[tuple[str, str]]],
    capacity_index: dict[tuple[str, Month], float],
    rate_fn,
) -> tuple[list[Bounds], list[Target]]:
    bounds: list[Bounds] = []
    targets: list[Target] = []
    horizon = set(Month.range(HORIZON_START, HORIZON_END))

    for project in projects:
        crew = crews[project.project_id]
        pop_months = [m for m in project.months() if m in horizon]
        if not pop_months:
            continue
        ramp_crew_size = max(1, round(len(crew) * 0.4))
        ramp_crew = set(pid for pid, _ in crew[:ramp_crew_size])

        for month_idx, month in enumerate(pop_months):
            active_crew = crew if month_idx > 0 else [(pid, role) for pid, role in crew if pid in ramp_crew]
            target_dollars = 0.0

            for person_id, role in active_crew:
                cap = capacity_index.get((person_id, month), 0.0)
                if cap <= 0:
                    continue
                intensity = rng.uniform(0.6, 1.0) if role == "primary" else rng.uniform(0.2, 0.4)
                target_hours = intensity * cap
                soft_min = round(0.7 * target_hours, 2)
                soft_max = round(target_hours, 2)
                hard_max = round(min(cap, 1.15 * target_hours), 2)
                bounds.append(
                    Bounds(
                        project_id=project.project_id,
                        person_id=person_id,
                        month=month,
                        hard_min=0.0,
                        soft_min=soft_min,
                        soft_max=soft_max,
                        hard_max=max(hard_max, soft_max),
                        eligible=True,
                    )
                )
                target_dollars += soft_max * rate_fn(project.project_id, person_id, month)

            targets.append(
                Target(
                    project_id=project.project_id,
                    month=month,
                    labor_spend_target=round(target_dollars, 2),
                    target_tolerance=round(0.05 * target_dollars, 2),
                    target_type=TargetType.SOFT,
                )
            )

    return bounds, targets


def generate_closed_month_actuals(
    rng: random.Random, plan_bounds: list[Bounds], capacity_index: dict[tuple[str, Month], float]
) -> list[AllocationRow]:
    """For months <= CLOSED_THROUGH: a synthetic prior plan plus actuals that vary from it.

    Closed months fix `hours_assigned` (`04-solver-design.md`, C5), so a person's fixed
    hours across their *simultaneous* projects that month must not exceed their capacity —
    generating each project's hours independently could violate that, so this scales the
    naive per-project draws down proportionally when their sum would oversubscribe the month.
    """
    from collections import defaultdict

    by_person_month: dict[tuple[str, Month], list[Bounds]] = defaultdict(list)
    for b in plan_bounds:
        if b.month <= CLOSED_THROUGH:
            by_person_month[(b.person_id, b.month)].append(b)

    rows = []
    for (person_id, month), bounds_list in by_person_month.items():
        cap = capacity_index.get((person_id, month), 0.0)
        naive = {b.project_id: rng.uniform(0.85, 1.0) * b.soft_max for b in bounds_list}
        total_naive = sum(naive.values())
        scale = min(1.0, cap / total_naive) if total_naive > 0 else 1.0

        for b in bounds_list:
            planned = round(naive[b.project_id] * scale, 2)
            actual = round(min(cap, planned * rng.uniform(0.85, 1.15)), 2)
            rows.append(
                AllocationRow(
                    project_id=b.project_id,
                    person_id=person_id,
                    month=month,
                    hours_assigned=planned,
                    hours_actual=actual,
                    locked=False,
                    solve_id="synthetic-history",
                )
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    people, fte_by_person = generate_people(rng)
    wrap_rates = generate_wrap_rates(rng)
    rates = generate_rates(rng, people)
    capacity = generate_capacity(people, fte_by_person, wrap_rates)
    capacity_index = {(c.person_id, c.month): c.available_hours for c in capacity}

    projects = generate_project_chains(rng)
    rate_structures = [
        RateStructure(structure_id="direct", rate_type=RateType.PROJECT),
        RateStructure(structure_id="oh_charged", rate_type=RateType.OH),
        RateStructure(structure_id="fee_charged", rate_type=RateType.FEE),
    ]
    crews = assign_crews(rng, projects, people)

    # A rate-lookup-only Plan (bounds/targets not generated yet) so target dollars can
    # reuse the one real cost composition function rather than duplicating its logic.
    rate_lookup_plan = Plan(
        horizon_start=HORIZON_START,
        horizon_end=HORIZON_END,
        people=people,
        projects=projects,
        rate_structures=rate_structures,
        rates=rates,
        wrap_rates=wrap_rates,
        capacity=capacity,
        bounds=[],
        targets=[],
        allocation=[],
    )
    rate_fn = lambda project_id, person_id, month: loaded_rate(rate_lookup_plan, person_id, month, project_id)  # noqa: E731

    bounds, targets = generate_bounds_and_targets(rng, projects, crews, capacity_index, rate_fn)
    allocation = generate_closed_month_actuals(rng, bounds, capacity_index)

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

    save_plan(plan, args.out)
    print(f"Generated {len(people)} people, {len(projects)} projects, {len(bounds)} bounds rows.")
    print(f"Wrote data files to {args.out}")


if __name__ == "__main__":
    main()
