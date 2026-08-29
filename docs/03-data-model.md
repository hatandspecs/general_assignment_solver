# 03. Data Model

## Shape

A star schema. One fact table (`allocation`), five dimension and parameter tables, one join table (`bounds`). The two user-facing views described in the original requirement are pivots of the fact table, not stored structures.

```
                people ──┐
                         ├── bounds ──┐
              projects ──┘            │
                                      ├── allocation (fact)
                 rates ──┐            │
              capacity ──┤            │
               targets ──┘────────────┘
```

The "task view" groups `allocation` by project and the "resource view" groups it by person. Neither is a table. Storing both is how the same number ends up with two values.

## Time granularity

The month is the atomic time unit throughout. Represented as `YYYY-MM` text or as the first-of-month date, consistently, everywhere. `[OPEN-1]`

Mixing month representations across tables is the single most likely source of silent join failures in this schema, so the choice is made once and enforced by a Pydantic validator, not by convention.

## Tables

### `people`

| Column | Type | Notes |
|---|---|---|
| `person_id` | text, PK | Stable. Never reuse after departure. |
| `name` | text | Display only. |
| `active_from` | month | First month employable. |
| `active_to` | month, nullable | Last month employable. Null means open-ended. |
| `soft_max_concurrent_projects` | int | Fragmentation limit, penalized above. Default 2. |
| `hard_max_concurrent_projects` | int | Fragmentation limit, never exceeded. Default 4. |

`active_from` / `active_to` exist so that departures and new hires are modeled rather than handled by deleting rows, which would orphan history.

Two fragmentation limits, not one: the source requirement is explicit that a worker should rarely be spread across many projects for a small percentage each, but that this is a preference to be traded off, not an absolute rule — hence a soft ceiling that costs an objective penalty above it, and a hard ceiling that the solver may never cross. Defaults of 2 (soft) and 4 (hard) apply to every worker unless a planner overrides them; this replaces the earlier single, nullable `max_concurrent_projects` field.

### `projects`

| Column | Type | Notes |
|---|---|---|
| `project_id` | text, PK | |
| `name` | text | |
| `pop_start` | month | |
| `pop_end` | month | |
| `rate_structure` | ref -> `rate_structures` | Which cost layers apply. |
| `travel_budget` | decimal | Carried, not optimized. `[OPEN-4]` |
| `odc_budget` | decimal | Carried, not optimized. `[OPEN-4]` |
| `status` | enum | `active`, `pending`, `closed`. Non-active excluded from solve. |

### `rate_structures`

Not in the original requirement, but required to keep `rate_structure` from being a free-text field that the cost composition has to pattern match on.

The notes describe this as a *selection*, not a stack: a project's hours are costed at the project rate, the OH rate, or the fee rate — one of the three, chosen by the project's rate structure — rather than OH and fee layering multiplicatively (or additively) on top of the project rate. Most projects select `project`; OH- or fee-charged work is the exception the notes call "special circumstances."

| Column | Type | Notes |
|---|---|---|
| `structure_id` | text, PK | e.g. `direct`, `oh-charged`, `fee-charged`. |
| `rate_type` | enum | `project`, `oh`, or `fee`. Selects which of the person's three derived rates applies to hours on this project. |

This replaces an earlier draft of this table (`apply_oh` / `apply_fee` / `composition` bools) that assumed a multiplicative or additive stack. That assumption is superseded pending confirmation — see `[OPEN-2]` in `07-open-questions.md`.

### `wrap_rates`

Global reference data, not per person — not present in earlier drafts of this schema, and needed to hold the corporate-wide multipliers the notes describe separately from any individual's salary.

| Column | Type | Notes |
|---|---|---|
| `month` | month, PK | |
| `workable_hours` | decimal | Standard workable hours that month; the divisor for everyone's hourly rate. |
| `project_wrap_rate` | decimal | Multiplier from base hourly rate to `project_rate`. |
| `oh_wrap_rate` | decimal | Multiplier from base hourly rate to `oh_rate`. |
| `fee_wrap_rate` | decimal | Multiplier from base hourly rate to `fee_rate`. |

