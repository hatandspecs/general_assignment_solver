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
from collections import defaultdict
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
PROJECT_WRAP_RATE_MEAN, PROJECT_WRAP_RATE_STDEV = 2.9, 0.02 * 2.9  # ~2.9 +/- 2% (relative)
OH_WRAP_RATE_MEAN, OH_WRAP_RATE_STDEV = 1.65, 0.02 * 1.65
FEE_WRAP_RATE_MEAN, FEE_WRAP_RATE_STDEV = 1.1, 0.02 * 1.1
CLOSED_THROUGH = Month(2027, 2)  # first two months treated as already-closed, actualed


def generate_people(rng: random.Random) -> tuple[list[Person], dict[str, float]]:
    """35 people at 100% FTE availability to this portfolio, 10 at 75%, 5 at 25%."""
    fte_levels = [1.0] * 35 + [0.75] * 10 + [0.25] * 5
    rng.shuffle(fte_levels)

    # Per the spec: person_i is named "firstname_i lastname_i" — matching numbers, not
    # independently shuffled first/last name pools.
    people = []
    fte_by_person: dict[str, float] = {}
    for i in range(NUM_PEOPLE):
        person_id = f"person_{i + 1}"
        people.append(
            Person(
                person_id=person_id,
                name=f"firstname_{i + 1} lastname_{i + 1}",
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


def compute_capacity_dollars_by_month(
    capacity: list[Capacity], rates: list[Rate], wrap_rates: list[WrapRate]
) -> dict[Month, float]:
    """Same valuation as `staffing_balance._capacity_dollar_rate` (every hour priced
    at the direct project wrap rate) — this is the reference `generate_bounds_and_targets`
    calibrates demand against, so the generated data and the eventual staffing-balance
    report agree on what "capacity" means."""
    rate_index = {(r.person_id, r.month): r.annual_salary for r in rates}
    wrap_index = {wr.month: wr for wr in wrap_rates}
    totals: dict[Month, float] = defaultdict(float)
    for c in capacity:
        wr = wrap_index[c.month]
        base_hourly = rate_index[(c.person_id, c.month)] / 12 / wr.workable_hours
        totals[c.month] += c.available_hours * base_hourly * wr.project_wrap_rate
    return dict(totals)


def _draw_rate_structure(rng: random.Random) -> str:
    """Drawn per project, so one unlucky draw can't dominate the project count the
    way it would if it applied to a whole lane's worth of back-to-back projects.

    OH/fee-charged projects are a token minority, not the ~15% used earlier: their
    wrap rates (~1.65x, ~1.1x) are well below the direct rate (~2.9x) that the
    staffing-balance report's capacity figure is valued at, so any meaningful OH/fee
    share puts a structural ceiling on demand well below capacity even at 100%
    crew utilization — a gap no amount of monthly calibration below can close.
    Keeping OH/fee to a sliver keeps that gap negligible while still showing that
    the funding types exist."""
    roll = rng.random()
    if roll < 0.003:
        return "oh_charged"
    if roll < 0.005:
        return "fee_charged"
    return "direct"


def generate_project_chains(rng: random.Random) -> list[Project]:
    """A fixed number of concurrent "lanes" maintains ~10-12 simultaneously active
    projects throughout the horizon: each lane just keeps generating one independent
    project after another, back to back, until the horizon is filled. No tracking of
    which projects are "really" a continuation of which — each is independent, with
    its own rate structure and its own crew (`assign_crews`).

    Project names are plain sequential integers assigned in chronological PoP-start
    order (project_1, project_2, project_3, ...).
    """
    num_lanes = rng.randint(*NUM_PROJECT_SLOTS_RANGE)
    raw: list[dict] = []

    for _ in range(num_lanes):
        cursor = HORIZON_START
        while cursor <= HORIZON_END:
            pop_len = rng.randint(*POP_LENGTH_RANGE_MONTHS)
            pop_end = min(HORIZON_END, cursor.add(pop_len - 1))
            raw.append(
                {"pop_start": cursor, "pop_end": pop_end, "rate_structure": _draw_rate_structure(rng)}
            )
            cursor = pop_end.add(1)

    raw.sort(key=lambda r: r["pop_start"])

    projects: list[Project] = []
    for i, r in enumerate(raw):
        projects.append(
            Project(
                project_id=f"project_{i + 1}",
                name=f"Project {i + 1}",
                pop_start=r["pop_start"],
                pop_end=r["pop_end"],
                rate_structure=r["rate_structure"],
                travel_budget=round(rng.uniform(5_000, 50_000), 2),
                odc_budget=round(rng.uniform(2_000, 30_000), 2),
                status=ProjectStatus.ACTIVE,
            )
        )
    return projects


def assign_crews(
    rng: random.Random, projects: list[Project], people: list[Person]
) -> dict[str, list[tuple[str, str]]]:
    """Each project gets its own independently drawn crew.

    Fragmentation limits are respected against *temporal overlap*, not lifetime
    totals: a person who's free again once an earlier, non-overlapping project ended
    is eligible again, the same way real availability works. (A running total that's
    never decremented would eventually exhaust everyone eligible, once there are more
    independent projects than a per-person lifetime cap of 4 could ever cover.)

    Returns {project_id: [(person_id, role), ...]} where role is "primary" or "secondary".
    """
    person_ids = [p.person_id for p in people]
    committed: dict[str, list[Project]] = {pid: [] for pid in person_ids}
    assignments: dict[str, list[tuple[str, str]]] = {}

    def overlaps(a: Project, b: Project) -> bool:
        return a.pop_start <= b.pop_end and b.pop_start <= a.pop_end

    for project in sorted(projects, key=lambda p: p.pop_start):
        crew_size = rng.randint(5, 10)

        def load(pid: str) -> int:
            return sum(1 for other in committed[pid] if overlaps(other, project))

        eligible_candidates = [pid for pid in person_ids if load(pid) < 4]
        candidates = sorted(eligible_candidates, key=lambda pid: (load(pid), rng.random()))
        crew = candidates[:crew_size]
        for pid in crew:
            committed[pid].append(project)

        roles = ["primary"] * max(1, len(crew) // 2) + ["secondary"] * (len(crew) - max(1, len(crew) // 2))
        rng.shuffle(roles)
        assignments[project.project_id] = list(zip(crew, roles))

    return assignments


def generate_bounds_and_targets(
    rng: random.Random,
    people: list[Person],
    projects: list[Project],
    crews: dict[str, list[tuple[str, str]]],
    capacity_index: dict[tuple[str, Month], float],
    capacity_dollars_by_month: dict[Month, float],
    rate_fn,
) -> tuple[list[Bounds], list[Target]]:
    """Two passes: first generate each crew member's "raw" target hours from their
    role/intensity as before; then, per month, uniformly rescale every cell's raw
    hours so the portfolio's total target dollars land within a small, deliberately
    narrow band of that month's total labor spend capacity (`compute_capacity_dollars_
    by_month`) — the business philosophy is a near-full, only-slightly-short (rarely
    slightly over) draw on the pool each month, not the wide swings independent
    per-project/per-person draws would otherwise produce (`staffing_balance.py`).

    Ramp-up (first PoP month at ~40% crew) is skipped for any project whose
    `pop_start` is the horizon's own first month: with every one of the ~10-12
    lanes starting simultaneously right at `HORIZON_START`, ramping all of them at
    once would manufacture an artificial portfolio-wide dip in month one that no
    other month has — those lanes are treated as already-established, mid-steady-
    state work that merely happens to be visible from the start of this window.
    """
    horizon = set(Month.range(HORIZON_START, HORIZON_END))

    # Pass 1: each crewed person's own (project, role) cells this month, with a raw
    # role-intensity draw kept only as a *relative weight* between a person's own
    # concurrent cells — not an absolute hours anchor. An absolute anchor is what
    # the old, uniform-monthly-scale approach used, and it strands capacity no scale
    # factor can recover: a person crewed onto just one secondary-role project that
    # month has no *other* bound to soak up the rest of their hours, so scaling
    # their one small cell up or down never reaches the capacity that has nowhere
    # to go. Filling per-person instead (pass 2) reaches it directly.
    cells_by_month: dict[Month, list[dict]] = defaultdict(list)
    pop_months_by_project: dict[str, list[Month]] = {}
    for project in projects:
        crew = crews[project.project_id]
        pop_months = [m for m in project.months() if m in horizon]
        pop_months_by_project[project.project_id] = pop_months
        if not pop_months:
            continue
        ramp_crew_size = max(1, round(len(crew) * 0.4))
        ramp_crew = set(pid for pid, _ in crew[:ramp_crew_size])
        skip_ramp = project.pop_start == HORIZON_START

        for month_idx, month in enumerate(pop_months):
            use_full_crew = skip_ramp or month_idx > 0
            active_crew = crew if use_full_crew else [(pid, role) for pid, role in crew if pid in ramp_crew]

            for person_id, role in active_crew:
                cap = capacity_index.get((person_id, month), 0.0)
                if cap <= 0:
                    continue
                weight = rng.uniform(0.72, 1.0) if role == "primary" else rng.uniform(0.32, 0.52)
                cells_by_month[month].append(
                    {
                        "project_id": project.project_id,
                        "person_id": person_id,
                        "weight": weight,
                        "rate": rate_fn(project.project_id, person_id, month),
                        "cap": cap,
                    }
                )

    # Pass 1b: crew rotation occasionally leaves a handful of people with no active
    # assignment at all in a given month (one project ended, the next one they'd
    # rotate onto hasn't picked them up yet). That's real capacity with no bound to
    # reach it — pass 2's per-person fill can't recover it no matter the fraction,
    # since fraction only redistributes among people who already have a cell. Backfill
    # each such person onto one of that month's already-active projects (a plausible
    # "pulled in wherever needed" assignment) so their capacity is reachable too.
    all_person_ids = [p.person_id for p in people]
    for month in list(cells_by_month.keys()):
        cells = cells_by_month[month]
        covered = {c["person_id"] for c in cells}
        active_project_ids = list({c["project_id"] for c in cells})
        if not active_project_ids:
            continue
        for person_id in all_person_ids:
            if person_id in covered:
                continue
            cap = capacity_index.get((person_id, month), 0.0)
            if cap <= 0:
                continue
            project_id = rng.choice(active_project_ids)
            cells_by_month[month].append(
                {
                    "project_id": project_id,
                    "person_id": person_id,
                    "weight": rng.uniform(0.32, 0.52),
                    "rate": rate_fn(project_id, person_id, month),
                    "cap": cap,
                }
            )

    # Pass 2: per month, fill every crewed person up to a calibrated fraction of
    # *their own* capacity (never more), splitting that total across their own
    # concurrent cells by relative weight (primary gets the larger share). The
    # fraction is solved directly from the month's total labor spend capacity minus
    # a small, deliberately narrow (and usually-shortfall) target imbalance —
    # linear in the fraction, since each person's own weighted-average rate doesn't
    # depend on it — clipped at 1.0 (100% personal utilization is the real ceiling;
    # if even that isn't enough to reach the target, the shortfall is genuine: this
    # month's crewed subset of the pool doesn't have enough capacity, not a
    # calibration miss).
    bounds: list[Bounds] = []
    target_dollars_by_project_month: dict[tuple[str, Month], float] = defaultdict(float)
    for project in projects:
        for month in pop_months_by_project[project.project_id]:
            target_dollars_by_project_month[(project.project_id, month)] += 0.0  # ensure every PoP month appears

    for month, cells in cells_by_month.items():
        by_person: dict[str, list[dict]] = defaultdict(list)
        for c in cells:
            by_person[c["person_id"]].append(c)

        person_cap: dict[str, float] = {}
        person_avg_rate: dict[str, float] = {}
        for person_id, person_cells in by_person.items():
            total_weight = sum(c["weight"] for c in person_cells)
            person_cap[person_id] = person_cells[0]["cap"]
            person_avg_rate[person_id] = sum(c["weight"] * c["rate"] for c in person_cells) / total_weight

        # capacity_of_crewed: total dollar capacity of just the people actually
        # crewed this month, valued at each person's own weighted-average
        # applicable rate — what `fraction` is solved against.
        #
        # Deliberately *not* clipped to <= 1.0: `fraction` sets each person's
        # *target* hours, and targets represent what the projects need, not a
        # promise about what the pool can actually deliver (`staffing_balance.py`).
        # A fraction above 1.0 asks a crewed person's cells for more than their own
        # 100% capacity — the solver's real per-person capacity constraint (C3)
        # still caps what actually gets assigned, so this never manufactures an
        # infeasibility; it just leaves that month's targets genuinely unmet,
        # which is the real signal this demo is usually a labor deficit, not
        # (falsely) an always-achievable one.
        capacity_of_crewed = sum(person_cap[pid] * person_avg_rate[pid] for pid in by_person)
        capacity_dollars = capacity_dollars_by_month.get(month, 0.0)
        # A mixture, not a single always-slightly-negative draw: reforecast pushes
        # any month's underspend forward as a target *increase* for that project's
        # remaining months (proportional redistribution, `reforecast/redistribute.py`)
        # with no damping. If targets ran short of capacity almost every month, every
        # project would underspend almost every month, and reforecast would compound
        # that into an ever-growing target across the whole 5-year horizon — a real
        # spiral this demo hit once. Genuine catch-up months (target comfortably
        # *below* capacity) let a project's actual meet or clear its target, which
        # reforecast then redistributes as a target *decrease* — the reset that
        # keeps "usually a slight deficit" from silently becoming "always growing".
        if rng.random() < 0.82:
            target_balance = rng.uniform(-5000.0, -500.0)  # usual: deficit
        else:
            target_balance = rng.uniform(500.0, 3000.0)  # occasional: catch-up
        desired_demand = capacity_dollars - target_balance
        fraction = desired_demand / capacity_of_crewed if capacity_of_crewed > 0 else 0.0

        for person_id, person_cells in by_person.items():
            total_weight = sum(c["weight"] for c in person_cells)
            person_total_hours = fraction * person_cap[person_id]
            for c in person_cells:
                target_hours = person_total_hours * (c["weight"] / total_weight)
                soft_min = round(0.92 * target_hours, 2)
                soft_max = round(target_hours, 2)
                hard_max = round(1.15 * target_hours, 2)
                bounds.append(
                    Bounds(
                        project_id=c["project_id"],
                        person_id=person_id,
                        month=month,
                        hard_min=0.0,
                        soft_min=soft_min,
                        soft_max=soft_max,
                        hard_max=hard_max,
                        eligible=True,
                    )
                )
                target_dollars_by_project_month[(c["project_id"], month)] += soft_max * c["rate"]

    targets = [
        Target(
            project_id=project_id,
            month=month,
            labor_spend_target=round(target_dollars, 2),
            target_tolerance=round(0.01 * target_dollars, 2),
            target_type=TargetType.SOFT,
        )
        for (project_id, month), target_dollars in target_dollars_by_project_month.items()
    ]

    return bounds, targets


def generate_closed_month_actuals(
    rng: random.Random, plan_bounds: list[Bounds], capacity_index: dict[tuple[str, Month], float]
) -> list[AllocationRow]:
    """For months <= CLOSED_THROUGH: a synthetic prior plan plus actuals that vary from it.

    Closed months fix `x` to `hours_actual`, not `hours_assigned` (`04-solver-design.md`,
    C5 plus the "closed month" rule) — so it's the *actual* hours whose sum across a
    person's simultaneous projects that month must not exceed their capacity. Capping
    each project's actual draw independently at the person's full capacity isn't enough:
    two projects each near-capacity on their own can still sum past it. Both the planned
    and the actual draws are scaled down proportionally per (person, month) when their
    sum would oversubscribe it.
    """
    from collections import defaultdict

    by_person_month: dict[tuple[str, Month], list[Bounds]] = defaultdict(list)
    for b in plan_bounds:
        if b.month <= CLOSED_THROUGH:
            by_person_month[(b.person_id, b.month)].append(b)

    rows = []
    for (person_id, month), bounds_list in by_person_month.items():
        cap = capacity_index.get((person_id, month), 0.0)

        naive_planned = {b.project_id: rng.uniform(0.96, 1.0) * b.soft_max for b in bounds_list}
        total_planned = sum(naive_planned.values())
        scale_planned = min(1.0, cap / total_planned) if total_planned > 0 else 1.0
        planned_by_project = {pid: v * scale_planned for pid, v in naive_planned.items()}

        # Same tight, slightly-overspend-leaning noise as the live simulation
        # (`io/synthetic.py`'s NORMAL_NOISE) — no reason this bootstrap history
        # should be biased differently than the months the simulation itself creates.
        naive_actual = {pid: v * rng.uniform(0.98, 1.03) for pid, v in planned_by_project.items()}
        total_actual = sum(naive_actual.values())
        scale_actual = min(1.0, cap / total_actual) if total_actual > 0 else 1.0

        actual_by_project = {pid: round(v * scale_actual, 2) for pid, v in naive_actual.items()}
        # Rounding each project's actual independently, after the scale-down above
        # already lands the (unrounded) sum at exactly `cap`, can push the *rounded*
        # sum a few hundredths of an hour back over it — and this month's `hours_actual`
        # is what C3's exact capacity constraint fixes cells to once closed, so even
        # that tiny an overage makes the very first solve infeasible. Trim any such
        # excess from the largest cell, the only one big enough to absorb it cleanly.
        excess = round(sum(actual_by_project.values()) - cap, 2)
        if excess > 0:
            largest_project_id = max(actual_by_project, key=actual_by_project.get)
            actual_by_project[largest_project_id] = round(actual_by_project[largest_project_id] - excess, 2)

        for b in bounds_list:
            planned = round(planned_by_project[b.project_id], 2)
            actual = actual_by_project[b.project_id]
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
    capacity_dollars_by_month = compute_capacity_dollars_by_month(capacity, rates, wrap_rates)

    bounds, targets = generate_bounds_and_targets(
        rng, people, projects, crews, capacity_index, capacity_dollars_by_month, rate_fn
    )
    allocation = generate_closed_month_actuals(rng, bounds, capacity_index)

    # labor_budget is the fixed funded ceiling the monthly targets are planned (and
    # later reforecast) against — set once, from the sum of this project's own
    # just-generated targets, then never recomputed.
    labor_budget_by_project: dict[str, float] = {}
    for t in targets:
        labor_budget_by_project[t.project_id] = labor_budget_by_project.get(t.project_id, 0.0) + t.labor_spend_target
    projects = [
        p.model_copy(update={"labor_budget": round(labor_budget_by_project.get(p.project_id, 0.0), 2)})
        for p in projects
    ]

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
    from allocsolver.reports.staffing_balance import staffing_balance

    save_plan(plan, args.out)
    clear_pre_assignments(args.out)  # starts empty: the planner's inbox for manual pre-assignments
    print(f"Generated {len(people)} people, {len(projects)} projects, {len(bounds)} bounds rows.")
    print(f"Wrote data files to {args.out}")

    balances = staffing_balance(plan)  # demand from plan.targets; no solve needed for this estimate
    total_capacity = sum(b.capacity_dollars for b in balances)
    total_demand = sum(b.demand_dollars for b in balances)
    shortfall_months = sum(1 for b in balances if b.balance_dollars < -1e-6)
    max_abs_balance = max((abs(b.balance_dollars) for b in balances), default=0.0)
    print(
        f"Staffing balance (pre-solve estimate): ${total_capacity:,.0f} spend capacity vs "
        f"${total_demand:,.0f} intended spend demand over the horizon "
        f"(${total_capacity - total_demand:+,.0f} net, {shortfall_months} month(s) with a shortfall, "
        f"max |monthly balance| ${max_abs_balance:,.0f})."
    )


if __name__ == "__main__":
    main()
