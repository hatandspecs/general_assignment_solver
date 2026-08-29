# 01. System Overview

## Problem

A program manager runs several concurrent projects staffed from a shared pool of people. Each project has a monthly labor spend target driven by funding profile and period of performance, not by task completion. Each person has finite monthly capacity and a loaded cost that changes over time as salary, overhead, and fee rates change.

The planning task is: allocate hours across (project, person, month) so that each project lands on its monthly spend target, nobody is overbooked, staffing bounds are respected, and the plan does not thrash between revisions.

Doing this by hand is a constraint satisfaction problem with hundreds of interacting cells. A MILP solver already exists and does it well. The gap is representation: MS Project is the current front end, and its API is a poor integration surface for Python tooling.

## What this system is

A thin, purpose-built planning tool with three parts:

1. A structured editing surface where humans maintain constraints and review results.
2. A Python service that pulls constraints, solves, and writes back assignments.
3. An ingest path that reconciles actual charged hours against the plan.

## What this system is not

Naming these explicitly, because each has been the death of a similar tool elsewhere.

- **Not a scheduler.** No predecessors, no durations, no critical path, no leveling engine. Projects are single tasks. If precedence relationships appear in requirements, this is the wrong tool and the design should be revisited from scratch.
- **Not a timekeeping system.** Actual hours originate elsewhere and are imported. The system never becomes the system of record for time charged.
- **Not an accounting system.** It computes planned and actual labor cost for planning purposes. It does not close books, does not handle indirect pools, and its numbers are not authoritative for billing.
- **Not multi-tenant.** Single organization, single planning group, tens of people and tens of projects. Design decisions favor clarity over scale.
- **Not a replacement for the funding document.** PoP dates and budgets are transcribed from contract documents; the system does not manage or version those documents.

## Operational goals

These come from the original requirement and shape the objective in `04-solver-design.md` more than any single constraint does.

- **Steady pulse.** Assignments should be as stable month to month as possible: no sudden drop to zero, no repeated phase-in/phase-out for the same person on the same project. This is a management goal, not just a modeling nicety.
- **Ramp-up.** A project's first month or two is ideally staffed only by PIs, co-PIs, and key technical contributors, with the rest of the team phased in once there is a project plan. In practice this is enforced by planners pre-setting narrower bounds for early months, not by a separate solver feature.
- **Spend out by PoP end, non-linearly if needed.** A linear monthly spend profile is the naive default but rarely what actually happens. The solver should be willing to land on a non-linear spend profile in preference to causing churn or exceeding fragmentation limits. See `[OPEN-9]` for what this implies about target weighting.
- **Fragmentation defaults.** Absent a planner override, every worker gets a soft limit of 2 concurrent projects and a hard limit of 4. Exceeding the soft limit should be rare.
- **NCE as a release valve.** When worker constraints can't be satisfied within a project's period of performance, the system should be able to point at a no-cost extension (lengthening the PoP with no added funding) as a possible fix, not just report infeasibility. See `[OPEN-10]`; not yet built.

## Users and their loops

**Program manager (primary).** Weekly to monthly cadence. Adjusts bounds and targets, triggers a solve, reviews the task view and resource view, investigates variance. Cares about: does the plan hit the target, and who is over capacity.

**Resource owner / line manager.** Reviews the resource view for their people. Cares about: is anyone underutilized, is anyone fragmented across too many projects, is anyone booked past capacity.

**Analyst / the person maintaining this system.** Runs the solver, tunes weights, diagnoses infeasibility, extends the model. Cares about: reproducibility and being able to diff two scenarios.

## Primary workflow

```
1. Actuals for the closed month land via ingest.
2. Solver locks closed months to actuals.
3. PM adjusts forward-looking bounds, capacity, and targets in Grist.
4. PM triggers a solve.
5. Solver returns either an updated allocation or a binding-constraint report.
6. PM reviews task view and resource view, iterates from step 3.
7. Accepted plan is snapshotted to git as the new baseline.
```

The baseline snapshot in step 7 matters more than it looks. The solver's stability objective measures churn against the last accepted baseline, so without a deliberate accept step there is nothing to be stable relative to.

## Scale assumptions

These bound the engineering, and every one of them is deliberately generous relative to the real case.

| Dimension | Expected | Design ceiling |
|---|---|---|
| Projects | 5 to 30 | 100 |
| People | 10 to 60 | 250 |
| Planning horizon | 12 to 24 months | 60 months |
| Allocation cells | roughly 10k | roughly 500k |
| Solve time | seconds | under 5 minutes |
| Concurrent editors | 1 to 3 | 10 |

At the design ceiling the MIP has on the order of 500k continuous variables and a similar count of binaries, which is past what an open source solver handles comfortably. Mitigations, if the ceiling is ever approached: restrict the allowable assignment set so that most (project, person) pairs never generate variables, drop binaries where semi-continuous behavior is not actually needed, and solve rolling windows rather than the full horizon. See `04-solver-design.md`.

## Glossary

| Term | Meaning |
|---|---|
| PoP | Period of performance. The contractual window during which a project may incur cost. |
| ODC | Other direct costs. Non-labor, non-travel direct charges. |
| OH | Overhead. An indirect rate applied to direct labor. |
| Fee | Profit component applied on top of cost, in cost-plus structures. |
| FTE | Full-time-equivalent. Bounds are entered as an FTE fraction (e.g. 0.5 = half time), not hours; the solver converts. |
| UFY | The corporate fiscal year, starting July 1. Wrap rates are set annually at this boundary, even though they are stored per calendar month. |
| NCE | No-cost extension. Lengthening a project's period of performance with no additional funding. |
| Rate structure | Which single rate layer (project, OH, or fee) applies to a given project. |
| Wrap rate | The multiplier from base hourly rate to a specific layer's loaded rate (project, OH, or fee). |
| Loaded cost | Labor cost after applying the applicable rate layer. |
| Hard bound | A constraint the solver may never violate. Infeasibility is the correct outcome if it cannot be met. |
| Soft bound | A preference. Violation is permitted and penalized in the objective. |
| Baseline | The last human-accepted allocation, used as the reference for plan stability. |
| Cell | One (project, person, month) allocation entry. |
| Locked cell | A cell whose hours a human has pinned. The solver treats it as a fixed value. |
| Closed month | A month whose actuals are final. Assignments are fixed to actuals. |
