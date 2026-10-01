"""The planner control-panel backend — what the widget's buttons call.

Every endpoint loads the current `Plan` fresh from Grist and, where it persists
anything, saves the whole plan back afterward (`plan_sync.py` mirrors `io/local.py`'s
"rewrite each table in full" posture) — there is no in-process session state, so a
container restart between clicks changes nothing.

Two postures, matching `allocsolver.cli`'s existing dry-run/accept pattern:
- `run-planning` and the `dry_run=true` half of `actuals/upload` never write to
  Grist — preview only.
- `export-work-assignments`, `run-portfolio-reports`, and the `dry_run=false` half
  of `actuals/upload` are the only endpoints that persist anything.
"""

import csv
import io
import json
import os
import random
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from allocsolver.config import (
    ADHERENCE_CHURN_WEIGHTS,
    DEFAULT_ADHERENCE,
    DEFAULT_MIP_GAP,
    DEFAULT_TIME_LIMIT_SECONDS,
    weights_for_adherence,
)
from allocsolver.io.pre_assignments import apply_pre_assignments
from allocsolver.io.synthetic import simulate_actuals_for_month
from allocsolver.io.working_assignment import (
    WorkingAssignmentParseError,
    audit,
    baseline_of,
    merged_allocation,
    parse_rows,
    permissive_bounds_for,
    to_csv,
)
from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.solve.locks import lock_conflicts
from allocsolver.solve.run import solve

from . import history, reports
from .grist_client import GristClient
from .plan_sync import (
    clear_pre_assignments_in_grist,
    load_plan_from_grist,
    load_pre_assignments_from_grist,
    save_plan_to_grist,
    write_pre_assignments_to_grist,
)
from .schema import REPORT_TABLES

app = FastAPI(title="Planner control panel")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # localhost-only demo deployment; see docs/08-grist-ui-design.md
    allow_methods=["*"],
    allow_headers=["*"],
)

_WIDGET_DIR = Path(__file__).parent.parent / "widget"
if _WIDGET_DIR.exists():
    app.mount("/widget", StaticFiles(directory=str(_WIDGET_DIR), html=True), name="widget")


def _client() -> GristClient:
    state_path = Path(os.environ.get("STATE_FILE", "/data/.grist_state.json"))
    if not state_path.exists():
        raise HTTPException(503, "Not provisioned yet — run `./deploy_planner.sh up` first.")
    with open(state_path) as f:
        state = json.load(f)
    grist_url = os.environ.get("GRIST_INTERNAL_URL", "http://grist:8484")
    return GristClient(grist_url, state["api_key"], state["doc_id"])


def _current_month(plan) -> Month:
    return plan.closed_through.add(1) if plan.closed_through else plan.horizon_start


def _conflict_dicts(conflicts) -> list[dict]:
    return [
        {
            "kind": c.kind,
            "person_id": c.person_id,
            "project_id": c.project_id,
            "month": c.month,
            "locked_amount": c.locked_amount,
            "limit": c.limit,
            "cells": list(c.cells),
            "detail": c.detail,
            "blocking": c.is_infeasible,
        }
        for c in conflicts
    ]


def _working_hours(plan) -> dict:
    """The working assignment's hours, keyed like a solve result's `hours_assigned`.

    Reports and exports read this instead of solving again. A fresh solve is not a
    read-only operation on this data: the model has many equally optimal assignments,
    so re-solving to "look up" the current hours can legitimately return a different
    plan than the one on screen, and a planner comparing a budget report against the
    `Allocation` table would see two different stories with no indication why. The
    working assignment is the single answer to "what is the plan right now".
    """
    closed_through = plan.closed_through
    hours: dict = {}
    for a in plan.allocation:
        if closed_through is not None and a.month <= closed_through:
            # Closed months report what actually happened, which is what C5 pins them to.
            hours[(a.project_id, a.person_id, a.month)] = (
                a.hours_actual if a.hours_actual is not None else a.hours_assigned
            )
        else:
            hours[(a.project_id, a.person_id, a.month)] = a.hours_assigned
    return hours


