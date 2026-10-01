# 10. Medium Example Tutorial — Planning Several Months at Scale

A second manual test protocol, planning three consecutive months on
`examples/medium_example/`: 50 people, 62 projects across the horizon with 10-12 active
at a time, a 5-year horizon (2027-2031), and a portfolio deliberately calibrated to run
near capacity.

`09-planner-tutorial.md` covers the mechanics of the loop on an 8-person scenario small
enough to check by eye. This one is about what changes when the plan is too big to read:
roughly 4,900 open cells, a solve that takes about ten seconds, and a diff no one is
going to scroll through. Run the small tutorial first — the controls are not re-explained
here.

What this protocol exercises that the small one cannot:

| | Small example | Medium example |
|---|---|---|
| Open cells after a solve | 31 | ~4,900 |
| Capacity | surplus every month | **shortfall in 51 of 60 months** |
| Removing an assignment | absorbed by a colleague | **nobody has slack; the target is missed** |
| Reviewing a diff | read all of it | filter, or read the counts |
| A partial ballpark import | the whole plan | **destroys the rest of the horizon** |

## A determinism warning, up front

Only the steps before the first month-close are reproducible. No real timekeeping export
exists, so closing a month draws **random** synthetic actuals (`io/synthetic.py`), and
every number downstream of that — the reforecast, the next month's solve, every
subsequent iteration — depends on that draw.

So: section 1 through section 5 reproduce exactly. From section 6 onward, expect the same
*shape* (how many cells move, how large the moves are, which months are touched) and
different digits. Each section says which it is.

## Setup

### Regenerate the data first

**The checked-in `examples/medium_example/data/` cannot be used as-is.** Its
`meta.json` carries `closed_through: 2031-12` — the whole horizon already closed, because
those files are the *output* of a full `simulate_full_horizon.py` run. Seeding a document
from them produces a planner with nothing left to plan.

```bash
cd examples/medium_example
python generate_data.py --seed 42
```

That rewrites `data/` with `closed_through: 2027-02`, so **2027-03 is the first month
planned**. It also prints the portfolio's calibration, which is the headline fact about
this scenario:

```
Generated 50 people, 62 projects, 5255 bounds rows.
Staffing balance (pre-solve estimate): $124,231,242 spend capacity vs $124,356,644
intended spend demand over the horizon ($-125,403 net, 51 month(s) with a shortfall,
max |monthly balance| $4,916).
```

Demand exceeds capacity in 51 of 60 months. The margins are thin — a few thousand dollars
against $1.85M a month, under 0.3% — but they are negative, and that is what makes this
scenario behave differently from the small one at every step below.

> `generate_data.py` overwrites checked-in files. That is expected and documented in
> `examples/medium_example/README.md`; `git checkout examples/medium_example/data` puts
> them back.

### Provision

```bash
cd ../../grist_planner
./deploy_planner.sh reset       # a document can only be seeded once
./deploy_planner.sh up --example medium_example
```

Expected opening banner:

```
Planning 2027-03 (horizon 2027-01–2031-12, closed through 2027-02).
No working assignment yet — import a ballpark in step 1, or solve from scratch in step 3.
```

with 50 people and 62 projects. 2027-01 and 2027-02 are already closed as bootstrap
history.

## 1. Solve from scratch — deterministic

This protocol skips the ballpark import at first and solves cold, which is the normal way
to start a horizon that has no plan yet.

On **3. Solve**, leave adherence at **loose**, click **Solve**, and wait. Around 10
seconds of solver time, 13-14 seconds wall clock including the write back to Grist.

Expected: `Feasible. Objective 24.97455, 9.8s, saved as iteration 1.` Changes:
`added: 4918`.

**What this verifies.** Every cell is `added` because there was nothing before. Note the
two scale facts:

- **The widget shows 200 of 4,918 diff rows.** That is deliberate — the full set is in
  `Report_SolveDiff`, which is a Grist table with sorting and filtering. At this size the
  table is the review surface and the widget is the control.
- **Objective 24.97 is the only cold number in this document.** Every later solve starts
  from an existing assignment, and the churn term against it dominates; subsequent
  objectives all land near 1.1. The two are not comparable, which is the point of the
  warning in panel 4.

### Look at the month being planned

Open `Report_SolveDiff` in Grist and filter `month` to `2027-03`.

