#!/usr/bin/env python
"""Runs the small example end to end: load -> solve -> views -> exports -> reforecast demo.

    python run_example.py

Assumes `data/` already exists (run `generate_data.py` first if not). Writes rendered
views to the console and full CSV exports to ./output/.
"""

from pathlib import Path

from rich.console import Console

from allocsolver.costing.masks import eligible_cells
from allocsolver.io.local import load_plan
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.reports.exports import export_budget_summary, export_variance_sheet, export_workforce_sheet
from allocsolver.reports.render import render_resource_view, render_task_view
from allocsolver.reports.staffing_balance import export_staffing_balance
from allocsolver.reports.views import build_rows
from allocsolver.solve.run import solve

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"
SAMPLE_PROJECTS = ["project_alpha", "project_beta", "project_gamma"]
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
    console.print("Solving the full horizon (OR-Tools / SCIP)...")
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

    console.rule("[bold]3. Task view and resource view[/bold]")
    rows = build_rows(plan, result.hours_assigned)
    render_task_view(plan, rows, console)
    resource_rows = [r for r in rows if r.person_id in SAMPLE_PEOPLE]
    render_resource_view(plan, resource_rows, result.hours_assigned, console)

    console.rule("[bold]4. Onboarding, visible in the data[/bold]")
    gamma = plan.project("project_gamma")
    m0 = gamma.pop_start
    crew_m0 = {w for (p, w, m), h in result.hours_assigned.items() if p == "project_gamma" and m == m0 and h > 0}
    console.print(f"project_gamma's crew in its first PoP month ({m0}): {len(crew_m0)} people — its whole crew.")
    console.print("(No ramp-up in this small scenario — every project starts at full crew from day one.)")

    console.rule("[bold]5. Reforecast demo, using the closed month's actuals[/bold]")
    closed_month = plan.closed_through
    for project_id in SAMPLE_PROJECTS:
        try:
            proposal = propose_reforecast(plan, project_id, closed_month)
        except ValueError:
            continue
        console.print(
            f"{project_id}: variance for {closed_month} = {proposal.variance:+,.0f} "
            f"(target - actual). Proposed target changes for the remaining open months:"
        )
        for m, new_target in proposal.updated_targets.items():
            console.print(f"    {m}: -> {new_target:,.0f}")

    console.rule("[bold]6. Exports[/bold]")
    OUTPUT_DIR.mkdir(exist_ok=True)
    first_open_month = closed_month.add(1)
    export_workforce_sheet(
        plan, result.hours_assigned, first_open_month, OUTPUT_DIR / f"assignments_{first_open_month}.csv"
    )
    export_variance_sheet(plan, result.hours_assigned, OUTPUT_DIR / "variance.csv")
    for project_id in SAMPLE_PROJECTS:
        export_budget_summary(
            plan, result.hours_assigned, project_id, OUTPUT_DIR / f"budget_{project_id}.csv", as_of_month=first_open_month
        )
    export_staffing_balance(plan, OUTPUT_DIR / "staffing_balance.csv")
    console.print(f"Wrote workforce, variance, budget-summary, and staffing-balance exports to {OUTPUT_DIR}/")
    console.print("See README.md for what a planner does with each of these in practice.")


if __name__ == "__main__":
    main()