def _solve_or_422(plan, adherence: str = DEFAULT_ADHERENCE):
    """Every solve in this service goes through here, and every one of them is
    baselined on the current working assignment (`baseline_of`).

    That is what makes the loop coherent rather than merely repeatable: with a baseline,
    re-solving an already-solved plan returns the same assignment (the fixed-point
    property in `tests/unit/test_working_assignment.py`), so Run Planning, Export Work
    Assignments and the report endpoints can no longer each land on a different equally
    optimal answer and show a planner three versions of "the plan".
    """
    try:
        weights = weights_for_adherence(adherence)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc

    result = solve(
        plan,
        baseline=baseline_of(plan),
        weights=weights,
        time_limit_seconds=DEFAULT_TIME_LIMIT_SECONDS,
        mip_gap=DEFAULT_MIP_GAP,
    )
    if not result.feasible:
        detail = result.diagnostics.render() if result.diagnostics else "no diagnostics available"
        raise HTTPException(
            422,
            {
                "message": "No assignment satisfies the current locks, bounds and targets.",
                "diagnostics": detail,
                "lock_conflicts": _conflict_dicts(
                    result.diagnostics.lock_conflicts if result.diagnostics else []
                ),
            },
        )
    return result


def _solution_rows(plan, result) -> tuple[list[AllocationRow], list[AllocationRow]]:
    """Splits a solve result into (open rows, closed rows) for `Allocation`.

    The open rows *are* the next iteration's working assignment — the solver's output
    and the planner's next starting point are the same object, which is what lets the
    tweak-and-solve loop run indefinitely without a conversion step between rounds
    (`io/working_assignment.py`).

    Closed months are carried through verbatim: they hold `hours_actual` and C5 fixes
    their cells to it regardless of `locked`. A cell's own `locked` flag is read from
    `plan.allocation` as it was *before* this solve and carried forward unchanged —
    this never writes `locked` itself, matching `05-interfaces.md`'s "never written by
    the solver: ... locked".
    """
    closed_through = plan.closed_through
    prior_by_cell = {(a.project_id, a.person_id, a.month): a for a in plan.allocation}
    closed_rows = [a for a in plan.allocation if closed_through and a.month <= closed_through]

    open_rows = []
    for (p, w, m), hours in result.hours_assigned.items():
        if closed_through and m <= closed_through:
            continue
        prior = prior_by_cell.get((p, w, m))
        locked = bool(prior.locked) if prior is not None else False
        # Filter on the *rounded* value, not the raw one. Where `hard_min` is 0 the
        # solver may legitimately assign a fraction of an hour, and a cell holding
        # 0.004h is stored and displayed as 0.00 — an assignment of nobody to nothing,
        # which reads as a bug in the Allocation table and pads the solve diff with
        # rows whose delta is 0.0. A locked cell is kept regardless: locking a cell
        # empty is a deliberate instruction.
        rounded = round(hours, 2)
        if rounded <= 0.0 and not locked:
            continue
        open_rows.append(
            AllocationRow(
                project_id=p,
                person_id=w,
                month=m,
                hours_assigned=rounded,
                hours_actual=None,
                locked=locked,
                lock_note=prior.lock_note if prior is not None else None,
                solve_id=result.solve_id,
            )
        )
    open_rows.sort(key=lambda a: (str(a.month), a.project_id, a.person_id))
    return open_rows, closed_rows


def _write_solution_to_allocation(plan, result, client: GristClient) -> list[AllocationRow]:
    open_rows, closed_rows = _solution_rows(plan, result)
    history.write_working_assignment(client, open_rows, closed_rows)
    return open_rows


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/state")
def get_state():
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        pre_assignments = load_pre_assignments_from_grist(client)
        current_month = _current_month(plan)
        working = history.open_month_rows(plan.allocation, plan.closed_through)
        latest = history.latest_iteration(client)
        # Reported even when nothing has failed: a lock on an ineligible cell is
        # silently dropped, so a planner needs telling before they rely on it.
        warnings = [c for c in lock_conflicts(plan) if not c.is_infeasible]
        return {
            "horizon_start": str(plan.horizon_start),
            "horizon_end": str(plan.horizon_end),
            "closed_through": str(plan.closed_through) if plan.closed_through else None,
            "current_month": str(current_month),
            "horizon_exhausted": current_month > plan.horizon_end,
            "num_people": len(plan.people),
            "num_projects": len(plan.projects),
            "num_pre_assignments": len(pre_assignments),
            "working_cells": len(working),
            "working_locked": sum(1 for a in working if a.locked),
            "working_hours": round(sum(a.hours_assigned for a in working), 2),
            "iteration": latest["iteration"] if latest else 0,
            "iteration_source": latest["source"] if latest else None,
            "unsaved_tweaks": history.differs_from_latest(client, working),
            "lock_warnings": _conflict_dicts(warnings),
            "adherence_levels": list(ADHERENCE_CHURN_WEIGHTS),
            "default_adherence": DEFAULT_ADHERENCE,
        }
    finally:
        client.close()


