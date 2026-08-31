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
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from allocsolver.config import DEFAULT_MIP_GAP, DEFAULT_TIME_LIMIT_SECONDS, Weights
from allocsolver.io.pre_assignments import apply_pre_assignments
from allocsolver.io.synthetic import simulate_actuals_for_month
from allocsolver.models.allocation import AllocationRow
from allocsolver.models.bounds import Bounds
from allocsolver.models.calendar import Month
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.solve.run import solve

from . import reports
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


def _solve_or_422(plan):
    result = solve(plan, weights=Weights(), time_limit_seconds=DEFAULT_TIME_LIMIT_SECONDS, mip_gap=DEFAULT_MIP_GAP)
    if not result.feasible:
        detail = result.diagnostics.render() if result.diagnostics else "no diagnostics available"
        raise HTTPException(422, f"Infeasible: {detail}")
    return result


def _write_solution_to_allocation(plan, result, client: GristClient) -> None:
    """Persists every open (not-yet-closed) month's solved hours into the
    `Allocation` table — this *is* the editable "solution" a planner iterates
    on: open it in Grist, hand-edit a cell's `hours_assigned`, check its
    `locked` box, and the next Run Planning pins that cell exactly
    (`fixed_cells_and_values`, `solve/build.py`) while re-optimizing everything
    else around it. Closed months' rows (which carry `hours_actual`, fixed by
    C5 regardless of `locked`) are left untouched. A cell's own `locked` flag,
    read from `plan.allocation` *before* this solve, is carried forward as-is —
    this function only ever writes `hours_assigned`, never `locked` itself,
    matching `05-interfaces.md`'s "never written by the solver: ... locked".
    """
    closed_through = plan.closed_through
    locked_by_cell = {(a.project_id, a.person_id, a.month): a.locked for a in plan.allocation}
    closed_rows = [a for a in plan.allocation if closed_through and a.month <= closed_through]

    open_rows = []
    for (p, w, m), hours in result.hours_assigned.items():
        if closed_through and m <= closed_through:
            continue
        locked = locked_by_cell.get((p, w, m), False)
        if hours <= 1e-9 and not locked:
            continue
        open_rows.append(
            AllocationRow(
                project_id=p,
                person_id=w,
                month=m,
                hours_assigned=round(hours, 2),
                hours_actual=None,
                locked=locked,
                solve_id=result.solve_id,
            )
        )

    all_rows = closed_rows + open_rows
    client.replace_table("Allocation", [r.model_dump(mode="json") for r in all_rows])


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
        return {
            "horizon_start": str(plan.horizon_start),
            "horizon_end": str(plan.horizon_end),
            "closed_through": str(plan.closed_through) if plan.closed_through else None,
            "current_month": str(current_month),
            "horizon_exhausted": current_month > plan.horizon_end,
            "num_people": len(plan.people),
            "num_projects": len(plan.projects),
            "num_pre_assignments": len(pre_assignments),
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
def run_planning():
    """Solves with the current Pre_Assignments merged in, and — this is the
    editable "solution" a planner iterates on, not a one-shot preview — writes
    every open month's result into `Allocation` (`_write_solution_to_allocation`).
    Never touches `Bounds`, `Targets`, or `closed_through`: a planner can run
    this as many times as they like, hand-editing `Allocation` rows (tweak
    `hours_assigned`, check `locked` to pin a cell) between runs, before ever
    committing a pre-assignment or closing a month.
    """
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        pre_assignments = load_pre_assignments_from_grist(client)
        working_plan = apply_pre_assignments(plan, pre_assignments)
        result = _solve_or_422(working_plan)

        _write_solution_to_allocation(plan, result, client)

        current_month = _current_month(plan)
        diff_rows = reports.solve_diff_rows(pre_assignments, result.hours_assigned, current_month)
        client.replace_table("Report_SolveDiff", diff_rows)

        counts: dict[str, int] = {}
        for row in diff_rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1

        return {
            "feasible": True,
            "month": str(current_month),
            "objective": result.objective.total if result.objective else None,
            "diff_counts": counts,
            "diff_rows": diff_rows,
        }
    finally:
        client.close()


@app.post("/api/export-work-assignments")
def export_work_assignments():
    """Commits: merges Pre_Assignments into Bounds for real, saves, and clears the
    inbox — this is the "send it to the workforce" moment, so it's the natural
    point the plan gets locked in (matches `apply_pre_assignments`'s "the override
    persists permanently in bounds" contract, `io/pre_assignments.py`). Also
    refreshes `Allocation` from this solve (`_write_solution_to_allocation`), same
    as Run Planning — the two exported/committed views should never disagree.

    Deliberately writes only `Bounds` and `Allocation`, not the whole plan via
    `save_plan_to_grist`: `plan.allocation` here is whatever was loaded *before*
    this solve ran, so blindly saving the whole plan would overwrite `Allocation`
    with stale pre-solve data, undoing the fresh result.
    """
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        pre_assignments = load_pre_assignments_from_grist(client)
        working_plan = apply_pre_assignments(plan, pre_assignments)
        result = _solve_or_422(working_plan)

        client.replace_table("Bounds", [b.model_dump(mode="json") for b in working_plan.bounds])
        _write_solution_to_allocation(plan, result, client)
        clear_pre_assignments_in_grist(client)

        current_month = _current_month(plan)
        rows = reports.work_assignment_rows(working_plan, result.hours_assigned, current_month)
        client.replace_table("Report_WorkAssignments", rows)

        return {"month": str(current_month), "num_assignments": len(rows), "rows": rows}
    finally:
        client.close()


@app.get("/api/export-work-assignments/download")
def download_work_assignments():
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        result = _solve_or_422(plan)
        current_month = _current_month(plan)
        rows = reports.work_assignment_rows(plan, result.hours_assigned, current_month)
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
    """Budget summary (every currently-active project) + staffing balance."""
    client = _client()
    try:
        plan = load_plan_from_grist(client)
        result = _solve_or_422(plan)
        current_month = _current_month(plan)

        budget_rows: list[dict] = []
        for project in plan.projects:
            if project.pop_start <= current_month <= project.pop_end:
                budget_rows.extend(
                    reports.budget_summary_rows(plan, result.hours_assigned, project.project_id, current_month)
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
        result = _solve_or_422(plan)
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
                rows = reports.budget_summary_rows(plan, result.hours_assigned, project.project_id, current_month)
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

        result = _solve_or_422(plan)
        hours_assigned_this_month = {
            (p, w, m): h for (p, w, m), h in result.hours_assigned.items() if m == current_month
        }

        if actuals_by_cell:
            simulated = [
                AllocationRow(
                    project_id=p,
                    person_id=w,
                    month=current_month,
                    hours_assigned=round(h, 2),
                    hours_actual=round(actuals_by_cell.get((p, w), 0.0), 2),
                    locked=False,
                    solve_id=result.solve_id,
                )
                for (p, w, m), h in hours_assigned_this_month.items()
            ]
        else:
            # No real actuals available yet for this month — fall back to the same
            # synthetic simulation the standalone examples use, so the tutorial can
            # be walked through end-to-end before a real timekeeping export exists
            # (`io/synthetic.py`).
            simulated = simulate_actuals_for_month(plan, current_month, result.hours_assigned, random.Random(seed))

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
