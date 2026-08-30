"""The three confirmed exports — `05-interfaces.md`, "Exports".

Workforce, planners, and analysts see fundamentally different things (`01-system-overview.md`).
The workforce sheet is a hard column allowlist: cost, rate, and salary never appear in it.
"""

import csv
from pathlib import Path

from allocsolver.costing.masks import Cell
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def export_workforce_sheet(
    plan: Plan, hours_assigned: dict[Cell, float], month: Month, out_path: Path
) -> None:
    """Sent to the workforce by the 1st of each month. Hours only — no cost, rate, or salary."""
    rows = [
        (plan.person(w).name, plan.project(p).name, round(hours, 2))
        for (p, w, m), hours in hours_assigned.items()
        if m == month and hours > 1e-9
    ]
    rows.sort()
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["worker_name", "project_name", "hours_assigned"])
        writer.writerows(rows)


def export_variance_sheet(
    plan: Plan, hours_assigned: dict[Cell, float], out_path: Path, month: Month | None = None
) -> None:
    """For planners. One row per (worker, project, month) with actuals recorded.

    Pass `month` to restrict to just that month's rows (e.g. for a per-month output
    folder) — omit it for the whole plan's variance to date.
    """
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}
    rows = []
    for cell, hours in hours_assigned.items():
        p, w, m = cell
        if month is not None and m != month:
            continue
        alloc = alloc_index.get(cell)
        actual = alloc.hours_actual if alloc else None
        if actual is None:
            continue
        rows.append(
            (
                plan.person(w).name,
                plan.project(p).name,
                str(m),
                round(hours, 2),
                round(actual, 2),
                round(hours - actual, 2),
            )
        )
    rows.sort()
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["worker_name", "project_name", "month", "hours_assigned", "actual_hours", "delta"])
        writer.writerows(rows)


def export_variance_sheet_for_closed_month(plan: Plan, month: Month, out_path: Path) -> None:
    """The variance report for one already-closed month, read directly from
    `plan.allocation`'s own recorded `hours_assigned`/`hours_actual` for it.

    Deliberately *not* driven by a live solve's `hours_assigned` dict: once a month
    is closed, the solver fixes its cells to match `hours_actual` exactly (`04-solver-
    design.md`), so a later solve's own `hours_assigned` for that month is just the
    actual value echoed back — comparing it against itself would always show a zero
    delta. The *originally planned* value for a closed month lives only in the
    allocation row saved when that month was itself closed, which is what this reads.
    """
    rows = []
    for a in plan.allocation:
        if a.month != month or a.hours_actual is None:
            continue
        rows.append(
            (
                plan.person(a.person_id).name,
                plan.project(a.project_id).name,
                str(a.month),
                round(a.hours_assigned, 2),
                round(a.hours_actual, 2),
                round(a.hours_assigned - a.hours_actual, 2),
            )
        )
    rows.sort()
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["worker_name", "project_name", "month", "hours_assigned", "actual_hours", "delta"])
        writer.writerows(rows)


def export_budget_summary(
    plan: Plan,
    hours_assigned: dict[Cell, float],
    project_id: str,
    out_path: Path,
    as_of_month: Month | None = None,
) -> None:
    """For planners, one per project: metadata block plus a monthly matrix.

    "Planned" for an already-closed month is read from *that month's own* recorded
    `hours_assigned` in `plan.allocation` — what was actually committed before it
    closed — not from the live solve's `hours_assigned`. A closed cell is fixed to
    `hours_actual` (C5), so the live solve's value for it just echoes the actual
    back; using it here would make every historical month show planned == actual
    identically, with only the just-solved current month escaping that. Only a
    month with no closed record yet (still open) falls back to the live dict.

    `as_of_month`, if given, is "this report is as of the start of `as_of_month`":
    the *actual*-side figures (`actual_spend`, `delta`, `cumulative_actual_spend`,
    `actual_funds_remaining`) are blank for `as_of_month` itself and anything after
    it — a month's own actuals aren't known until the month after it closes (same
    timing as `export_variance_sheet_for_closed_month`), so showing them, or a
    running total that includes them, as of that month's own report would be
    reporting something not yet knowable. The *planned*-side figures — `planned_spend`,
    `cumulative_planned_spend`, and `planned_funds_remaining` — stay populated for
    the whole PoP regardless: they're forward budget figures, not something that
    needs elapsed time to be meaningful, the same way any ordinary budget-vs-actual
    report shows the full year's budget alongside actual-to-date. Omit `as_of_month`
    (the default) for a plain full-horizon snapshot with nothing blanked.
    """
    project = plan.project(project_id)
    months = [m for m in project.months() if m in set(plan.horizon())]
    alloc_index = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}

    planned_by_month: dict[Month, float] = {}
    actual_by_month: dict[Month, float] = {}
    for m in months:
        planned = 0.0
        actual = 0.0
        closed_people_this_month: set[str] = set()

        for (p, w, m2), alloc in alloc_index.items():
            if p == project_id and m2 == m and alloc.hours_actual is not None:
                planned += alloc.hours_assigned * loaded_rate(plan, w, m, p)
                actual += alloc.hours_actual * loaded_rate(plan, w, m, p)
                closed_people_this_month.add(w)

        for (p, w, m2), hours in hours_assigned.items():
            if p == project_id and m2 == m and w not in closed_people_this_month:
                planned += hours * loaded_rate(plan, w, m2, p)

        planned_by_month[m] = planned
        actual_by_month[m] = actual

    # The fixed funded ceiling, not the (reforecast-adjustable) sum of monthly targets —
    # reforecasting conserves this total by construction, but it's the project's own
    # `labor_budget` that's the actual reference figure, not a derived proxy for it.
    total_budget = project.labor_budget
    planned_to_date = sum(planned_by_month.values())
    actual_to_date = sum(actual_by_month.values())

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["project_name", project.name])
        writer.writerow(["pop_start", str(project.pop_start)])
        writer.writerow(["pop_end", str(project.pop_end)])
        writer.writerow(["labor_budget", round(total_budget, 2)])
        writer.writerow(["budget_expended_planned", round(planned_to_date, 2)])
        writer.writerow(["budget_expended_actual", round(actual_to_date, 2)])
        writer.writerow(["budget_remaining_planned", round(total_budget - planned_to_date, 2)])
        writer.writerow(["budget_remaining_actual", round(total_budget - actual_to_date, 2)])
        cumulative_planned_by_month: dict[Month, float] = {}
        cumulative_actual_by_month: dict[Month, float] = {}
        running_planned = 0.0
        running_actual = 0.0
        for m in months:
            running_planned += planned_by_month[m]
            running_actual += actual_by_month[m]
            cumulative_planned_by_month[m] = running_planned
            cumulative_actual_by_month[m] = running_actual

        def known(m: Month) -> bool:
            return as_of_month is None or m < as_of_month

        def cell(value: float, m: Month) -> str:
            return f"{value:.2f}" if known(m) else ""

        writer.writerow([])
        writer.writerow(["month", *[str(m) for m in months]])
        writer.writerow(["planned_spend", *[round(planned_by_month[m], 2) for m in months]])
        writer.writerow(["actual_spend", *[cell(actual_by_month[m], m) for m in months]])
        writer.writerow(["delta", *[cell(planned_by_month[m] - actual_by_month[m], m) for m in months]])
        # Planned-side cumulative/remaining stay populated for the whole PoP, same as
        # planned_spend itself — they're forward budget figures, not something that
        # needs elapsed time to be meaningful. Only the actual-side ones are blanked.
        writer.writerow(
            ["cumulative_planned_spend", *[round(cumulative_planned_by_month[m], 2) for m in months]]
        )
        writer.writerow(["cumulative_actual_spend", *[cell(cumulative_actual_by_month[m], m) for m in months]])
        writer.writerow(
            [
                "planned_funds_remaining",
                *[round(total_budget - cumulative_planned_by_month[m], 2) for m in months],
            ]
        )
        writer.writerow(
            ["actual_funds_remaining", *[cell(total_budget - cumulative_actual_by_month[m], m) for m in months]]
        )


