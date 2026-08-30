#!/usr/bin/env python
"""Drives the advance-month cycle through the entire horizon, in-process.

This is the same logic as `allocsolver advance-month`, run 58 times in a row without
re-invoking the CLI/reloading the environment each time, to prove the simulation loop
holds up over the whole 5-year scenario rather than just a couple of hand-run cycles.

    python simulate_full_horizon.py [--seed 7]

Reforecast proposals are auto-accepted throughout (no interactive prompt) — this is a
proving run, not a demo of the human-in-the-loop review step.
"""

import argparse
import random
import time
from pathlib import Path

from allocsolver.config import Weights
from allocsolver.io.local import load_plan, save_plan
from allocsolver.io.pre_assignments import apply_pre_assignments, clear_pre_assignments, load_pre_assignments
from allocsolver.io.synthetic import simulate_actuals_for_month
from allocsolver.models.plan import Plan
from allocsolver.reforecast.propose import propose_reforecast
from allocsolver.reports.exports import export_month_snapshot
from allocsolver.reports.staffing_balance import export_staffing_balance
from allocsolver.solve.result import SolveResult
from allocsolver.solve.run import solve

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"


def advance_one_month(plan: Plan, rng: random.Random) -> tuple[Plan, dict | None]:
    pre_assignments = load_pre_assignments(DATA_DIR)
    if pre_assignments:
        plan = apply_pre_assignments(plan, pre_assignments)
        clear_pre_assignments(DATA_DIR)

    current_month = plan.closed_through.add(1) if plan.closed_through else plan.horizon_start
    if current_month > plan.horizon_end:
        return plan, None

    t0 = time.monotonic()
    result: SolveResult = solve(plan, weights=Weights())
    elapsed = time.monotonic() - t0

    if not result.feasible:
        return plan, {
            "month": current_month,
            "feasible": False,
            "elapsed": elapsed,
            "diagnostics": result.diagnostics.render() if result.diagnostics else "(no diagnostics)",
        }

    simulated = simulate_actuals_for_month(plan, current_month, result.hours_assigned, rng)
    existing = [a for a in plan.allocation if a.month != current_month]
    plan_with_actuals = plan.model_copy(
        update={"allocation": existing + simulated, "closed_through": current_month}
    )

    # Exported from plan_with_actuals, not plan: the variance sheet needs this
    # month's just-simulated actuals attached, or it would show no rows for it.
    export_month_snapshot(plan_with_actuals, result.hours_assigned, current_month, OUTPUT_DIR / str(current_month))

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

    targets = list(plan_with_actuals.targets)
    for proposal in proposals:
        for m, new_value in proposal.updated_targets.items():
            idx = next(
                i for i, t in enumerate(targets) if t.project_id == proposal.project_id and t.month == m
            )
            targets[idx] = targets[idx].model_copy(update={"labor_spend_target": new_value})
    final_plan = plan_with_actuals.model_copy(update={"targets": targets})

    return final_plan, {
        "month": current_month,
        "feasible": True,
        "elapsed": elapsed,
        "objective_total": result.objective.total if result.objective else None,
        "num_reforecasts": len(proposals),
        "total_variance": sum(p.variance for p in proposals),
        "num_eligible_assignments": sum(1 for h in result.hours_assigned.values() if h > 1e-9),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    plan = load_plan(DATA_DIR)
    print(f"Starting from closed_through={plan.closed_through}, horizon_end={plan.horizon_end}")

    history = []
    while True:
        plan, record = advance_one_month(plan, rng)
        if record is None:
            break
        history.append(record)

        if record["feasible"]:
            print(
                f"{record['month']}: OK  "
                f"({record['elapsed']:.1f}s, obj={record['objective_total']:.2f}, "
                f"{record['num_eligible_assignments']} nonzero assignments, "
                f"{record['num_reforecasts']} reforecasts, "
                f"variance={record['total_variance']:+,.0f})"
            )
        else:
            print(f"{record['month']}: INFEASIBLE ({record['elapsed']:.1f}s)")
            print(record["diagnostics"])
            print("Stopping — an infeasible month needs attention before the loop can continue.")
            break

    save_plan(plan, DATA_DIR)

    feasible_months = [r for r in history if r["feasible"]]
    infeasible_months = [r for r in history if not r["feasible"]]
    print()
    print(f"Processed {len(history)} months: {len(feasible_months)} feasible, {len(infeasible_months)} infeasible.")
    if feasible_months:
        total_time = sum(r["elapsed"] for r in feasible_months)
        avg_time = total_time / len(feasible_months)
        max_time = max(r["elapsed"] for r in feasible_months)
        print(f"Solve time: total {total_time:.1f}s, avg {avg_time:.2f}s/month, max {max_time:.2f}s.")
        total_variance = sum(r["total_variance"] for r in feasible_months)
        print(f"Cumulative reforecast variance absorbed across all months: {total_variance:+,.0f}")

        balance_path = OUTPUT_DIR / "staffing_balance.csv"
        export_staffing_balance(plan, balance_path)
        print(f"Staffing balance (capacity vs. project spend targets) written to {balance_path}")

    print(f"Final state saved to {DATA_DIR}, closed_through={plan.closed_through}.")


if __name__ == "__main__":
    main()