| | |
|---|---|
| Cells in 2027-03 | 86 |
| Distinct projects | 12 |
| Distinct people | 49 of 50 |

Filter further to `project_id = project_5`:

| person | hours |
|---|---|
| person_20 | 184.00 |
| person_42 | 122.61 |
| person_1 | 105.71 |
| person_10 | 88.19 |
| person_45 | 84.40 |
| person_2 | 63.61 |
| person_19 | 53.79 |
| person_40 | 49.06 |
| person_36 | 27.50 |
| **total** | **778.87** |

Nine people on one project in one month, one of them for 27.5 hours. That fragment is the
subject of the next two sections.

## 2. The scale lesson: no one has slack — deterministic

In a near-capacity portfolio, pulling an assignment out does not move work to a colleague.
There is no colleague with room.

Suppose the 27.5-hour fragment is not worth the context-switch, and person_36 should come
off Project 5 for March entirely. In the `Allocation` table, filter to
`month = 2027-03`, `project_id = project_5`, find person_36's row, set `hours_assigned`
to **0**, and tick `locked`.

Locking a cell at zero pins it **empty** — it tells the solver this person is not on this
project, rather than leaving it free to put them back.

Click **Solve**.

Expected: feasible, saved as iteration 3, with hand-edits saved first as iteration 2.
Changes: **`unchanged: 4918`** — not one cell moved.

Now click **Run Portfolio Reports** and filter `Report_BudgetSummary` to project_5,
2027-03:

| | planned spend |
|---|---|
| Before | 173,585.67 |
| After | **165,640.78** |
| Target | 175,339.03 (tolerance 1,753.39) |

**What this verifies, and it is the central lesson of this scenario.** The 27.5 hours did
not go anywhere. They vanished from the plan, and Project 5 now misses its March spend
target by $9,698 — five and a half times its tolerance.

Check why in the `Allocation` table: filter to `month = 2027-03` and sum hours per person
for the eight people left on Project 5. Every one of them is at exactly their available
hours — 184.0, 184.0, 138.0, 184.0, 184.0, 138.0, 184.0, 184.0 — with **zero slack**. The
solver had nowhere to move the work to. It took the target miss because a soft target
miss is a penalty it can absorb, and capacity is a constraint it cannot.

On the small example the equivalent edit moved the hours to a colleague within the same
solve. The difference is not the solver; it is that this portfolio has no spare capacity
to absorb anything.

**The diff did not show this.** Zero cells changed, so the solve report was silent. The
consequence appeared in the budget summary. At this scale the solve diff answers "what
moved" and the portfolio reports answer "is the plan still any good" — both are needed,
and a quiet diff is not the same as no consequence.

## 3. Undo it — deterministic

The fix is to let the solver have the cell back. On **2. Tweak and lock**, set
`Project` to `project_5`, `Person` to `person_36`, `Month` to `2027-03`, **uncheck "Only
cells with hours"**, and click **Unlock matching**.

The checkbox matters: the cell is pinned at zero hours, so with "only cells with hours"
left on, nothing matches and the unlock silently does nothing.

Expected: `Unlocked 1 cell(s). 0 of 4918 now locked.`

Click **Solve**. Expected: `added: 1, unchanged: 4917`, with person_36 back on Project 5
at exactly 27.50 hours, and the budget summary back to 173,585.67.

**What this verifies.** A lock is a complete override, and removing it restores the
solver's own answer exactly. The round trip is lossless.

## 4. Pin the month before sending it out — deterministic

A useful habit at this scale: once a month's staffing is settled, lock the whole month so
that later solves — which re-optimize all 58 open months every time — cannot disturb the
one already going to the team.

On panel 2, clear the Project and Person boxes, set `Month` to `2027-03`, re-check **Only
cells with hours**, and click **Lock matching**.

Expected: `Locked 86 cell(s). 86 of 4918 now locked.`

Click **Solve** to confirm the locks are satisfiable: `unchanged: 4918`, 86 locked cells
held.

**What this verifies.** A bulk lock across a whole month is checked the same way any lock
is. Had those 86 pinned cells contradicted capacity or a hard target, this solve would
have failed with the conflict named rather than quietly producing something else.

## 5. Commit and close month one — the last deterministic step

Click **Export Work Assignments**. Expected: `Committed 86 assignment(s) for 2027-03.`

Then on panel 8, leave the actuals file empty and click **Confirm & Close Month** with
**Accept reforecast proposal** checked.