def export_month_snapshot(
    plan: Plan, hours_assigned: dict[Cell, float], month: Month, out_dir: Path
) -> None:
    """Everything to review after solving/closing one month, bundled into `out_dir`.

    Two different timings are deliberately in play here, matching how this actually
    works (`01-system-overview.md`, "Primary workflow"):

    - **Work assignments are sent before the month they're for starts.** So
      `<month>_work_assignments.csv` — prefixed with this folder's own month — holds
      the just-solved plan for `month` itself.
    - **A month's variance can only be known the month *after* it closes** — actuals
      land in the first week of the following month. So the variance file in this
      folder is for `month`'s *predecessor*, prefixed with that earlier month, not
      this folder's own. It's read straight from `plan.allocation`, which already
      has that predecessor month's actuals recorded from the *previous* cycle.

    Used by `advance-month` and `simulate_full_horizon.py` to produce one dated
    folder per simulated month.

    `<month>_budget_<project_id>.csv` — prefixed with this folder's own month, same
    as the work-assignment file — reports `month` "as of" itself: the actual-side
    figures (and their cumulative/remaining) are blank for `month` and anything
    after it, since a month's own actuals aren't knowable until the month after; the
    planned side stays populated throughout (see `export_budget_summary`).

    A project's *final* budget summary is additionally written to
    `completed_project_reports/` — a persistent folder, sibling to the dated month
    folders, not itself month-named — as `<pop_end date>_final_budget_<project_id>.csv`
    (the PoP end's actual calendar date, e.g. `2027-11-30`, not just its month, so
    these sort chronologically). This happens one cycle *after* the project's own
    PoP end, not during it — a project's own last month is necessarily still blank
    on the actual side in its own `pop_end` folder (that month's actuals aren't
    known until the month after), so the genuinely final report — every month
    populated, nothing blank — is only possible from the cycle after.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    export_workforce_sheet(plan, hours_assigned, month, out_dir / f"{month}_work_assignments.csv")

    previous_month = month.add(-1)
    if previous_month >= plan.horizon_start:
        export_variance_sheet_for_closed_month(plan, previous_month, out_dir / f"{previous_month}_variance.csv")

    for project in plan.projects:
        if project.pop_start <= month <= project.pop_end:
            filename = f"{month}_budget_{project.project_id}.csv"
            export_budget_summary(plan, hours_assigned, project.project_id, out_dir / filename, as_of_month=month)

        if project.pop_end.add(1) == month:
            # This is the *first* cycle where the project's own last month's actuals
            # are actually known (one cycle after pop_end, same lag as everything
            # else here) — a fresh export, "as of" this month, not a copy of the
            # pop_end month's own file, which necessarily still had its last month
            # blank at the time it was written.
            completed_dir = out_dir.parent / "completed_project_reports"
            completed_dir.mkdir(parents=True, exist_ok=True)
            final_filename = f"{project.pop_end.last_day()}_final_budget_{project.project_id}.csv"
            export_budget_summary(
                plan, hours_assigned, project.project_id, completed_dir / final_filename, as_of_month=month
            )
