# General Assignment Solver

A MILP-driven labor allocation and spend-planning tool: given a pool of people, a set
of concurrent projects each with a monthly labor spend target, and per-person-per-project
hour bounds, it solves for an hours assignment that hits spend targets, respects
capacity and fragmentation limits, and stays stable from one plan revision to the next.

Full design rationale lives in `docs/` — start at `docs/README.md`. This README covers
getting the code running.

## Setup

```bash
conda env create -f environment.yml
conda activate general_assignment_solver
```

This creates a conda environment named `general_assignment_solver`, installs Python
3.11, and pip-installs everything the package needs — including OR-Tools (the MILP
solver, via its `linear_solver`/SCIP backend), Pydantic, Polars, Typer, and Rich — plus
`allocsolver` itself in editable mode, so code changes take effect immediately.

To rebuild the environment from scratch later (e.g. after a dependency change):

```bash
conda env remove -n general_assignment_solver
conda env create -f environment.yml
```

## Try it: the small example

The quickest way to see the tool working end to end — 8 people, 3 staggered
projects, a 6-month horizon, readable in a few minutes:

```bash
cd examples/small_example
python generate_data.py   # writes data/*.json (already checked in; re-run to reset)
python run_example.py     # loads it, solves it, shows the views, runs a reforecast demo, exports
```

See `examples/small_example/README.md`.

## Try it: the medium example

A bigger, longer-running scenario in `examples/medium_example/` — 50 people,
~10-12 concurrent projects, a 5-year horizon spanning several fiscal-year rate
transitions:

```bash
cd examples/medium_example
python generate_data.py --seed 42   # writes data/*.json (already checked in; re-run for a fresh draw)
python run_example.py               # loads it, solves it, shows the views, runs a reforecast demo, exports
```

See `examples/medium_example/README.md` for a full walkthrough, including a tutorial
aimed at the planner who'd actually use this tool (not just the person building it).

## Try it: the live Grist planner UI

A real, self-hosted Grist document backed by a small FastAPI service, with a
control-panel widget embedded right in the doc. The loop it drives: import a hand-built
ballpark assignment, tweak and lock cells, press Solve, repeat, and restore an earlier
iteration whenever a round goes badly — plus export work assignments, portfolio reports,
load actuals and variance reports, all as buttons rather than CLI invocations:

```bash
cd grist_planner
./deploy_planner.sh up
```

Opens Grist at `http://localhost:8484` with the small example already loaded
(pass `--example medium_example` to load the bigger scenario instead). See
`docs/09-planner-tutorial.md` for a step-by-step manual test protocol,
`docs/10-medium-example-tutorial.md` for planning several months at scale, and
`docs/08-grist-ui-design.md` for how it's built.

## Running the tests

```bash
pytest
```

## Package layout

See `docs/06-code-structure-and-dependencies.md` for the full rationale. Briefly:

```
allocsolver/
    models/       Pydantic schema — the star schema in docs/03-data-model.md
    costing/       Rate composition and eligibility masks
    solve/         The MILP itself (OR-Tools/SCIP), elastic-relaxation diagnostics,
                    rolling-horizon support
    reforecast/    Target-vs-actual variance and the proportional redistribution
                    that follows a closed month
    reports/       Task/resource views and the three confirmed export formats
    io/            Local JSON file I/O (the current stand-in for a live Grist doc),
                    synthetic-actuals simulation, the range-shaped pre-assignment inbox,
                    and the hours-shaped working assignment (import/audit/baseline)
    cli.py         `allocsolver validate|solve|advance-month` — the last one is a
                    simulated real-time engine: solve, simulate that month's
                    actuals, close it, reforecast, one month per invocation

tests/             pytest suite covering the model invariants in
                    docs/04-solver-design.md, "Testing the model"
examples/          Runnable, self-contained scenarios
docs/              The design documentation this was built from
```

## What's implemented vs. what's still design-only

Implemented: the full data model and its validation, cost composition (resolved
selection-not-stacking rate model), the MILP (semi-continuous assignment, soft
bounds, capacity, spend targets, fragmentation tiers, churn minimization),
elastic-relaxation infeasibility diagnostics, the reforecast mechanism, task/resource
views, the three confirmed exports (workforce sheet, variance sheet, budget
summary — measured against each project's fixed `labor_budget`), two manual input
shapes — a range-shaped pre-assignment inbox (`pre_assignments.json`, validated and
merged into `bounds` before each solve) and an hours-shaped working assignment
(`io/working_assignment.py`: a partial, possibly rule-breaking ballpark, imported from
CSV or JSON, audited rather than rejected, and fed to the solver as its starting point
via the churn baseline) — lock-conflict diagnostics that name why a set of pins cannot
hold (`solve/locks.py`), a staffing-balance assessment (spend capacity vs. spend demand,
in dollars, surfaced as a monthly surplus/shortfall — an assessment, not an
auto-remediation), and a simulated real-time engine that drives the whole monthly
solve/actuals/close/reforecast cycle (`allocsolver advance-month`, proven feasible
across all 58 months of the medium
example's full 5-year horizon).

Also implemented: a live, self-hosted Grist document (`grist_planner/`, `docs/08-
grist-ui-design.md`) — every input table, a `GristClient` REST wrapper, and a
control-panel widget wiring the import/tweak/solve/restore loop plus
pre-assignments/export/reports/close-month to buttons instead of CLI invocations,
deployed with `./grist_planner/deploy_planner.sh up`. Includes an append-only iteration
history of the working assignment (`Assignment_History`), so any earlier state can be
restored.

Still design-only (documented in `docs/05-interfaces.md` but not built): the real
timekeeping-ingest pipeline (actuals are still synthetic, `io/synthetic.py`, or a
hand-built CSV — there's no mapping-table/reconciliation pipeline against a real
export yet), and the snapshot repo with `diff`/`accept` as CLI verbs. The Grist planner's
iteration history covers the interactive "go back one step" need but not the audit one:
it versions the assignment, not the full inputs, so it can't replay an old solve against
a different code version.
