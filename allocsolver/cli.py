"""Typer entry points — `05-interfaces.md`, "CLI".

Scoped to what this build actually implements: `solve`, `validate`, `export`, and
`advance-month` (the simulated real-time engine) against a local JSON data directory
(see `io/local.py`). Grist REST integration, a real timekeeping ingest pipeline, and
snapshot/diff are documented in `05-interfaces.md` but not yet wired up here.
"""

import random
from pathlib import Path

import typer
from rich.console import Console

from allocsolver.config import DEFAULT_MIP_GAP, DEFAULT_TIME_LIMIT_SECONDS, Weights
from allocsolver.io.local import load_plan, save_plan
from allocsolver.io.pre_assignments import apply_pre_assignments, clear_pre_assignments, load_pre_assignments
from allocsolver.io.synthetic import simulate_actuals_for_month
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.reports.exports import (
    export_budget_summary,
    export_month_snapshot,
    export_variance_sheet,
    export_workforce_sheet,
)
from allocsolver.reports.render import render_resource_view, render_task_view
from allocsolver.reports.staffing_balance import export_staffing_balance
from allocsolver.reports.views import build_rows
from allocsolver.solve.run import solve

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def validate(data_dir: Path = typer.Option(..., exists=True)) -> None:
    """Checks only, no solve — `05-interfaces.md`."""
    load_plan(data_dir)
    console.print("[green]Plan is valid.[/green]")


@app.command(name="solve")
def solve_cmd(
    data_dir: Path = typer.Option(..., exists=True),
    time_limit: int = DEFAULT_TIME_LIMIT_SECONDS,
    mip_gap: float = DEFAULT_MIP_GAP,
    export_dir: Path | None = None,
) -> None:
    """Solve the plan and render the task/resource views."""
    plan = load_plan(data_dir)
    result = solve(plan, weights=Weights(), time_limit_seconds=time_limit, mip_gap=mip_gap)

    if not result.feasible:
        console.print("[red]INFEASIBLE[/red]")
        console.print(result.diagnostics.render() if result.diagnostics else "no diagnostics")
        raise typer.Exit(code=1)

    console.print(f"[green]Solved[/green] in {result.wall_time_seconds:.1f}s — solve_id={result.solve_id}")
    console.print(result.objective)

    rows = build_rows(plan, result.hours_assigned)
    render_task_view(plan, rows, console)
    render_resource_view(plan, rows, result.hours_assigned, console)

    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
        first_month = plan.horizon_start
        # "As of" the first open month: whatever's already closed shows real
        # actuals, everything from there on is blank on the actual/cumulative side
        # (see export_budget_summary) rather than presenting a speculative future
        # as if it were already known.
        as_of_month = plan.closed_through.add(1) if plan.closed_through else None
        export_workforce_sheet(plan, result.hours_assigned, first_month, export_dir / f"assignments_{first_month}.csv")
        export_variance_sheet(plan, result.hours_assigned, export_dir / "variance.csv")
        for project in plan.projects:
            export_budget_summary(
                plan,
                result.hours_assigned,
                project.project_id,
                export_dir / f"budget_{project.project_id}.csv",
                as_of_month=as_of_month,
            )
        console.print(f"Exports written to {export_dir}")


