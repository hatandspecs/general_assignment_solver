"""Typer entry points — `05-interfaces.md`, "CLI".

Scoped to what this build actually implements: `solve`, `validate`, and `export`
against a local JSON data directory (see `io/local.py`). Grist REST integration,
live timekeeping ingest, reforecast-as-a-CLI-step, and snapshot/diff are documented
in `05-interfaces.md` but not yet wired up here.
"""

from pathlib import Path

import typer
from rich.console import Console

from allocsolver.config import DEFAULT_MIP_GAP, DEFAULT_TIME_LIMIT_SECONDS, Weights
from allocsolver.io.local import load_plan
from allocsolver.reports.exports import export_budget_summary, export_variance_sheet, export_workforce_sheet
from allocsolver.reports.render import render_resource_view, render_task_view
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
        export_workforce_sheet(plan, result.hours_assigned, first_month, export_dir / f"assignments_{first_month}.csv")
        export_variance_sheet(plan, result.hours_assigned, export_dir / "variance.csv")
        for project in plan.projects:
            export_budget_summary(
                plan, result.hours_assigned, project.project_id, export_dir / f"budget_{project.project_id}.csv"
            )
        console.print(f"Exports written to {export_dir}")


if __name__ == "__main__":
    app()
