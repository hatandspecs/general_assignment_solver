#!/usr/bin/env python
"""Runs the medium example end to end: load -> solve -> views -> exports -> reforecast demo.

    python run_example.py

Assumes `data/` already exists (run `generate_data.py` first if not). Writes rendered
views to the console (a sample, not all 59 projects) and full CSV exports to ./output/.
"""

from pathlib import Path

from rich.console import Console

from allocsolver.costing.masks import eligible_cells
from allocsolver.io.local import load_plan
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.reports.exports import export_budget_summary, export_variance_sheet, export_workforce_sheet
from allocsolver.reports.render import render_resource_view, render_task_view
from allocsolver.reports.views import build_rows
from allocsolver.solve.run import solve

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"
SAMPLE_PROJECTS = ["project_1", "project_2", "project_3"]
SAMPLE_PEOPLE = ["person_1", "person_2"]


def main() -> None:
    console = Console(width=140)

    console.rule("[bold]1. Load[/bold]")
    plan = load_plan(DATA_DIR)
    console.print(
        f"{len(plan.people)} people, {len(plan.projects)} projects, "
        f"horizon {plan.horizon_start} to {plan.horizon_end} "
        f"({len(plan.horizon())} months), closed through {plan.closed_through}."
    )
    console.print(f"{len(eligible_cells(plan))} eligible (project, person, month) cells.")

    console.rule("[bold]2. Solve[/bold]")
    console.print("Solving the full 5-year horizon (OR-Tools / SCIP)...")
    result = solve(plan)

    if not result.feasible:
        console.print("[red]INFEASIBLE[/red]")
        console.print(result.diagnostics.render() if result.diagnostics else "no diagnostics")
        return

    console.print(
        f"[green]Solved[/green] in {result.wall_time_seconds:.1f}s "
        f"(solve_id={result.solve_id}). Objective breakdown:"
    )
    console.print(result.objective)

    console.rule("[bold]3. Task view and resource view (sample)[/bold]")
    console.print(
        f"Full task/resource views cover all {len(plan.projects)} projects and "
        f"{len(plan.people)} people; showing the first 3 months of a few of each here. "
        "The CSV exports in step 6 carry everything."
    )
    rows = build_rows(plan, result.hours_assigned)
    sample_months = {plan.horizon_start.add(i) for i in range(3)}
    sample_rows = [r for r in rows if r.project_id in SAMPLE_PROJECTS and r.month in sample_months]
    render_task_view(plan, sample_rows, console)
    resource_rows = [r for r in rows if r.person_id in SAMPLE_PEOPLE and r.month in sample_months]
    render_resource_view(plan, resource_rows, result.hours_assigned, console)

    console.rule("[bold]4. Ramp-up, visible in the data[/bold]")
    first_project = plan.project("project_1")
    m0, m1 = first_project.pop_start, first_project.pop_start.add(1)
    crew_m0 = {w for (p, w, m), h in result.hours_assigned.items() if p == "project_1" and m == m0 and h > 0}
    crew_m1 = {w for (p, w, m), h in result.hours_assigned.items() if p == "project_1" and m == m1 and h > 0}
    console.print(f"project_1's crew in its first PoP month ({m0}): {len(crew_m0)} people.")
    console.print(f"project_1's crew the following month ({m1}): {len(crew_m1)} people.")
    console.print("Smaller first month is the pre-assigned ramp-up pattern from `01-system-overview.md`.")

    console.rule("[bold]5. Reforecast demo, using the closed months' actuals[/bold]")
    closed_month = plan.closed_through
    for project_id in SAMPLE_PROJECTS:
        try:
            proposal = propose_reforecast(plan, project_id, closed_month)
        except ValueError:
            continue
        console.print(
            f"{project_id}: variance for {closed_month} = {proposal.variance:+,.0f} "
            f"(target - actual). Proposed target changes for the remaining open months "
            f"(first 3 shown):"
        )
        for m, new_target in list(proposal.updated_targets.items())[:3]:
            console.print(f"    {m}: -> {new_target:,.0f}")

    console.rule("[bold]6. Exports[/bold]")
    OUTPUT_DIR.mkdir(exist_ok=True)
    first_open_month = closed_month.add(1)
    export_workforce_sheet(
        plan, result.hours_assigned, first_open_month, OUTPUT_DIR / f"assignments_{first_open_month}.csv"
    )
    export_variance_sheet(plan, result.hours_assigned, OUTPUT_DIR / "variance.csv")
    for project_id in SAMPLE_PROJECTS:
        export_budget_summary(plan, result.hours_assigned, project_id, OUTPUT_DIR / f"budget_{project_id}.csv")
    console.print(f"Wrote workforce, variance, and budget-summary exports to {OUTPUT_DIR}/")
    console.print("See README.md for what a planner does with each of these in practice.")


if __name__ == "__main__":
    main()
