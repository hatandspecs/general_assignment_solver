# Small Example

The smallest scenario in the repo: 8 people, 3 staggered projects, a 6-month
horizon, with the first month already closed as bootstrap history so the
reforecast mechanism has something to show immediately. Meant to be read end to
end in a few minutes — contrast with `examples/medium_example`'s 50-person,
5-year scenario.

This is also the dataset `grist_planner/`'s live Grist deployment seeds by
default (`docs/09-planner-tutorial.md` walks through it there); everything here
works standalone too, exactly like `examples/medium_example`.

Like `examples/medium_example`, this is entirely local-file based —
`allocsolver/io/local.py` is the practical stand-in: one JSON file per table in
`data/`, mirroring exactly what would be one Grist table each.

## Setup

From the repository root:

```bash
conda env create -f environment.yml
conda activate general_assignment_solver
```

See the repository root README for more on the environment.

## Running it

```bash
cd examples/small_example

# 1. Generate the scenario (deterministic — every number is a specific line in
#    generate_data.py, not a random draw; re-run any time to reset to a fresh start).
python generate_data.py

# 2. Solve it and produce reports.
python run_example.py

# 3. Or: drive the whole remaining horizon end to end, one month at a time.
python simulate_full_horizon.py
```

`run_example.py` walks through, in order: loading the plan, solving the full
horizon, rendering the task view and resource view, a quick note on Project
Gamma's mid-horizon start, a reforecast demo using the one closed month's
actuals, and CSV exports to `output/`.

`simulate_full_horizon.py` is the same solve → simulate actuals → close →
reforecast logic as `allocsolver advance-month`, run once per remaining month
in a row — proves the cycle holds up across the whole horizon, and leaves
`data/` fully closed out afterward (re-run `generate_data.py` to reset it to
its fresh starting state).

## Files

```
generate_data.py             writes data/*.json (checked in; re-run to reset)
run_example.py                 load -> solve -> views -> exports -> reforecast demo
simulate_full_horizon.py        drives the whole remaining horizon, one month at a time
sample_pre_assignment.json       a manual pre-assignment, used by docs/09-planner-tutorial.md
data/                          the star-schema JSON files (allocsolver/io/local.py's layout)
output/                        CSV exports (gitignored — regenerate any time)
```