Stored dense per month like `rates`, but in practice these four values change only at the corporate fiscal year boundary (UFY, starting July 1), not monthly. The entry workflow should be organized around UFY, even though the table itself stays calendar-month grained for join simplicity.

### `rates`

Time-phased, per person. This is the table that makes cost a function of month.

| Column | Type | Notes |
|---|---|---|
| `person_id` | ref -> `people`, PK part | |
| `month` | month, PK part | |
| `annual_salary` | decimal | The real input. Everything else on this row is derived from it. |
| `project_rate` | decimal, derived | `annual_salary / 12 / workable_hours[m] x project_wrap_rate[m]` |
| `oh_rate` | decimal, derived | `annual_salary / 12 / workable_hours[m] x oh_wrap_rate[m]` |
| `fee_rate` | decimal, derived | `annual_salary / 12 / workable_hours[m] x fee_wrap_rate[m]` |

`workable_hours`, `project_wrap_rate`, `oh_wrap_rate`, and `fee_wrap_rate` come from `wrap_rates` above, not from this table.

**Dense, not sparse.** One row per person per month in the horizon, even when nothing changes. Sparse "effective from" rows require the reader to implement as-of lookup correctly in two places (Grist formula and Python), and as-of lookups are where off-by-one-month bugs live. At 60 people over 60 months this is 3600 rows, which is nothing. In practice only `annual_salary` needs hand entry (and rarely changes); the three rate columns and `wrap_rates` can be generated.

This resolves `[OPEN-3]`: `project_rate` (and its OH/fee siblings) are derived from salary, not entered independently — the notes give the formula directly. It is captured here as the candidate resolution pending confirmation in `07-open-questions.md`.

### `capacity`

| Column | Type | Notes |
|---|---|---|
| `person_id` | ref -> `people`, PK part | |
| `month` | month, PK part | |
| `available_hours` | decimal | Net of holiday and planned leave. |

Not present in the original requirement, and load-bearing. If capacity is the only coupling between projects, then this table *is* the coupling. Without it the solver has nothing to contend over and will happily book a person 400 hours in March.

### `bounds`

| Column | Type | Notes |
|---|---|---|
| `project_id` | ref, PK part | |
| `person_id` | ref, PK part | |
| `month` | month, PK part | `[OPEN-5]` |
| `hard_min` | decimal | FTE fraction (0-1+). Solver may never go below when assigned. |
| `soft_min` | decimal | FTE fraction. Penalized below. |
| `soft_max` | decimal | FTE fraction. Penalized above. |
| `hard_max` | decimal | FTE fraction. Solver may never exceed. |
| `eligible` | bool | False means this pair generates no variable at all. |

**Units.** The notes specify these four bounds as FTE percentage (full-time-equivalent fraction), which is how planners actually think about a pre-assignment — "half time," not "84 hours" — not as raw hours. The solver's decision variable is hours, so these are converted at build time against that person's `cap[w,m]` for the month in question; see the FTE-to-hours conversion in `04-solver-design.md`. Captured as the candidate resolution pending confirmation at `[OPEN-7]` in `07-open-questions.md`.

**Invariant:** `0 <= hard_min <= soft_min <= soft_max <= hard_max`. Enforced at validation, not at write time, so that mid-edit states are permitted in the UI.

`eligible` is a performance lever as much as a modeling one. Marking ineligible pairs cuts variable count directly, and at the design ceiling that is the difference between a solve and a timeout.

The month dimension here is the open question that most affects UI design: with it, `bounds` is roughly `projects x people x months` rows and needs a grid editor; without it, it is one row per pair and fits a simple list. `[OPEN-5]`

The notes describe an explicit ramp-up pattern — a project's first month or two staffed only by PIs, co-PIs, and key technical contributors, with the rest of the team phased in afterward, enforced by varying these bounds across months. That is direct evidence for the per-month answer to `[OPEN-5]`; see the updated discussion there.