# --- The working assignment: import, inspect, lock, solve, undo ---------------------
#
# Steps 1-5 of the planner's loop. The object every one of them reads and writes is
# `Allocation`'s open months (`io/working_assignment.py`): the imported ballpark, the
# thing hand-tweaked in Grist, the solver's starting point and the solver's output are
# all the same rows, which is what makes "the result of this solve is the input to the
# next one" true by construction instead of by a conversion step.


@app.get("/api/working-assignment")
def get_working_assignment():
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        rows = history.open_month_rows(plan.allocation, plan.closed_through)
        rows.sort(key=lambda a: (str(a.month), a.project_id, a.person_id))
        return {
            "rows": [
                {
                    "project_id": a.project_id,
                    "person_id": a.person_id,
                    "person_name": plan.person(a.person_id).name if a.person_id in {p.person_id for p in plan.people} else a.person_id,
                    "month": str(a.month),
                    "hours_assigned": round(a.hours_assigned, 2),
                    "locked": bool(a.locked),
                }
                for a in rows
            ],
            "total_hours": round(sum(a.hours_assigned for a in rows), 2),
            "num_locked": sum(1 for a in rows if a.locked),
        }
    finally:
        client.close()


@app.get("/api/working-assignment/download")
def download_working_assignment():
    """The current working assignment as a CSV the import endpoint reads back, so an
    iteration can be pulled into a spreadsheet, reworked there, and re-imported."""
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        return Response(
            to_csv(plan),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="working_assignment.csv"'},
        )
    finally:
        client.close()


@app.post("/api/working-assignment/import")
async def import_working_assignment(
    file: UploadFile,
    dry_run: bool = Query(False, description="Audit the file and report, without writing anything"),
    make_eligible: bool = Query(
        False,
        description="Also add permissive Bounds rows for cells that have none, so the solver can use them",
    ),
):
    """Step 1: import the hand-built ballpark.

    CSV or JSON, columns `project_id, person_id, month, hours, locked` (`hours_assigned`
    accepted for `hours`; `locked` optional). Format is sniffed from the content.

    A partial, constraint-violating ballpark is the expected input, not an error case:
    the audit reports every violation and the import proceeds anyway, because pulling
    an infeasible starting point back to feasibility is precisely what the solve step
    is for. The one exception is structural — a cell with no eligible `Bounds` row has
    no solver variable at all (`costing/masks.py`), so its row is reported, excluded,
    and listed under `needs_bounds`. Re-submit with `make_eligible=true` to open those
    cells, which is a real staffing decision and so stays an explicit opt-in.
    """
    raw = await file.read()
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        try:
            rows = parse_rows(raw, filename=file.filename or "upload")
        except WorkingAssignmentParseError as exc:
            raise HTTPException(400, str(exc)) from exc

        audit_rows = audit(plan, rows)
        new_bounds = permissive_bounds_for(plan, rows, audit_rows)

        if make_eligible and new_bounds:
            # Re-audit against the widened plan so the response reports what the import
            # will actually do, not what it would have done without the new Bounds rows.
            merged_bounds = {(b.project_id, b.person_id, b.month): b for b in plan.bounds}
            for b in new_bounds:
                merged_bounds[(b.project_id, b.person_id, b.month)] = b
            plan = Plan.model_validate(
                {
                    **plan.model_dump(mode="json"),
                    "bounds": [b.model_dump(mode="json") for b in merged_bounds.values()],
                }
            )
            audit_rows = audit(plan, rows)

        report_rows = reports.ballpark_audit_rows(audit_rows)
        counts: dict[str, int] = {}
        for r in audit_rows:
            counts[r.status] = counts.get(r.status, 0) + 1

        response = {
            "dry_run": dry_run,
            "parsed": len(rows),
            "applied": sum(1 for r in audit_rows if r.applied and r.project_id),
            "dropped": sum(1 for r in audit_rows if not r.applied),
            "status_counts": counts,
            "audit_rows": report_rows,
            "needs_bounds": [
                {"project_id": b.project_id, "person_id": b.person_id, "month": str(b.month)}
                for b in new_bounds
            ],
            "made_eligible": len(new_bounds) if make_eligible else 0,
        }

        if dry_run:
            client.replace_table("Report_BallparkAudit", report_rows)
            return response

        if make_eligible and new_bounds:
            client.replace_table("Bounds", [b.model_dump(mode="json") for b in plan.bounds])

        allocation = merged_allocation(plan, rows, audit_rows)
        open_rows = history.open_month_rows(allocation, plan.closed_through)
        closed_rows = [a for a in allocation if plan.closed_through and a.month <= plan.closed_through]
        history.write_working_assignment(client, open_rows, closed_rows)
        client.replace_table("Report_BallparkAudit", report_rows)

        entry = history.snapshot(
            client,
            open_rows,
            source="import",
            label=f"imported {file.filename or 'ballpark'}",
            note=f"{len(rows)} row(s) parsed, {response['dropped']} not usable by the solver",
        )
        response["iteration"] = entry["iteration"] if entry else None
        return response
    finally:
        client.close()


