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
| `max_concurrent_projects` | int, nullable | Fragmentation limit. Null means unlimited. |

`active_from` / `active_to` exist so that departures and new hires are modeled rather than handled by deleting rows, which would orphan history.

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

| Column | Type | Notes |
|---|---|---|
| `structure_id` | text, PK | e.g. `cpff`, `tm`, `irad`. |
| `apply_oh` | bool | |
| `apply_fee` | bool | |
| `composition` | enum | `multiplicative` or `additive`. `[OPEN-2]` |

### `rates`

Time-phased, per person. This is the table that makes cost a function of month.

| Column | Type | Notes |
|---|---|---|
| `person_id` | ref -> `people`, PK part | |
| `month` | month, PK part | |
| `annual_salary` | decimal | Reference only; not used in cost math. |
| `project_rate` | decimal | Hourly direct labor rate. |
| `oh_rate` | decimal | Overhead, as a fraction or a rate. `[OPEN-2]` |
| `fee_rate` | decimal | Fee, as a fraction or a rate. `[OPEN-2]` |

**Dense, not sparse.** One row per person per month in the horizon, even when nothing changes. Sparse "effective from" rows require the reader to implement as-of lookup correctly in two places (Grist formula and Python), and as-of lookups are where off-by-one-month bugs live. At 60 people over 60 months this is 3600 rows, which is nothing. Generate the dense table from a sparse editing table if hand entry is tedious.

`annual_salary` is stored because the requirement listed it, but the cost path uses `project_rate`. If `project_rate` is meant to be *derived* from salary rather than entered alongside it, that changes this table. `[OPEN-3]`

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
| `hard_min` | decimal | Solver may never go below when assigned. |
| `soft_min` | decimal | Penalized below. |
| `soft_max` | decimal | Penalized above. |
| `hard_max` | decimal | Solver may never exceed. |
| `eligible` | bool | False means this pair generates no variable at all. |

**Invariant:** `0 <= hard_min <= soft_min <= soft_max <= hard_max`. Enforced at validation, not at write time, so that mid-edit states are permitted in the UI.

`eligible` is a performance lever as much as a modeling one. Marking ineligible pairs cuts variable count directly, and at the design ceiling that is the difference between a solve and a timeout.

The month dimension here is the open question that most affects UI design: with it, `bounds` is roughly `projects x people x months` rows and needs a grid editor; without it, it is one row per pair and fits a simple list. `[OPEN-5]`

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
| Project totals | Sum of the above grouped by project, or project and month |
| Person totals | Same, grouped by person |
| Variance | `assigned_cost - target`, `actual_cost - assigned_cost` |
| Utilization | `sum over projects of hours_assigned / available_hours` |

Storing any of these creates a second source of truth that goes stale on the first retroactive rate correction, and retroactive rate corrections are routine.

## Rate composition

`R[p,w,m]` is the loaded hourly cost of person `w` on project `p` in month `m`. It is a constant at solve time, which is what keeps the model linear.

Multiplicative form, typical of a wrap rate:

```
R = project_rate[w,m]
      x (1 + oh_rate[w,m])   if structure.apply_oh
      x (1 + fee_rate[w,m])  if structure.apply_fee
```

Additive form, if the stored rates are already per-hour dollar amounts per layer:

```
R = project_rate[w,m]
      + oh_rate[w,m]   if structure.apply_oh
      + fee_rate[w,m]  if structure.apply_fee
```

The requirement describes these as "Monthly OH Rate" and "Monthly Fee Rate", which reads as per-hour amounts and points at the additive form, but the naming is equally consistent with stored fractions. This must be settled before any cost number is trusted. `[OPEN-2]`

Implementation lives in exactly one function, `costing.rates.loaded_rate()`, mirrored by one Grist formula, with a test asserting the two agree across the full cross product of structures and a fixture rate table.

## Referential rules

- Deleting a person or project is forbidden while allocation rows reference it. Use `status` and `active_to` instead.
- `bounds` rows for ineligible pairs are kept, not deleted, so that eligibility history survives.
- `allocation` rows are created by the solver for eligible in-PoP cells and are not deleted when eligibility changes. A cell that becomes ineligible gets `hours_assigned = 0`.
