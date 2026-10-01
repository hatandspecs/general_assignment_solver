"""The working assignment — the planner's ballpark, the solver's starting point, and
the solver's own output, all one object.

`05-interfaces.md`'s manual pre-assignments (`io/pre_assignments.py`) are
`Bounds`-shaped: an hour *range* per cell, applied as a constraint before the solver
runs, and necessarily self-consistent (`hard_min <= soft_min <= soft_max <= hard_max`).
That shape cannot hold the other thing a planner arrives with — a hand-built, partial,
"roughly this" assignment of actual hours, drawn up without checking it against
capacity or bounds at all. Both shapes are supported; this module is the hours-shaped
one.

The working assignment lives where the solved hours already live: `plan.allocation`'s
open months. One object, three roles:

- **imported** from a hand-built CSV or JSON, however wrong (`parse_rows`,
  `merged_allocation`);
- **read as the solver's starting point** — `baseline_of`, passed to
  `solve(plan, baseline=...)`, which turns the churn term into an attraction toward
  the ballpark rather than toward nothing, so an unlocked cell moves only as far as
  feasibility and the other objective terms genuinely require;
- **overwritten by that solve's result**, which is therefore the next iteration's
  starting point with no conversion step at all.

Constraint violations in an imported ballpark are expected, not rejected. `audit`
names every one without blocking the import: pulling an infeasible ballpark back to
feasibility is the solver's job, and it can only do that if the ballpark is let in.
Two kinds are worth telling apart, which is most of why `audit` exists:

- a cell that is *eligible* but out of bounds, over capacity, or over-fragmented —
  the solver will fix it, since it is only a starting point. Informational.
- a cell with no `Bounds` row at all, or with `eligible=False` — `eligible_cells`
  generates no variable for it (`costing/masks.py`), so the solver cannot place anyone
  there and will silently drop the ballpark's intent for that cell. That one needs a
  decision: add the `Bounds` row, or accept the cell staying empty.
"""

import csv
import io
import json
from dataclasses import dataclass

from allocsolver.costing.masks import Cell, eligible_cells
from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.models.projects import ProjectStatus

WORKING_ASSIGNMENT_COLUMNS = ["project_id", "person_id", "month", "hours", "locked"]

# Statuses whose row the solver can actually see. Everything else names a cell that
# generates no variable, so merging it would write a number nothing ever reads.
APPLIED_STATUSES = frozenset({"ok", "above_hard_max", "below_hard_min"})

_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "lock", "locked", "x"})
_FALSEY = frozenset({"", "0", "false", "f", "no", "n", "unlocked"})


class WorkingAssignmentParseError(ValueError):
    """Raised with a message meant for the planner, naming the offending row."""


@dataclass(frozen=True, slots=True)
class WorkingRow:
    """One hand-authored cell of the ballpark: hours, and whether they're pinned."""

    project_id: str
    person_id: str
    month: Month
    hours: float
    locked: bool = False

    @property
    def cell(self) -> Cell:
        return (self.project_id, self.person_id, self.month)


@dataclass(frozen=True, slots=True)
class AuditRow:
    """What the solver will make of one imported row — see this module's docstring.

    `applied` is the load-bearing field: False means the solver generates no variable
    for this cell, so importing the row would be writing a number nothing reads.
    """

    project_id: str | None
    person_id: str | None
    month: str
    hours: float
    locked: bool
    status: str
    applied: bool
    detail: str