@app.post("/api/working-assignment/locks")
def set_locks(
    locked: bool = Query(..., description="True to lock the matched cells, False to unlock"),
    project_id: str | None = Query(None),
    person_id: str | None = Query(None),
    month: str | None = Query(None, description="YYYY-MM"),
    only_nonzero: bool = Query(True, description="Skip cells with no hours (locking a 0 pins it empty)"),
):
    """Step 2, in bulk: lock or unlock everything matching the given filters.

    Individual cells are faster to toggle in the Grist `Allocation` table directly —
    this exists for the sweeps that are tedious there: pin an entire month before
    re-solving the rest of the horizon, pin one project's staffing, or clear every lock
    to start the iteration over. With no filters it matches the whole open horizon.

    Locking a zero-hour cell pins it *empty*, which is a legitimate thing to want and an
    easy thing to do by accident across a bulk sweep — hence `only_nonzero`, on by
    default.
    """
    try:
        target_month = Month.parse(month) if month else None
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, f"{month!r} is not a YYYY-MM month") from exc

    client = _client()
    try:
        plan = load_plan_from_grist(client)
        closed_through = plan.closed_through
        open_rows = history.open_month_rows(plan.allocation, closed_through)
        closed_rows = [a for a in plan.allocation if closed_through and a.month <= closed_through]

        changed = 0
        updated: list[AllocationRow] = []
        for a in open_rows:
            matches = (
                (project_id is None or a.project_id == project_id)
                and (person_id is None or a.person_id == person_id)
                and (target_month is None or a.month == target_month)
                and (not only_nonzero or a.hours_assigned > 1e-9)
            )
            if matches and bool(a.locked) != locked:
                changed += 1
                updated.append(
                    a.model_copy(
                        update={
                            "locked": locked,
                            "lock_note": "bulk lock" if locked else None,
                        }
                    )
                )
            else:
                updated.append(a)

        if changed:
            history.write_working_assignment(client, updated, closed_rows)
            history.snapshot(
                client,
                updated,
                source="locks",
                label=f"{'locked' if locked else 'unlocked'} {changed} cell(s)",
                note=", ".join(
                    f"{k}={v}"
                    for k, v in (("project", project_id), ("person", person_id), ("month", month))
                    if v
                )
                or "whole open horizon",
            )

        return {
            "changed": changed,
            "locked_now": sum(1 for a in updated if a.locked),
            "total_cells": len(updated),
        }
    finally:
        client.close()


@app.get("/api/working-assignment/history")
def get_history():
    """Step 5's list: every saved iteration, newest first."""
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        working = history.open_month_rows(plan.allocation, plan.closed_through)
        return {
            "iterations": history.list_iterations(client),
            "unsaved_tweaks": history.differs_from_latest(client, working),
        }
    finally:
        client.close()