Expected: `Closed 2027-03.` and a banner showing:

| | |
|---|---|
| current month | 2027-04 |
| closed through | 2027-03 |
| working cells | **4,832** (was 4,918) |
| locked | **0** (was 86) |

**What this verifies.** The 86 cells moved out of the open horizon into closed history,
taking their locks with them. Locks do not accumulate month over month — each month's
pins stop existing once that month is closed, so there is no slowly-ossifying plan to
clean up later.

> Everything from here on depends on the random actuals just drawn. Expect the shapes
> below, not the digits.

## 6. Month two: what a reforecast actually costs

Click **Solve** for 2027-04.

Expected shape — the captured run gave:

```
iteration 9, 7.3s
adjusted: 181, unchanged: 4651     (3.7% of cells moved)
biggest movers: project_6 / person_41, +4.58h, +3.94h, +3.83h, +3.58h
changes spread across 2027-05 .. 2027-10, 16-18 cells per month
```

**What this verifies, and it is the reason the baseline exists.** Closing a month with
actuals that differ from plan triggers a reforecast, which shifts the remaining months'
targets, which genuinely changes the plan. That change is **3.7% of cells, none moving
more than about 5 hours** — a small correction rippling forward, which is what a planner
can read and sanity-check.

Without a baseline the solver would return a different-but-equally-optimal assignment
across all 4,832 cells, and this report would be unreadable: the reforecast's actual
effect would be indistinguishable from arbitrary churn. On a 31-cell plan that is an
annoyance. On a 4,832-cell plan it makes the tool unusable.

Sort `Report_SolveDiff` by `delta` to find the real movers — the table is already sorted
biggest-first within each status.

Commit and close 2027-04 the same way as month one. Working cells should drop by that
month's cell count again, to around 4,746.

### A labeling detail

The history will show a `tweak` iteration labeled "hand-edited in Grist" immediately
before each solve, even in months where nothing was hand-edited. Closing a month changes
the open horizon, so the pre-solve snapshot differs from the previous iteration and gets
saved. The snapshot is correct and worth having; only the label is imprecise.

## 7. Month three: destroy the plan, then get it back

The most important thing to know about importing a ballpark at this scale.

**An import replaces every open month, wholesale.** A cell the file does not mention ends
up empty. That is the right behavior for the small example, where the ballpark *is* the
plan — and it is a loaded gun against a 4,746-cell horizon.

Try it. Create a one-row file:

```csv
project_id,person_id,month,hours,locked
project_8,person_48,2027-05,120,true
```

Import it (no dry run). Expected: `Imported 1 of 1 row(s) as iteration 10.`

Then look at the banner:

```
Working assignment: 1 cell(s), 120.0h, 1 locked. Iteration 10 (import).
```

**4,745 cells are gone.** Five years of plan replaced by one row.

Now recover: panel 4, **Restore** on the last solve — iteration 9 in the captured run.

Expected:

```
restored_from 9, saved as iteration 11
num_cells 4746, skipped_closed 86
```

The banner returns to 4,746 cells. **What this verifies:**

- **The undo is real, and it is the whole safety net for this operation.** The import was
  appended as iteration 10, so restoring 9 did not delete it; the plan came back intact.
- **`skipped_closed: 86`** — iteration 9 was snapshotted while 2027-04 was still open, so
  it still held that month's 86 open rows. Those are dropped on restore, because the month
  has closed since and its cells now carry actuals. Without that, `Allocation` would hold
  each of those 86 cells twice, once with actuals and once without, silently corrupting
  the baseline and every variance report after it.

### The safe way to round-trip

Use **Download current as CSV** on panel 1, edit *that* file, and re-import it. It
contains every open cell, so wholesale replacement is exactly what is wanted and nothing
is lost. A one-project edit means editing a few rows of a 4,746-row file, not writing a
short file from scratch.

Then finish month three: solve, commit, close.

## 8. The portfolio under strain

Click **Run Portfolio Reports** at any point. On this scenario, unlike the small one:

| | |
|---|---|
| Budget rows | 177 (12 active projects) |
| Staffing balance rows | 60 |
| Months in **shortfall** | **51** |
| Months in surplus | 9 |

A representative shortfall month: capacity $1,847,089 against demand $1,849,490 — short
by $2,401, or 0.13%. The worst in the horizon is 2028-10 at −$4,916.

