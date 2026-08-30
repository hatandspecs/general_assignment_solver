# 09. Planner Tutorial

A hands-on walkthrough of a full planning month, using the small starting dataset
in `grist_planner/tutorial_data/` (8 people, 3 projects, a 6-month horizon,
nothing pre-closed). Everything below was run once against a real deployment
while writing this doc — the exact dollar and hour figures are real output, not
invented, **except** the "actual hours" numbers in step 5 onward, which come from
a random simulation (`allocsolver/io/synthetic.py`) and will differ every time you
run it, including if you follow these exact steps yourself.

## 1. Start it up

```bash
cd grist_planner
./deploy_planner.sh up
```

First run: generates `.env` with a random boot key, builds the `planner-api`
image, starts both containers, and provisions a fresh Grist document — schema,
the control-panel widget page, and the tutorial dataset. Takes under a minute.

Open **http://localhost:8484**. The document has one page per table on the left
(`People`, `Projects`, `Bounds`, ... — worth a skim, this is the whole star schema
from `03-data-model.md`) plus a **Planner Control Panel** page holding the widget
this tutorial uses for everything else.

## 2. The starting scenario

Three projects, staggered on purpose:

| Project | PoP | Rate structure | Labor budget | Crew |
|---|---|---|---|---|
| Project Alpha | 2027-01 – 2027-06 (the whole horizon) | direct | $396,000 | 5 people |
| Project Beta | 2027-01 – 2027-04 (ends mid-horizon) | direct | $168,000 | 3 people |
| Project Gamma | 2027-03 – 2027-06 (starts mid-horizon) | oh_charged | $120,000 | 2 people |

Nothing is closed yet (`closed_through` is empty) — you're planning the very
first month, 2027-01.

## 3. Month 1: plan around a manual pre-assignment

Say a planner has already decided Alicia Chen (`person_1`) works 130 hours on
Project Alpha in January — a decision made before running the solver, the way
`unstructured_notes.md` describes most of the workforce being assigned. Load it:

- On the widget's **1. Pre-Assignments** panel, choose
  `grist_planner/tutorial_data/sample_pre_assignment.json` and click **Load
  Pre-Assignment JSON**. (Same shape as any pre-assignment file — you could hand-
  edit the `Pre_Assignments` table instead, and get the identical result.)

Click **2. Run Planning**. This solves with that pre-assignment merged in, but
writes nothing yet:

```
Feasible for 2027-01. Objective: 9.569.
matched: 1, solver_only: 4
```

The diff table shows Alicia's row as `matched` (solved exactly at her requested
130h) and four other assignments the solver picked on its own (`solver_only`) to
cover the rest of both projects' targets — e.g. Ben Torres at 110.32h on Alpha,
Farid Osei at 120h on Beta. Adjust the pre-assignment and re-run as many times as
you like — nothing is saved until the next step.

Click **3. Export Work Assignments**. This is the commit point: the
pre-assignment is merged into `Bounds` permanently, the `Pre_Assignments` table
clears, and this month's sheet is produced:

```
Committed. 5 assignment row(s) for 2027-01.
Alicia Chen    Project Alpha   130.00h
Ben Torres     Project Alpha   110.32h
Carmen Ruiz    Project Alpha   100.00h
Farid Osei     Project Beta    120.00h
Grace Liu      Project Beta    100.57h
```

This is the sheet that would go out to the workforce — hours only, no cost
(`05-interfaces.md`'s workforce export).

## 4. Check the portfolio

Click **4. Run Portfolio Reports**. Two things come back: a budget summary for
every currently-active project (planned spend is populated for the whole PoP;
actual spend is blank everywhere, since nothing's closed yet — `export_budget_
summary`'s "as of" rule), and the staffing balance:

```
2027-01: capacity $236,350 vs demand $108,000 -> surplus $128,350
2027-03: capacity $236,350 vs demand $138,000 -> surplus $98,350   (Gamma has started)
```

This toy scenario is deliberately staffed light relative to its 8-person pool —
unlike `examples/medium_example`'s calibrated-to-near-capacity portfolio, there's
nothing here to tune toward a realistic deficit. The point of this step is the
mechanism (capacity valued at the direct rate, demand from `Targets`, `08-grist-
ui-design.md`), not the specific numbers.

## 5. Close the month

No real timekeeping export exists yet, so leave the file input empty and click
**Preview** under **5. Load Actuals** — this falls back to the same synthetic-
actuals generator the standalone examples use (`io/synthetic.py`), so you can
practice the full cycle before real data exists. A preview from one run looked
like:

```
Alicia Chen   130.00h assigned, 128.05h actual, delta 1.95
Ben Torres    110.32h assigned, 109.29h actual, delta 1.03
...
Proposals: project_alpha variance +4,128; project_beta variance +1,310
```

(Yours will differ — this is randomly generated.) Nothing is saved yet. Check
**Accept reforecast proposal**, then click **Confirm & Close Month**:

```
Closed 2027-01. Reforecast applied: true.
```

The state banner now reads `closed_through: 2027-01`, `current_month: 2027-02` —
Project Alpha and Beta's remaining targets have shifted slightly to absorb
January's variance (`propose_reforecast`, `04-solver-design.md`'s Reforecasting
section).

Use **6. Variance Report**, enter `2027-01`, click **Get Variance Report** to
pull the same five rows back up any time later — this is what a program review
actually wants (`05-interfaces.md`'s Variance sheet).

## 6. Repeat for the rest of the horizon

Months 2 through 6 follow the identical five-button cycle (skip step 3's
pre-assignment upload once you've made all the manual decisions you want to —
it's optional every month, not required). Two months are worth watching for
specifically:

- **2027-03**: Project Gamma's PoP starts. Its two-person crew (Elena Kim, Hassan
  Ali) shows up in Run Planning's diff for the first time, `solver_only` since
  there's no pre-assignment for it — a fresh project coming online mid-horizon.
- **2027-04**: Project Beta's PoP ends. Its final month's budget summary is where
  a real portfolio would show a true-up (the demo's own `examples/medium_example`
  is where that mechanism is actually exercised at scale — this tutorial's simple
  even target split doesn't specifically drive one).

By 2027-06 `horizon_exhausted` in `/api/state` flips to `true` — nothing left to
plan.

## 7. Loading real actuals instead of synthetic ones

Once a real timekeeping export exists, build a CSV with exactly these columns —
`person_id, project_id, hours_actual` — and upload it in step 5's file input
instead of leaving it empty. Everything downstream (variance, reforecast) works
identically; only the source of the numbers changes.

## 8. Shutting down

```bash
./deploy_planner.sh down     # stop containers, keep all data
./deploy_planner.sh reset    # destroy everything, including the Grist document — asks to confirm
```

`down` is what you want between sessions. `reset` is for starting over from
scratch (e.g. to re-run this tutorial from a clean slate) — it deletes the
`.env` file (with its boot key) along with both docker volumes.