@app.post("/api/working-assignment/restore")
def restore_iteration(iteration: int = Query(..., description="The iteration number to go back to")):
    """Step 5: go back to an earlier iteration.

    Append-only, so this is non-destructive in both directions: the restored cells are
    written into `Allocation` *and* appended as a new iteration, which leaves every
    later iteration still in the history and still restorable. Going back and then
    changing your mind costs nothing.
    """
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        rows = history.cells_of(client, iteration)
        known = {i["iteration"] for i in history.list_iterations(client)}
        if iteration not in known:
            raise HTTPException(
                404,
                f"No iteration {iteration}. Saved iterations: "
                f"{', '.join(str(i) for i in sorted(known)) or 'none yet'}",
            )

        closed_through = plan.closed_through
        closed_rows = [a for a in plan.allocation if closed_through and a.month <= closed_through]

        # Drop any restored cell whose month has closed since the snapshot was taken.
        # An iteration saved before a month closed still holds that month's open rows,
        # and writing them back alongside the closed ones puts the same cell in
        # `Allocation` twice — once with `hours_actual`, once without — which corrupts
        # the baseline and the variance report rather than failing visibly.
        restorable = history.open_month_rows(rows, closed_through)
        skipped = len(rows) - len(restorable)

        history.write_working_assignment(client, restorable, closed_rows)
        entry = history.snapshot(
            client,
            restorable,
            source="restore",
            label=f"restored iteration {iteration}",
            note=(
                "earlier iterations are kept — this appends rather than rewinding"
                + (f"; {skipped} cell(s) dropped, their month has closed since" if skipped else "")
            ),
        )
        return {
            "restored_from": iteration,
            "iteration": entry["iteration"] if entry else None,
            "num_cells": len(restorable),
            "num_locked": sum(1 for a in restorable if a.locked),
            "skipped_closed": skipped,
        }
    finally:
        client.close()


@app.post("/api/pre-assignments/upload")
async def upload_pre_assignments(file: UploadFile):
    """"Load a pre-assignment JSON" — the file is a list of `Bounds`-shaped rows
    (`05-interfaces.md`'s manual pre-assignments), same shape as `pre_assignments.json`.
    Replaces whatever's currently in the Pre_Assignments table."""
    raw = await file.read()
    try:
        data = json.loads(raw)
        pre_assignments = [Bounds.model_validate(row) for row in data]
    except Exception as exc:  # noqa: BLE001 - reported back to the planner, not logged
        raise HTTPException(400, f"Couldn't parse that file as pre-assignments: {exc}") from exc

    client = _client()
    try:
        write_pre_assignments_to_grist(client, pre_assignments)
    finally:
        client.close()
    return {"loaded": len(pre_assignments)}


@app.post("/api/run-planning")
def run_planning(
    adherence: str = Query(
        DEFAULT_ADHERENCE,
        description="How hard to keep the current working assignment: free | loose | close | exact",
    ),
):
    """Step 3: the solve button, and the hinge of the whole loop.

    Takes the current working assignment as its starting point (`baseline_of`, weighted
    by `adherence`), honors every `locked` cell as a hard pin, re-optimizes everything
    else, and writes the result back over the working assignment — which is therefore
    step 2's input for the next round, with nothing to convert.

    Three things happen around the solve that make the loop safe to run repeatedly:

    - the pre-solve state is snapshotted first if it differs from the last iteration,
      which is what captures hand-edits made directly in the Grist table — nothing else
      observes those, and without this a planner's tweaks would be unrecoverable the
      moment the solve overwrote them;
    - an infeasible solve returns 422 *having written nothing*, with the binding
      constraints and any lock conflicts named (`solve/locks.py`), so a failed solve
      costs the planner nothing and tells them what to change;
    - the diff of before-vs-after goes to `Report_SolveDiff` across the whole open
      horizon, so what the solver moved — and what it left alone because it was locked
      — is visible rather than inferred.

    Never touches `Bounds`, `Targets` or `closed_through`. Nothing is committed here.
    """
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        before = history.open_month_rows(plan.allocation, plan.closed_through)

        # Capture hand-edits *before* the solve overwrites them. Only if they're new:
        # re-solving without having touched anything shouldn't append a duplicate.
        tweak_entry = history.snapshot(
            client,
            before,
            source="tweak",
            label="hand-edited in Grist",
            note="captured before a solve overwrote it",
            only_if_changed=True,
        )

        pre_assignments = load_pre_assignments_from_grist(client)
        working_plan = apply_pre_assignments(plan, pre_assignments)
        result = _solve_or_422(working_plan, adherence=adherence)

        open_rows = _write_solution_to_allocation(plan, result, client)

        diff_rows = reports.working_diff_rows(before, result.hours_assigned, plan.closed_through)
        client.replace_table("Report_SolveDiff", diff_rows)

        counts: dict[str, int] = {}
        for row in diff_rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1

        entry = history.snapshot(
            client,
            open_rows,
            source="solve",
            label=f"solved ({adherence} adherence)",
            feasible=True,
            objective=result.objective.total if result.objective else None,
            adherence=adherence,
            note=f"{counts.get('adjusted', 0)} cell(s) adjusted, "
            f"{counts.get('added', 0)} added, {counts.get('dropped', 0)} dropped",
        )

        return {
            "feasible": True,
            "month": str(_current_month(plan)),
            "adherence": adherence,
            "objective": result.objective.total if result.objective else None,
            "wall_time_seconds": round(result.wall_time_seconds, 2),
            "iteration": entry["iteration"] if entry else None,
            "tweaks_saved_as": tweak_entry["iteration"] if tweak_entry else None,
            "num_locked": sum(1 for a in open_rows if a.locked),
            "lock_warnings": _conflict_dicts(result.lock_warnings),
            "diff_counts": counts,
            "diff_rows": diff_rows,
            # Whether the Bounds-shaped pre-assignment inbox (`io/pre_assignments.py`),
            # which is a separate and still-supported input, was honored this solve.
            "pre_assignment_diff": reports.solve_diff_rows(
                pre_assignments, result.hours_assigned, _current_month(plan)
            )
            if pre_assignments
            else [],
        }
    finally:
        client.close()