### `targets`

| Column | Type | Notes |
|---|---|---|
| `project_id` | ref, PK part | |
| `month` | month, PK part | |
| `labor_spend_target` | decimal | |
| `target_tolerance` | decimal, nullable | Band within which deviation is unpenalized. |
| `target_type` | enum | `soft` (penalized) or `hard` (constrained). |

`target_type` matters. A funding cap that legally cannot be exceeded is a different object from a burn target you are trying to hit. Modeling both as soft deviation will eventually produce a plan that overruns a ceiling because the penalty was cheaper than the alternative.

### `allocation` (fact table)

| Column | Type | Notes |
|---|---|---|
| `project_id` | ref, PK part | |
| `person_id` | ref, PK part | |
| `month` | month, PK part | |
| `hours_assigned` | decimal | **Solver-owned.** |
| `hours_actual` | decimal, nullable | **Ingest-owned.** |
| `locked` | bool | Human pin. Solver fixes the variable. |
| `lock_note` | text, nullable | Why. Unexplained locks become permanent. |
| `solve_id` | text | Which solve run last wrote this row. |

Three writers, three disjoint column sets, no overlap. That is what makes concurrent solving and ingest safe without locking.

## Derived, never stored

Every one of these is a formula column or summary table in Grist, and a computed property in Python.

| Derived value | Definition |
|---|---|
| `assigned_cost[p,w,m]` | `hours_assigned x R[p,w,m]` |
| `actual_cost[p,w,m]` | `hours_actual x R[p,w,m]` |
| Project / person totals | Sum of the above, grouped by project or person, optionally also by month |
| Delta hours | `hours_assigned - hours_actual` (task/resource view "Delta hours") |
| Delta cost | `assigned_cost - actual_cost` (task/resource view "Delta cost") |
| Spend variance | `assigned_cost - target`, at the project x month level. Distinct from the assigned-vs-actual delta above: this tracks plan against funding target, not plan against reality. |
| Utilization | `sum over projects of hours_assigned / available_hours` |

Storing any of these creates a second source of truth that goes stale on the first retroactive rate correction, and retroactive rate corrections are routine.

## Rate composition

`R[p,w,m]` is the loaded hourly cost of person `w` on project `p` in month `m`. It is a constant at solve time, which is what keeps the model linear.

The notes describe a base hourly rate multiplied by exactly one wrap rate, selected by the project's rate structure, rather than OH and fee stacking on top of the project rate:

```
base_hourly[w,m] = annual_salary[w,m] / 12 / workable_hours[m]

R[p,w,m] = base_hourly[w,m] x wrap_rate[ rate_structures[p].rate_type, m ]
```

where `wrap_rate[project, m]`, `wrap_rate[oh, m]`, and `wrap_rate[fee, m]` are `project_wrap_rate[m]`, `oh_wrap_rate[m]`, and `fee_wrap_rate[m]` from `wrap_rates`. Most projects have `rate_type = project`; OH- and fee-charged projects are the exception.

This is a change from an earlier draft that assumed OH and fee compose multiplicatively or additively on top of the project rate. The field naming ("Monthly OH Rate", "Monthly Fee Rate") was ambiguous between the two; the notes resolve it as selection instead of stacking. Captured here as the candidate resolution — confirm at `[OPEN-2]`.

Implementation lives in exactly one function, `costing.rates.loaded_rate()`, mirrored by one Grist formula, with a test asserting the two agree across the full cross product of structures and a fixture rate table.

## Referential rules

- Deleting a person or project is forbidden while allocation rows reference it. Use `status` and `active_to` instead.
- `bounds` rows for ineligible pairs are kept, not deleted, so that eligibility history survives.
- `allocation` rows are created by the solver for eligible in-PoP cells and are not deleted when eligibility changes. A cell that becomes ineligible gets `hours_assigned = 0`.
