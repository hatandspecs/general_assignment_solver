# Medium Example

A synthetic, medium-sized scenario for the labor allocation planner: 50 people, roughly
10-12 concurrently active projects at any given time (chained into longer programs of
back-to-back contracts), spanning 5 calendar years (2027-2031) so several corporate
fiscal year (UFY) wrap-rate transitions are visible. Generated from the spec in
`unstructured_notes_medium_example.md`.

This example is entirely local-file based — there is no live Grist document involved.
`allocsolver/io/local.py` is the practical stand-in: one JSON file per table in `data/`,
mirroring exactly what would be one Grist table each.

## Setup

From the repository root:

```bash
conda env create -f environment.yml
conda activate general_assignment_solver
```

This installs `allocsolver` itself (editable) along with OR-Tools, Pydantic, Polars,
Typer, Rich, and everything else needed. See the repository root README for more on
the environment.

## Running it

```bash
cd examples/medium_example

# 1. Generate the scenario (only needs to be re-run if you want a fresh random draw,
#    or pass --seed for a specific one; the checked-in data/ already has a run's output).
python generate_data.py --seed 42

# 2. Solve it and produce reports.
python run_example.py
```

`run_example.py` walks through, in order: loading the plan, solving the full 5-year
horizon, rendering a sample of the task view and resource view, pointing out the
ramp-up pattern in the generated data, running the reforecast mechanism against the
closed months' (synthetic) actuals, and writing the three confirmed export formats
to `output/`.

A full solve over this scenario (3,000+ eligible cells, 5-year horizon) takes on the
order of 5-10 seconds on a normal laptop.

### Command-line interface

The same solve is available through `allocsolver`'s CLI, which is what a real
deployment would actually run:

```bash
allocsolver validate --data-dir data
allocsolver solve --data-dir data --export-dir output
```

`solve` prints the objective breakdown and renders every project's and person's task
view / resource view (all of them — for a scan of everything rather than the curated
sample `run_example.py` shows, redirect this to a file or a pager).

## What's real here, and what's aspirational

This build implements: the full data model, cost composition (`costing/`), the MILP
itself via OR-Tools/SCIP (`solve/`), the elastic-relaxation infeasibility diagnostic,
the reforecast mechanism, the task/resource views, and the three confirmed exports
(workforce sheet, variance sheet, budget summary sheet).

Not yet built, and not needed for this example: a live Grist document and its REST
client, the real timekeeping-system ingest pipeline (this example's "actuals" are
synthetic, generated directly rather than imported from a CSV), snapshot/diff/accept
as CLI commands, and the legacy MSPDI export. These are all still described in
`../../docs/05-interfaces.md` as the target design — this example demonstrates the
solver and reporting core, not the full integration surface.

## A tutorial, for a planner

This section is written for the person who will actually use this tool to plan work
assignments, not for the person building it. It assumes you have a data directory
like this example's `data/` (in a real deployment, this would live in Grist).

### The mental model

You are looking at a grid: *people x projects x months*. For every cell where a
person could conceivably work on a project in a given month, you (or a prior planner)
set four numbers, in **hours**:

- **Hard min** — the least this person may work on this project, if they're on it at
  all. Usually 0.
- **Soft min** — the least you'd *like* them to work on it. The solver can go below
  this, but it costs a penalty in the objective — it will only do so when something
  else (a spend target, someone else's capacity) makes that necessary.
- **Soft max** — the most you'd like them to work on it. Same deal: crossable, but
  penalized.
- **Hard max** — the most they may *ever* work on this project this month. Never
  crossed.

If you don't want someone eligible for a project at all in a given month, you simply
don't create a row for that (project, person, month) — no row means ineligible, and
the solver never considers it.

The solver's job, every time you run it, is to pick an actual number of hours for
every eligible cell that:

1. Comes as close as it reasonably can to each project's monthly spend target,
2. Respects every hard bound and nobody's total capacity that month,
3. Tries not to violate soft bounds or leave people fragmented across too many
   projects (default: rarely more than 2, never more than 4), and
4. Changes as little as possible from whatever the last accepted plan was.

Priority (1) dominates the others by design — the tool's whole purpose is hitting the
spend target — but (3) and (4) matter enough that the solver won't casually blow past
them for a rounding error's worth of spend accuracy.

### Reading the task view

Run `allocsolver solve --data-dir data` (or look at `run_example.py`'s console output)
and you'll see, for each project, one row per person assigned to it that month: their
four bounds, how many hours the solver assigned them, what that costs, and — once
actuals exist for a closed month — how that compares to what they actually billed.

The **ramp-up** you'll notice in `project_1`'s first month versus its second: only a
handful of people show up in month one (the PIs and key technical staff), and the
full crew appears from month two onward. That's not a solver feature — it's you (or
whoever set up the input bounds) deliberately not making the rest of the crew eligible
until month two. The solver just fills in whatever bounds it's given.

### Reading the resource view

The same numbers, pivoted around a person instead of a project — everything one
person is doing this month, across all their projects, plus their **%FTE** figure:
what fraction of their available hours this month is actually assigned. This is a
reporting check, not something you enter — you enter hours, the tool tells you what
percentage that works out to.

### When a month closes

Once actuals land for a month (in this example, synthetically, for the first two
months), that month's hours get fixed to whatever was actually billed — the "planned
vs. actual" delta for a closed month is trivially zero by design, because the record
gets corrected to match reality once it's final. The interesting variance for a
closed month isn't "assigned vs. actual" (always zero once closed) — it's **target
vs. actual**, which is what reforecasting looks at.

### Reforecasting

Once a month closes, the tool computes the gap between that project's target for the
month and what was actually spent, and proposes spreading that gap across the
project's *remaining* open months (proportional to their existing target sizes), so
the total still lands close to the funded amount by the project's end. This is always
a *proposal* for you to review — nothing gets written to the targets until you accept
it. Step 5 of `run_example.py`'s output shows this for a few sample projects.

Whether to also re-solve the *current, already-distributed* month because of a big
miss (a "hot fix") is left entirely to your judgment — the tool doesn't try to guess
when a variance is "big enough."

### The exports

Three things come out of `output/` after a solve:

- **`assignments_YYYY-MM.csv`** — what you send to the workforce. Worker, project,
  hours for next month. Nothing else — no cost, no rate, no salary ever appears here.
- **`variance.csv`** — for you: worker, project, month, hours assigned, hours
  actually billed, and the delta, for every cell where actuals exist.
- **`budget_<project_id>.csv`** — one per project: a metadata block (PoP dates,
  budget expended/remaining, planned and actual) plus a month-by-month matrix of
  planned spend, actual spend, and delta.

### If a solve comes back infeasible

You'll see a report naming exactly which constraints couldn't all be satisfied
simultaneously, and by how much — e.g. a specific person over capacity in a specific
month, or a hard minimum that couldn't be met. The fix is almost always to relax one
of those bounds, or move someone's assignment elsewhere, then re-solve. The tool never
just tells you "infeasible" with no further information.