@app.command(name="advance-month")
def advance_month(
    data_dir: Path = typer.Option(..., exists=True),
    output_dir: Path = typer.Option(Path("output"), help="One dated subfolder is written per month advanced."),
    time_limit: int = DEFAULT_TIME_LIMIT_SECONDS,
    mip_gap: float = DEFAULT_MIP_GAP,
    seed: int | None = None,
    yes: bool = typer.Option(False, "--yes", help="Auto-accept the reforecast proposal without prompting."),
) -> None:
    """The simulated real-time engine, one month at a time.

    Hand-edit `pre_assignments.json` in `data_dir` before running this to make your
    own manual pre-assignment decisions for the month about to be solved (add or
    change a bounds row for a project/person/month) — that's the one file this
    command treats as planner input, separate from anything the solver or the
    simulation itself writes. Each run: applies and clears `pre_assignments.json`,
    solves the current month forward, "simulates worker activity" (synthetic
    actuals) for the month just solved, closes it, computes a reforecast proposal
    from the new actuals, and — on your say-so — writes it back. State is saved to
    `data_dir`, so the next run naturally continues from here. Work assignments,
    that month's variance, and a budget summary for every project active that month
    are written to `output_dir/<month>/`.
    """
    plan = load_plan(data_dir)

    pre_assignments = load_pre_assignments(data_dir)
    if pre_assignments:
        console.print(
            f"[cyan]Applying {len(pre_assignments)} manual pre-assignment(s) "
            f"from pre_assignments.json[/cyan]"
        )
        plan = apply_pre_assignments(plan, pre_assignments)

    current_month = plan.closed_through.add(1) if plan.closed_through else plan.horizon_start
    if current_month > plan.horizon_end:
        console.print("[yellow]Horizon exhausted — nothing more to advance.[/yellow]")
        raise typer.Exit()

    console.rule(f"Solving for {current_month} forward")
    result = solve(plan, weights=Weights(), time_limit_seconds=time_limit, mip_gap=mip_gap)
    if not result.feasible:
        console.print("[red]INFEASIBLE[/red]")
        console.print(result.diagnostics.render() if result.diagnostics else "no diagnostics")
        raise typer.Exit(code=1)

    console.print(f"[green]Solved[/green] (solve_id={result.solve_id}). Plan for {current_month}:")
    rows = build_rows(plan, result.hours_assigned)
    render_task_view(plan, [r for r in rows if r.month == current_month], console)

    console.rule(f"Simulating worker activity for {current_month}")
    rng = random.Random(seed)
    simulated = simulate_actuals_for_month(plan, current_month, result.hours_assigned, rng)
    console.print(f"Simulated actuals for {len(simulated)} (project, person) assignments.")

    existing = [a for a in plan.allocation if a.month != current_month]
    plan_with_actuals = plan.model_copy(
        update={"allocation": existing + simulated, "closed_through": current_month}
    )

    # Exported from plan_with_actuals, not plan: the variance sheet needs this
    # month's just-simulated actuals attached, or it would show no rows for it.
    month_dir = output_dir / str(current_month)
    export_month_snapshot(plan_with_actuals, result.hours_assigned, current_month, month_dir)
    export_staffing_balance(plan_with_actuals, output_dir / "staffing_balance.csv", hours_assigned=result.hours_assigned)
    console.print(f"Work assignments, variance, and budget summaries written to {month_dir}/")
    console.print(f"Staffing balance (whole-horizon) refreshed at {output_dir}/staffing_balance.csv")

    console.rule(f"Reforecast proposal, using {current_month}'s new actuals")
    proposals = []
    for project in plan.projects:
        if not (project.pop_start <= current_month <= project.pop_end):
            continue
        try:
            proposal = propose_reforecast(plan_with_actuals, project.project_id, current_month)
        except ValueError:
            continue
        if not proposal.updated_targets:
            continue
        proposals.append(proposal)
        console.print(f"{project.project_id}: variance {proposal.variance:+,.0f} (target - actual)")
        for m, new_target in proposal.updated_targets.items():
            console.print(f"    {m}: -> {new_target:,.0f}")

    if not proposals:
        console.print("No projects had a target to reforecast against this month.")
        final_plan = plan_with_actuals
    else:
        accept = yes or typer.confirm("Accept these reforecast proposals?", default=False)
        if accept:
            targets = list(plan_with_actuals.targets)
            for proposal in proposals:
                for m, new_value in proposal.updated_targets.items():
                    idx = next(
                        i
                        for i, t in enumerate(targets)
                        if t.project_id == proposal.project_id and t.month == m
                    )
                    targets[idx] = targets[idx].model_copy(update={"labor_spend_target": new_value})
            final_plan = plan_with_actuals.model_copy(update={"targets": targets})
            console.print("[green]Reforecast accepted and applied.[/green]")
        else:
            final_plan = plan_with_actuals
            console.print("[yellow]Reforecast NOT applied — targets unchanged.[/yellow]")

    save_plan(final_plan, data_dir)
    clear_pre_assignments(data_dir)  # this cycle's manual entries are now permanent in bounds.json
    next_month = current_month.add(1)
    if next_month <= plan.horizon_end:
        console.print(f"State saved to {data_dir}. Next month to advance: {next_month}")
    else:
        console.print(f"State saved to {data_dir}. Horizon complete.")


if __name__ == "__main__":
    app()