@app.post("/api/export-work-assignments")
def export_work_assignments(
    force: bool = Query(False, description="Commit hand-tweaks that have not been solved since"),
):
    """Commits: merges Pre_Assignments into Bounds for real and clears the inbox — the
    "send it to the workforce" moment, so the natural point the plan gets locked in
    (matching `apply_pre_assignments`'s "the override persists permanently in bounds"
    contract, `io/pre_assignments.py`).

    Exports the working assignment **as it stands** rather than re-solving it. The
    previous behavior re-solved here, which meant the sheet that went out to the team
    was produced by a different solver run than the one the planner reviewed and
    approved in step 3 — with no baseline wired in, that run could legitimately return
    a different, equally optimal assignment, and the plan would change after sign-off
    without anyone touching it. What was approved is what ships.

    The cost of not re-solving is that an unsolved hand-tweak would go out unchecked, so
    that is refused instead: tweak-then-commit returns 409 asking for a solve first,
    since an unsolved tweak has never been validated against capacity or the targets.
    `force=true` commits anyway, for the case where a planner deliberately wants their
    own numbers out regardless of what the model thinks of them.

    Deliberately writes only `Bounds`, `Allocation` and the report, not the whole plan
    via `save_plan_to_grist`, which would overwrite `Allocation` with the pre-commit
    copy this handler is holding.
    """
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        working = history.open_month_rows(plan.allocation, plan.closed_through)
        if not working:
            raise HTTPException(
                409, "The working assignment is empty — import a ballpark or run a solve first."
            )

        latest = history.latest_iteration(client)
        unsolved = history.differs_from_latest(client, working) or (
            latest is not None and latest["source"] not in ("solve", "restore")
        )
        if unsolved and not force:
            raise HTTPException(
                409,
                {
                    "message": (
                        "The working assignment has changes that haven't been through a solve, so "
                        "they've never been checked against capacity, bounds or the spend targets. "
                        "Run Solve first, or re-send with force=true to commit them as they are."
                    ),
                    "latest_iteration": latest["iteration"] if latest else None,
                    "latest_source": latest["source"] if latest else None,
                },
            )

        pre_assignments = load_pre_assignments_from_grist(client)
        working_plan = apply_pre_assignments(plan, pre_assignments)

        hours_assigned = {(a.project_id, a.person_id, a.month): a.hours_assigned for a in working}
        current_month = _current_month(plan)
        rows = reports.work_assignment_rows(working_plan, hours_assigned, current_month)

        client.replace_table("Bounds", [b.model_dump(mode="json") for b in working_plan.bounds])
        clear_pre_assignments_in_grist(client)
        client.replace_table("Report_WorkAssignments", rows)

        entry = history.snapshot(
            client,
            working,
            source="commit",
            label=f"committed {current_month}",
            note=f"{len(rows)} assignment(s) exported; "
            f"{len(pre_assignments)} pre-assignment(s) merged into Bounds"
            + (" (forced: not solved since the last tweak)" if unsolved else ""),
            only_if_changed=True,
        )

        return {
            "month": str(current_month),
            "num_assignments": len(rows),
            "forced": bool(unsolved and force),
            "iteration": entry["iteration"] if entry else (latest["iteration"] if latest else None),
            "rows": rows,
        }
    finally:
        client.close()


