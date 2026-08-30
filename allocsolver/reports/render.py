"""Rich terminal output for the task view and resource view (`03-data-model.md`)."""

from rich.console import Console
from rich.table import Table

from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan

from .views import ViewRow, assigned_fte, group_by_person, group_by_project, totals_of


def render_task_view(plan: Plan, rows: list[ViewRow], console: Console | None = None) -> None:
    console = console or Console()
    for project_id, project_rows in sorted(group_by_project(rows).items()):
        project = plan.project(project_id)
        table = Table(title=f"Task view: {project.name} ({project_id})")
        table.add_column("Person")
        table.add_column("Month")
        table.add_column("Hard min", justify="right")
        table.add_column("Soft min", justify="right")
        table.add_column("Soft max", justify="right")
        table.add_column("Hard max", justify="right")
        table.add_column("Assigned h", justify="right")
        table.add_column("Assigned $", justify="right")
        table.add_column("Delta h", justify="right")

        for row in sorted(project_rows, key=lambda r: (r.person_id, r.month)):
            person = plan.person(row.person_id)
            table.add_row(
                person.name,
                str(row.month),
                f"{row.hard_min:.0f}",
                f"{row.soft_min:.0f}",
                f"{row.soft_max:.0f}",
                f"{row.hard_max:.0f}",
                f"{row.hours_assigned:.1f}",
                f"{row.assigned_cost:,.0f}",
                "-" if row.delta_hours is None else f"{row.delta_hours:+.1f}",
            )

        t = totals_of(project_rows)
        delta_str = "-" if t.delta_hours is None else f"{t.delta_hours:+.1f}"
        table.add_row(
            "[bold]Totals[/bold]", "", "", "", "", "",
            f"[bold]{t.hours_assigned:.1f}[/bold]",
            f"[bold]{t.assigned_cost:,.0f}[/bold]",
            f"[bold]{delta_str}[/bold]",
        )
        console.print(table)


def render_resource_view(
    plan: Plan, rows: list[ViewRow], hours_assigned: dict, console: Console | None = None
) -> None:
    console = console or Console()
    for person_id, person_rows in sorted(group_by_person(rows).items()):
        person = plan.person(person_id)
        table = Table(title=f"Resource view: {person.name} ({person_id})")
        table.add_column("Project")
        table.add_column("Month")
        table.add_column("Hard min", justify="right")
        table.add_column("Soft max", justify="right")
        table.add_column("Hard max", justify="right")
        table.add_column("Assigned h", justify="right")
        table.add_column("Assigned $", justify="right")

        for row in sorted(person_rows, key=lambda r: (r.project_id, r.month)):
            project = plan.project(row.project_id)
            table.add_row(
                project.name,
                str(row.month),
                f"{row.hard_min:.0f}",
                f"{row.soft_max:.0f}",
                f"{row.hard_max:.0f}",
                f"{row.hours_assigned:.1f}",
                f"{row.assigned_cost:,.0f}",
            )

        months = sorted({row.month for row in person_rows})
        fte_line = ", ".join(
            f"{m}: {assigned_fte(plan, hours_assigned, person_id, m):.0%}" for m in months
        )
        console.print(table)
        console.print(f"  [dim]Assigned %FTE by month — {fte_line}[/dim]")