def _parse_bool(value: object, *, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSEY:
        return False
    raise WorkingAssignmentParseError(f"{where}: {value!r} is not a yes/no value for `locked`")


def _parse_hours(value: object, *, where: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        hours = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkingAssignmentParseError(f"{where}: {value!r} is not a number of hours") from exc
    if hours < 0:
        raise WorkingAssignmentParseError(f"{where}: hours cannot be negative ({hours})")
    return hours


def _row_from_mapping(raw: dict, *, where: str) -> WorkingRow:
    """One dict -> one `WorkingRow`, accepting either of the two names the hours
    column goes by: `hours` (what this module's own CSV export writes) or
    `hours_assigned` (what `Allocation`/`AllocationRow` call it), so a sheet exported
    straight out of the Grist Allocation table imports without being renamed first."""
    lowered = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}
    missing = [c for c in ("project_id", "person_id", "month") if not str(lowered.get(c) or "").strip()]
    if missing:
        raise WorkingAssignmentParseError(f"{where}: missing required column(s) {', '.join(missing)}")

    if "hours" in lowered and str(lowered["hours"] or "").strip():
        hours_value = lowered["hours"]
    elif "hours_assigned" in lowered:
        hours_value = lowered["hours_assigned"]
    else:
        hours_value = lowered.get("hours")

    month_text = str(lowered["month"]).strip()
    try:
        month = Month.parse(month_text)
    except (ValueError, AttributeError) as exc:
        raise WorkingAssignmentParseError(f"{where}: {month_text!r} is not a YYYY-MM month") from exc

    return WorkingRow(
        project_id=str(lowered["project_id"]).strip(),
        person_id=str(lowered["person_id"]).strip(),
        month=month,
        hours=_parse_hours(hours_value, where=where),
        locked=_parse_bool(lowered.get("locked"), where=where),
    )


def parse_rows(raw: bytes | str, *, filename: str = "") -> list[WorkingRow]:
    """Parses a hand-built ballpark from CSV or JSON.

    Format is detected from the content, not the extension — a planner who exports
    "CSV" from a spreadsheet and saves it as `.txt` should not have to care. JSON is a
    list of objects; CSV is a header row plus data. Either way the columns are
    `project_id, person_id, month, hours, locked`, with `hours_assigned` accepted as a
    synonym for `hours` and `locked` optional.

    Deliberately does no plan validation: an unknown id, an out-of-bounds hour count
    and an ineligible pair are all `audit`'s business, reported rather than raised. The
    only errors here are ones that make the bytes unreadable as a table at all.
    """
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    stripped = text.lstrip()
    if not stripped:
        raise WorkingAssignmentParseError(f"{filename or 'file'} is empty")

    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise WorkingAssignmentParseError(f"{filename or 'file'} is not valid JSON: {exc}") from exc
        if isinstance(data, dict):
            # Tolerate a wrapped shape, e.g. {"rows": [...]} or {"working_assignment": [...]}.
            for key in ("rows", "working_assignment", "assignment", "cells"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise WorkingAssignmentParseError(
                f"{filename or 'file'}: expected a JSON list of assignment rows, got {type(data).__name__}"
            )
        return [_row_from_mapping(row, where=f"row {i + 1}") for i, row in enumerate(data)]

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise WorkingAssignmentParseError(f"{filename or 'file'}: no CSV header row found")
    rows = [
        _row_from_mapping(row, where=f"line {i + 2}")  # +2: header is line 1, enumerate is 0-based
        for i, row in enumerate(reader)
        if any(str(v or "").strip() for v in row.values())  # skip blank trailing lines
    ]
    if not rows:
        raise WorkingAssignmentParseError(
            f"{filename or 'file'}: header row read, but no data rows "
            f"(columns seen: {', '.join(reader.fieldnames)})"
        )
    return rows


def baseline_of(plan: Plan) -> dict[Cell, float]:
    """The solver's `baseline` argument: the current working assignment's open months.

    Closed months are excluded on purpose — C5 pins them to `hours_actual` regardless
    (`solve/build.py`), so a churn term against them would charge the objective for
    history it cannot change. A cell absent here baselines at 0.0 (`constraints.py`'s
    C7 `baseline.get(cell, 0.0)`), which is what makes a *partial* ballpark mean what
    a planner expects: the cells they left out are pulled toward empty, not treated as
    unconstrained.
    """
    closed_through = plan.closed_through
    return {
        (a.project_id, a.person_id, a.month): a.hours_assigned
        for a in plan.allocation
        if closed_through is None or a.month > closed_through
    }


def audit(plan: Plan, rows: list[WorkingRow]) -> list[AuditRow]:
    """Classifies every imported row against the plan, and reports the two aggregate
    violations a single row can't show on its own (capacity, fragmentation).

    Nothing here blocks an import. The output is a report: `applied=False` rows are
    the ones the solver structurally cannot act on, and the rest are either clean or
    carry a violation the solver is expected to resolve.
    """
    person_ids = {p.person_id for p in plan.people}
    projects_by_id = {p.project_id: p for p in plan.projects}
    horizon = set(plan.horizon())
    eligible = set(eligible_cells(plan))
    bounds_index = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
    closed_through = plan.closed_through

    out: list[AuditRow] = []
    for row in rows:
        status, detail = "ok", ""
        project = projects_by_id.get(row.project_id)

        if row.person_id not in person_ids:
            status, detail = "unknown_person", f"no person with id {row.person_id!r} in this plan"
        elif project is None:
            status, detail = "unknown_project", f"no project with id {row.project_id!r} in this plan"
        elif row.month not in horizon:
            status, detail = (
                "out_of_horizon",
                f"{row.month} is outside the plan horizon {plan.horizon_start}..{plan.horizon_end}",
            )
        elif closed_through is not None and row.month <= closed_through:
            status, detail = (
                "closed_month",
                f"{row.month} is closed (through {closed_through}) — its hours are actuals now, not assignable",
            )
        elif project.status != ProjectStatus.ACTIVE:
            status, detail = "project_not_active", f"project {row.project_id} has status {project.status}"
        elif not (project.pop_start <= row.month <= project.pop_end):
            status, detail = (
                "out_of_pop",
                f"{row.month} is outside {row.project_id}'s PoP {project.pop_start}..{project.pop_end}",
            )
        elif not plan.person(row.person_id).is_active(row.month):
            status, detail = "person_inactive", f"{row.person_id} is not employed in {row.month}"
        elif row.cell not in eligible:
            existing = bounds_index.get(row.cell)
            status = "not_eligible"
            detail = (
                f"{row.person_id} is marked eligible=False on {row.project_id} for {row.month}"
                if existing is not None
                else f"no Bounds row exists for {row.project_id}/{row.person_id}/{row.month}"
            )
            detail += " — the solver has no variable for this cell and will leave it empty"
        else:
            bound = bounds_index[row.cell]
            if row.hours > bound.hard_max + 1e-9:
                status, detail = (
                    "above_hard_max",
                    f"{row.hours:g}h is over this cell's hard_max of {bound.hard_max:g}h; "
                    f"{'the lock will override the bound' if row.locked else 'the solver will pull it down'}",
                )
            elif 0 < row.hours < bound.hard_min - 1e-9:
                status, detail = (
                    "below_hard_min",
                    f"{row.hours:g}h is under this cell's hard_min of {bound.hard_min:g}h; "
                    f"{'the lock will override the bound' if row.locked else 'the solver will raise it or empty the cell'}",
                )

        out.append(
            AuditRow(
                project_id=row.project_id,
                person_id=row.person_id,
                month=str(row.month),
                hours=round(row.hours, 2),
                locked=row.locked,
                status=status,
                applied=status in APPLIED_STATUSES,
                detail=detail,
            )
        )

    applied_cells = {(r.project_id, r.person_id, r.month) for r in out if r.applied}
    out.extend(_aggregate_audit_rows(plan, rows, applied_cells))
    out.sort(key=lambda r: (r.applied, r.status, r.person_id or "", r.project_id or "", r.month))
    return out


def _aggregate_audit_rows(
    plan: Plan, rows: list[WorkingRow], applied_cells: set[tuple[str | None, str | None, str]]
) -> list[AuditRow]:
    """Capacity and fragmentation violations, which live on a (person, month) rather
    than on any one cell — a ballpark that puts someone on five projects at 60h each
    has nothing wrong with any single row of it."""
    hours_by_person_month: dict[tuple[str, Month], float] = {}
    projects_by_person_month: dict[tuple[str, Month], set[str]] = {}
    for row in rows:
        if (row.project_id, row.person_id, str(row.month)) not in applied_cells:
            continue
        key = (row.person_id, row.month)
        hours_by_person_month[key] = hours_by_person_month.get(key, 0.0) + row.hours
        if row.hours > 1e-9:
            projects_by_person_month.setdefault(key, set()).add(row.project_id)

    out: list[AuditRow] = []
    for (person_id, month), total in sorted(hours_by_person_month.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        try:
            available = plan.capacity_of(person_id, month).available_hours
        except KeyError:  # no capacity row — Plan validation already reports this for active people
            continue
        if total > available + 1e-6:
            out.append(
                AuditRow(
                    project_id=None,
                    person_id=person_id,
                    month=str(month),
                    hours=round(total, 2),
                    locked=False,
                    status="over_capacity",
                    applied=True,
                    detail=(
                        f"the ballpark gives {person_id} {total:g}h in {month}, over their "
                        f"{available:g}h of capacity — the solver must shed {total - available:g}h "
                        f"from somewhere unless those cells are locked"
                    ),
                )
            )

    for (person_id, month), project_ids in sorted(
        projects_by_person_month.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
    ):
        hard_max = plan.person(person_id).hard_max_concurrent_projects
        if len(project_ids) > hard_max:
            out.append(
                AuditRow(
                    project_id=None,
                    person_id=person_id,
                    month=str(month),
                    hours=float(len(project_ids)),
                    locked=False,
                    status="over_concurrent",
                    applied=True,
                    detail=(
                        f"the ballpark puts {person_id} on {len(project_ids)} projects in {month}, over their "
                        f"hard_max_concurrent_projects of {hard_max} — the solver must drop "
                        f"{len(project_ids) - hard_max} unless those cells are locked"
                    ),
                )
            )

    return out


def permissive_bounds_for(plan: Plan, rows: list[WorkingRow], audit_rows: list[AuditRow]) -> list[Bounds]:
    """`Bounds` rows that would make the `not_eligible` cells of a ballpark eligible.

    Permissive on purpose: `hard_min`/`soft_min` of 0 and a `hard_max`/`soft_max` wide
    enough to hold the hours the planner actually asked for (rounded up to the person's
    capacity for that month, so the cell isn't born already pinned to one value). This
    opens a cell for the solver to use; it does not tell the solver to use it.

    Only ever returned, never applied here — making a person eligible for a project is
    a real planning decision, so it stays an explicit opt-in at the call site.
    """
    needs_bounds = {
        (r.project_id, r.person_id, r.month) for r in audit_rows if r.status == "not_eligible" and r.project_id
    }
    existing = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}

    out: list[Bounds] = []
    for row in rows:
        key = (row.project_id, row.person_id, str(row.month))
        if key not in needs_bounds:
            continue
        needs_bounds.discard(key)  # one Bounds row per cell even if the file repeats it
        try:
            ceiling = plan.capacity_of(row.person_id, row.month).available_hours
        except KeyError:
            ceiling = row.hours
        hard_max = max(ceiling, row.hours)
        prior = existing.get(row.cell)
        out.append(
            Bounds(
                project_id=row.project_id,
                person_id=row.person_id,
                month=row.month,
                hard_min=0.0,
                soft_min=0.0,
                # Keep a hand-set soft_max if the row existed and was merely eligible=False;
                # flipping the flag shouldn't quietly widen a range someone chose.
                soft_max=prior.soft_max if prior is not None else hard_max,
                hard_max=prior.hard_max if prior is not None else hard_max,
                eligible=True,
            )
        )
    return out


def merged_allocation(
    plan: Plan, rows: list[WorkingRow], audit_rows: list[AuditRow], *, solve_id: str | None = None
) -> list[AllocationRow]:
    """The `allocation` list that results from importing a ballpark.

    Replaces the open months wholesale rather than upserting into them: an imported
    ballpark is a statement about the whole open horizon ("this is the plan"), so a
    cell the file omits should end up empty, not keep a number from a previous
    iteration that the planner has no reason to expect is still there. Closed months
    are carried through untouched — their `hours_actual` is historical fact.

    Rows the audit marked `applied=False` are dropped, since the solver generates no
    variable for those cells (`costing/masks.py`); `audit`'s report is where they get
    explained rather than silently vanishing.
    """
    applied_keys = {
        (r.project_id, r.person_id, r.month) for r in audit_rows if r.applied and r.project_id is not None
    }
    closed_through = plan.closed_through
    kept = [a for a in plan.allocation if closed_through is not None and a.month <= closed_through]

    by_cell: dict[Cell, WorkingRow] = {}
    for row in rows:
        if (row.project_id, row.person_id, str(row.month)) not in applied_keys:
            continue
        by_cell[row.cell] = row  # a repeated cell takes its last value, like a spreadsheet would

    new_rows = [
        AllocationRow(
            project_id=row.project_id,
            person_id=row.person_id,
            month=row.month,
            hours_assigned=round(row.hours, 2),
            hours_actual=None,
            locked=row.locked,
            lock_note="imported ballpark" if row.locked else None,
            solve_id=solve_id,
        )
        for row in by_cell.values()
    ]
    new_rows.sort(key=lambda a: (str(a.month), a.project_id, a.person_id))
    return kept + new_rows


def to_csv(plan: Plan, *, open_months_only: bool = True) -> str:
    """The current working assignment as a CSV `parse_rows` can read back, so a
    planner can pull an iteration into a spreadsheet, rework it there, and re-import."""
    closed_through = plan.closed_through
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=WORKING_ASSIGNMENT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    rows = sorted(plan.allocation, key=lambda a: (str(a.month), a.project_id, a.person_id))
    for a in rows:
        if open_months_only and closed_through is not None and a.month <= closed_through:
            continue
        writer.writerow(
            {
                "project_id": a.project_id,
                "person_id": a.person_id,
                "month": str(a.month),
                "hours": round(a.hours_assigned, 2),
                "locked": "true" if a.locked else "false",
            }
        )
    return buf.getvalue()