@app.get("/api/export-work-assignments/download")
def download_work_assignments():
    """The same sheet `export-work-assignments` produces, from the same working
    assignment — a download, not a second solve (`_working_hours`)."""
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        current_month = _current_month(plan)
        rows = reports.work_assignment_rows(plan, _working_hours(plan), current_month)
        csv_text = reports.rows_to_csv(rows, ["worker_name", "project_name", "month", "hours_assigned"])
        return Response(
            csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="work_assignments_{current_month}.csv"'},
        )
    finally:
        client.close()


@app.post("/api/run-portfolio-reports")
def run_portfolio_reports():
    """Budget summary (every currently-active project) + staffing balance.

    Reports the working assignment the planner is looking at (`_working_hours`), not a
    fresh solve — a report that disagreed with the `Allocation` table would be worse
    than no report.
    """
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        hours_assigned = _working_hours(plan)
        current_month = _current_month(plan)

        budget_rows: list[dict] = []
        for project in plan.projects:
            if project.pop_start <= current_month <= project.pop_end:
                budget_rows.extend(
                    reports.budget_summary_rows(plan, hours_assigned, project.project_id, current_month)
                )
        client.replace_table("Report_BudgetSummary", budget_rows)

        balance_rows = reports.staffing_balance_rows(plan)
        client.replace_table("Report_StaffingBalance", balance_rows)

        return {
            "month": str(current_month),
            "num_active_projects": sum(1 for p in plan.projects if p.pop_start <= current_month <= p.pop_end),
            "budget_rows": budget_rows,
            "balance_rows": balance_rows,
        }
    finally:
        client.close()


@app.get("/api/run-portfolio-reports/download")
def download_portfolio_reports():
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        hours_assigned = _working_hours(plan)
        current_month = _current_month(plan)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            balance_rows = reports.staffing_balance_rows(plan)
            zf.writestr(
                "staffing_balance.csv",
                reports.rows_to_csv(
                    balance_rows, ["month", "capacity_dollars", "demand_dollars", "balance_dollars", "status"]
                ),
            )
            for project in plan.projects:
                if not (project.pop_start <= current_month <= project.pop_end):
                    continue
                rows = reports.budget_summary_rows(plan, hours_assigned, project.project_id, current_month)
                zf.writestr(
                    f"budget_{project.project_id}.csv",
                    reports.rows_to_csv(
                        rows,
                        [
                            "project_id",
                            "project_name",
                            "month",
                            "planned_spend",
                            "actual_spend",
                            "delta",
                            "cumulative_planned_spend",
                            "cumulative_actual_spend",
                            "planned_funds_remaining",
                            "actual_funds_remaining",
                        ],
                    ),
                )
        return Response(
            buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="portfolio_reports_{current_month}.zip"'},
        )
    finally:
        client.close()


@app.get("/api/reports/variance")
def variance_report(month: str = Query(..., description="YYYY-MM, must already be closed")):
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        target_month = Month.parse(month)
        rows = reports.variance_rows_for_closed_month(plan, target_month)
        client.replace_table("Report_Variance", rows)
        return {"month": month, "rows": rows}
    finally:
        client.close()


