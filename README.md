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

## Try it: the medium example

The fastest way to see the tool working end to end is the bundled synthetic scenario
in `examples/medium_example/` — 50 people, ~10-12 concurrent projects, a 5-year
horizon spanning several fiscal-year rate transitions:

```bash
cd examples/medium_example
python generate_data.py   # writes data/*.json (already checked in; re-run for a fresh draw)
python run_example.py     # loads it, solves it, shows the views, runs a reforecast demo, exports
```

See `examples/medium_example/README.md` for a full walkthrough, including a tutorial
aimed at the planner who'd actually use this tool (not just the person building it).

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
    io/            Local JSON file I/O (the current stand-in for a live Grist doc)
    cli.py         `allocsolver validate|solve`

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
views, and the three confirmed exports (workforce sheet, variance sheet, budget
summary).

Still design-only (documented in `docs/05-interfaces.md` but not built): a live Grist
document and its REST client, the real timekeeping-ingest pipeline (this build's
"actuals" are synthetic), snapshot/diff/accept as CLI verbs, and the legacy MSPDI
export.