**What this verifies.** The staffing balance compares spend *demand* from `Targets`
against spend *capacity* valued at each person's direct rate — deliberately not against
solved hours, which are capacity-capped by C3 and so could never exceed capacity by
construction. A shortfall is the signal to find staff outside the pool or move work out of
the month. It is an assessment, not a remediation: nothing acts on it.

This is also the mechanical explanation for section 2. A portfolio running 0.1-0.3% over
capacity most months has no slack anywhere, which is why removing one 27.5-hour assignment
became a $9,698 target miss instead of someone else's extra half-week.

## 9. Things worth looking at in this dataset

Not steps — things the small example has nothing equivalent to.

- **Fiscal-year wrap-rate transitions.** Open `Wrap_Rates`. Rates change every July 1
  (the UFY boundary), five times across the horizon, and `workable_hours` moves with them:

  | From | project wrap | oh wrap | fee wrap | workable hours |
  |---|---|---|---|---|
  | 2027-01 | 2.7480 | 1.6300 | 1.0799 | 152 |
  | 2027-07 | 2.9508 | 1.6719 | 1.0732 | 168 |
  | 2028-07 | 2.9491 | 1.6169 | 1.0981 | 160 |
  | 2029-07 | 2.8830 | 1.6538 | 1.1180 | 168 |
  | 2030-07 | 2.9370 | 1.6615 | 1.1143 | 176 |
  | 2031-07 | 2.9278 | 1.6293 | 1.0842 | 176 |

  The same hour by the same person costs a different amount either side of a July. Cost is
  never stored, always derived, so this needs no migration and no re-solve to reprice.

- **Projects starting and ending mid-horizon.** 62 projects across 5 years with 10-12
  active at a time. Filter `Projects` by `pop_end` to find a month where one ends; its
  final budget summary is where a true-up would show.

- **Three rate structures.** Unlike the small example, this one uses `direct`,
  `oh_charged` and fee-bearing structures, so two projects with identical hours can have
  materially different spend.

- **Adherence at scale.** The levels in `config.ADHERENCE_CHURN_WEIGHTS` were calibrated
  on a two-person fixture where the headcount term is unusually heavy relative to churn.
  Here `norms.count` is in the thousands, so the same weights are relatively stronger.
  Worth confirming directly: import a download of the current plan with a few cells
  changed, then solve at `free` and at `close` and compare how near the result stays. Do
  it on a throwaway document — it is an experiment, not a planning step.

## 10. Running the whole horizon without clicking

Clicking through all 58 open months by hand works and is slow. To see the full cycle hold
up end to end:

```bash
cd examples/medium_example
python simulate_full_horizon.py
```

Solve → simulate actuals → close → reforecast, one month at a time, across the whole
5-year horizon in one command. That script is what put `closed_through: 2031-12` in the
checked-in data, so re-run `generate_data.py --seed 42` before provisioning a document
again.

Use the UI to look closely at a few representative months; use the script to confirm the
horizon never goes infeasible.

## Checks that something is wrong

| Symptom | Likely cause |
|---|---|
| Banner says `Horizon complete` immediately | The document was seeded from the checked-in `data/` with `closed_through: 2031-12`. Re-run `generate_data.py --seed 42`, then `reset` and `up`. |
| Solve takes minutes, not ~10 seconds | Expected on a loaded machine; the time limit is 300s (`DEFAULT_TIME_LIMIT_SECONDS`). A solve that hits the limit still returns the best assignment found. |
| Working cells collapse to a handful | A partial ballpark was imported. Restore the last `solve` iteration (section 7). |
| Unlock matching reports 0 changed | The target cells are pinned at zero hours; uncheck "Only cells with hours". |
| Diff shows thousands of `adjusted` rows with tiny deltas | Should not occur. Movements under 0.05h are reported `unchanged`, since the solver runs to a 1% MIP gap and reaches a slightly different vertex each run. |
| A month's hours look duplicated in `Allocation` | Should not occur. Restoring an iteration from before a month closed drops that month's rows and reports `skipped_closed`. |
| Portfolio reports disagree with `Allocation` | Should not occur — reports read the working assignment rather than re-solving. |

## Shutting down

```bash
./deploy_planner.sh down     # stop containers, keep the document
./deploy_planner.sh reset    # destroy the document and both volumes
```

To go back to the small example afterward, `reset` first — a document can only be seeded
once.