@app.post("/api/actuals/upload")
async def upload_actuals(
    file: UploadFile,
    dry_run: bool = Query(True),
    accept_reforecast: bool = Query(False),
    seed: int | None = Query(None),
):
    """Closes the current open month with real (or, absent real data yet,
    synthetic) actuals. CSV columns: `person_id, project_id, hours_actual`.

    `dry_run=true` (the default, for a first "Preview" click) computes and returns
    variance + reforecast proposals without writing anything. Re-submitting the
    same file with `dry_run=false` persists: `hours_actual` into Allocation,
    `closed_through` advances, and — only if `accept_reforecast=true` — the
    proposed target updates are applied, mirroring `advance-month`'s confirm step.
    """
    raw = (await file.read()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    actuals_by_cell: dict[tuple[str, str], float] = {}
    for row in reader:
        try:
            actuals_by_cell[(row["project_id"], row["person_id"])] = float(row["hours_actual"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, f"Bad row in actuals file: {row!r} ({exc})") from exc

    client = _client()
    try:
        plan = load_plan_from_grist(client)
        current_month = _current_month(plan)
        if current_month > plan.horizon_end:
            raise HTTPException(400, "Horizon exhausted — nothing left to close.")

        # Variance is actuals against what was *assigned* — the working assignment the
        # planner committed and the team was given (`_working_hours`), not a fresh
        # solve. Re-solving here would measure the month against a plan nobody ever
        # worked to, which is the one comparison a variance report must not make.
        hours_assigned = _working_hours(plan)
        hours_assigned_this_month = {
            (p, w, m): h for (p, w, m), h in hours_assigned.items() if m == current_month
        }
        if not hours_assigned_this_month:
            raise HTTPException(
                409,
                f"No assignment on record for {current_month} — run a solve (and commit it) "
                f"before closing the month, or there is nothing to measure the actuals against.",
            )
        solve_id_for_month = next(
            (
                a.solve_id
                for a in plan.allocation
                if a.month == current_month and a.solve_id
            ),
            None,
        )

        if actuals_by_cell:
            simulated = [
                AllocationRow(
                    project_id=p,
                    person_id=w,
                    month=current_month,
                    hours_assigned=round(h, 2),
                    hours_actual=round(actuals_by_cell.get((p, w), 0.0), 2),
                    locked=False,
                    solve_id=solve_id_for_month,
                )
                for (p, w, m), h in hours_assigned_this_month.items()
            ]
        else:
            # No real actuals available yet for this month — fall back to the same
            # synthetic simulation the standalone examples use, so the tutorial can
            # be walked through end-to-end before a real timekeeping export exists
            # (`io/synthetic.py`).
            simulated = simulate_actuals_for_month(plan, current_month, hours_assigned, random.Random(seed))

        existing = [a for a in plan.allocation if a.month != current_month]
        plan_with_actuals = plan.model_copy(update={"allocation": existing + simulated, "closed_through": current_month})

        variance_rows = reports.variance_rows_for_closed_month(plan_with_actuals, current_month)

        proposals = []
        for project in plan.projects:
            if not (project.pop_start <= current_month <= project.pop_end):
                continue
            try:
                proposal = propose_reforecast(plan_with_actuals, project.project_id, current_month)
            except ValueError:
                continue
            if proposal.updated_targets:
                proposals.append(proposal)

        if dry_run:
            return {
                "month": str(current_month),
                "variance_rows": variance_rows,
                "proposals": [
                    {
                        "project_id": p.project_id,
                        "variance": p.variance,
                        "updated_targets": {str(m): v for m, v in p.updated_targets.items()},
                    }
                    for p in proposals
                ],
            }

        if accept_reforecast and proposals:
            targets = list(plan_with_actuals.targets)
            for proposal in proposals:
                for m, new_value in proposal.updated_targets.items():
                    idx = next(i for i, t in enumerate(targets) if t.project_id == proposal.project_id and t.month == m)
                    targets[idx] = targets[idx].model_copy(update={"labor_spend_target": new_value})
            final_plan = plan_with_actuals.model_copy(update={"targets": targets})
        else:
            final_plan = plan_with_actuals

        save_plan_to_grist(final_plan, client)
        client.replace_table("Report_Variance", variance_rows)

        return {
            "month": str(current_month),
            "closed": True,
            "reforecast_applied": accept_reforecast and bool(proposals),
            "variance_rows": variance_rows,
        }
    finally:
        client.close()


@app.get("/api/schema/report-tables")
def report_tables():
    """What Report_* tables exist and their columns, for the widget to render
    generic on-screen previews without hardcoding column lists twice."""
    return {t.table_id: [c for c, _ in t.columns] for t in REPORT_TABLES}
