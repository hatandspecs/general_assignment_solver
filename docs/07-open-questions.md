# 07. Open Questions

Decisions not yet made. Each is referenced inline where it affects a design choice. `[OPEN-1]` through `[OPEN-6]` are ordered by how much rework a late answer costs; `[OPEN-7]` through `[OPEN-10]` were added from `unstructured_notes.md` and appended rather than re-sorted into that ordering.

Each item now ends with a **Decision:** line — answer inline there.

---

## `[OPEN-2]` How do the rate layers compose?

**Blocks:** every cost number in the system. `03-data-model.md`, `04-solver-design.md`.

Stored per person per month are a project rate, an OH rate, and a fee rate. Originally two stacking readings were considered:

- **Additive.** All three are dollars per hour, and `R = project + oh + fee`.
- **Multiplicative.** Project rate is dollars per hour, OH and fee are fractions, and `R = project x (1 + oh) x (1 + fee)`.

**Update from the notes (2026-08-29):** the notes describe something different from either stacking reading — a *selection*, not a sum. Each person has a base hourly rate (`annual_salary / 12 / workable_hours`), and each of `project_rate`, `oh_rate`, `fee_rate` is that base rate times its own wrap rate (`project_wrap_rate`, `oh_wrap_rate`, `fee_wrap_rate` — global, monthly, changing only at the UFY boundary). A project's `rate_structure` then names exactly *one* of the three as the rate that applies to hours on that project; most projects use `project`, and OH/fee are "special circumstances." Nothing stacks. `03-data-model.md` and `04-solver-design.md` have been updated to this model as the candidate resolution.

**Cost of a late answer:** low in code (one function), high in trust. Every number produced before this is settled is wrong by a multiplier, and the error is plausible enough not to be noticed.

**Recommendation:** if the selection reading above matches intent, this is effectively settled — encode `rate_structures.rate_type` and write the parity test (Python `loaded_rate()` vs Grist formula) in the same commit. If instead OH and fee really are meant to stack on top of project rate for some contract types, that is a third variant not yet covered and needs its own description.

**Decision:** _pending — confirm the selection model above matches intent, or describe the actual composition if not._

---

## `[OPEN-5]` Are hour bounds per month or per period of performance?

**Blocks:** `bounds` table shape, editing UI design, variable count. `03-data-model.md`.

- **Per PoP.** One row per (project, person). Small table, simple list editor. Cannot express "half time through Q1, full time after."
- **Per month.** Roughly `projects x people x months` rows. Needs a real grid editor. Expresses ramp-up, ramp-down, and planned leave against a specific project.

**Middle option worth considering:** per-PoP defaults with per-month overrides only where they differ. Keeps the common case to one row and the table sparse, at the cost of an as-of resolution step, which is the same class of bug flagged for the rates table.

**Cost of a late answer:** high. Adding the month dimension later is a schema migration plus a UI rebuild plus a solver change.

**Recommendation:** decide by asking whether any current project has a staffing profile that varies within its PoP. If even one does, go per month now.

**Update from the notes (2026-08-29):** the notes describe ramp-up explicitly as a design goal — a project's first month(s) staffed only by PIs, co-PIs, and key technical contributors, phased in afterward, "likely manually enforced by the hard/soft min/max assignments." That is a staffing profile that varies within the PoP by the recommendation's own test, which points at per-month (or the per-PoP-with-overrides middle option). Not marked resolved here because the operational answer — how often this actually happens across real projects, and whether the overrides-only middle option is preferred over full per-month rows — is still a call for whoever runs the plan.

**Decision:** _pending — per-month, per-PoP, or per-PoP-with-overrides?_

---

## `[OPEN-3]` Is `project_rate` entered, or derived from salary?

**Blocks:** `rates` table, data entry workflow. `03-data-model.md`.

The requirement lists annual salary *and* a monthly project rate on the same timeline. Either the two are maintained independently (and can disagree), or the rate is `salary / productive_hours_per_year` and salary is the real input.

If derived, the divisor is itself a decision: 2080 hours, or net of holiday and leave, or a standard productive-hours factor. That divisor is a policy number and should be a stored, versioned parameter rather than a constant in code.

**Recommendation:** if derived, store the divisor per person per year in a `productive_hours` column and compute `project_rate` as a formula. Keeps one input, makes the assumption visible.

**Update from the notes (2026-08-29):** this is now settled by the notes, which give the formula directly: `annual_salary / 12 / workable_hours_current_month = worker_hourly_rate`, then `worker_hourly_rate x wrap_rate = cost per hour`. `annual_salary` is the real input; `project_rate` (and `oh_rate`, `fee_rate`) are derived. The divisor (`workable_hours`) is exactly the versioned, stored parameter the recommendation called for — it lives in the new `wrap_rates` reference table, one row per month, in `03-data-model.md`. This also ties into `[OPEN-2]`: the wrap rate that gets applied depends on which of the three rate types the project selects.

**Decision:** _pending — confirm this formula and the `wrap_rates` table match intent._

---

## `[OPEN-4]` Do travel and ODC budgets enter the optimization?

**Blocks:** solver scope. `03-data-model.md`, `04-solver-design.md`.

Currently carried as project attributes and displayed, not optimized. The requirement describes the solver as labor-only, so this matches today's behavior.

If total project spend (labor + travel + ODC) is what must hit the monthly target, the spend constraint C4 changes to include non-labor terms, and travel and ODC need month phasing rather than a single budget number. That is a meaningful extension: new tables, new variables if they are decision quantities rather than fixed inputs, and a real question about whether the solver should be *choosing* travel spend.

**Recommendation:** keep labor-only for v1. Add a `non_labor_planned[p,m]` input column now, defaulting to zero, and subtract it from the labor target in C4. That is a one-line change that makes total-spend targeting available later without a schema migration.

**Update from the notes (2026-08-29):** consistent with the recommendation — the notes describe travel and ODC budgets as single values per project (not month-phased) sitting alongside PoP dates and rate structure, with no mention of the solver optimizing against them. This supports keeping v1 labor-only.

**Decision:** _pending — confirm labor-only for v1._

---

## `[OPEN-1]` Month representation

**Blocks:** every join. `03-data-model.md`.

`YYYY-MM` text, or first-of-month date, or an integer month index from an epoch. Text sorts correctly and is readable in Grist. Date joins naturally with anything else date-shaped. Integer index is fastest and least readable.

**Recommendation:** `YYYY-MM` text at the storage boundary, a `Month` value object in Python that parses once and does arithmetic safely. Low stakes as long as it is uniform, and expensive to fix piecemeal if it is not.

**Decision:** _pending._

---

## `[OPEN-6]` Read consistency across tables

**Blocks:** nothing yet. `05-interfaces.md`.

Grist has no cross-table snapshot read. With 1 to 3 editors and a sub-second read burst, a torn read is unlikely but not impossible, and it would produce a plan solved against inconsistent inputs with no visible symptom.

**Recommendation:** defer. Record the action log position before and after the read burst and warn if it moved. Escalate to abort-and-retry only if it is ever observed.

**Decision:** _pending._

---

## `[OPEN-7]` Are hard/soft min/max entered as FTE fraction or hours?

**Blocks:** `bounds` table units, solver conversion logic. `03-data-model.md`, `04-solver-design.md`.

New question, raised by the notes: they describe hard/soft min/max explicitly as "a number of FTE (full time equivalent percentage)," not hours — e.g. a planner enters "half time," not "84 hours." The solver's decision variable `x[p,w,m]` is naturally hours (it has to sum against capacity and multiply by an hourly rate), so somewhere a conversion has to happen.

`03-data-model.md` and `04-solver-design.md` now carry this as the candidate resolution: `bounds` stores FTE fractions, and the solver converts to hours at build time as `bound_h[p,w,m] = bound[p,w,m] * cap[w,m]`, using that person's actual monthly capacity rather than a fixed full-time constant.

**Cost of a late answer:** moderate. It changes the units and validation range of one table and one build-time step, but does not touch the constraint shapes themselves — C1/C2 just gain a multiplication.

**Recommendation:** confirm the FTE reading and the per-month-capacity conversion (rather than, say, a fixed 40-hour week) is what's intended — a person with reduced availability that month should have their FTE bounds scale down with them, not stay pinned to a nominal full week.

**Decision:** _pending._

---

## `[OPEN-8]` What weight (and defaults) for the fragmentation penalty?

**Blocks:** `04-solver-design.md` objective tuning, `03-data-model.md` people defaults.

The notes give concrete defaults — soft max 2 concurrent projects, hard max 4, for every worker unless overridden — and say the solver "should rarely" violate the soft max. That fixes the defaults but not the objective weight `W_frag` that enforces "rarely." `04-solver-design.md` currently suggests `frag: 8`, placed above `churn: 5` because "rarely" reads stronger than general churn-avoidance, but that is a guess, not a value from the notes.

**Cost of a late answer:** low. It is one number in a weights file, tunable after the fact by rerunning historical scenarios.

**Recommendation:** start at the suggested value, then tune against a real planning period: if the solver fragments people more than planners consider acceptable, raise it before touching anything else.

**Decision:** _pending._

---

## `[OPEN-9]` Should the solver redistribute spend across months, or only hit the entered target?

**Blocks:** `04-solver-design.md` objective weighting (target vs. churn/fragmentation), how `targets` is meant to be populated and re-populated.

The notes state a preference for non-linear spend profiles over churn or fragmentation violations. `targets` already supports an arbitrary non-linear monthly value, entered by a PM, so one reading is: this is already handled, a PM who wants a non-linear profile just enters one. But the current objective weights target deviation at 100 versus churn at 5 and the (proposed) fragmentation weight at 8 — heavily dominant — which means the solver will always work hard to hit whatever is in `targets` for a given month even if a small reshuffle of *which month* the spend lands in would avoid a churn or fragmentation penalty entirely.

The alternative reading: the solver itself should have license to treat a soft target as an aim point it can miss in one month and make up in an adjacent one, if doing so avoids churn or a fragmentation violation — i.e., target deviation should not dominate churn/fragmentation as heavily as the current weights imply, at least for soft targets.

**Cost of a late answer:** moderate. It is a weighting change, not a schema change, but it changes what the solver's output means well enough that program reviews built around "the plan hits target X" need to be re-explained if it turns out targets are meant as flexible aim points.

**Recommendation:** clarify whether `targets.target_type = soft` already means "PM-adjustable aim point, solver may deviate for churn/fragmentation reasons," in which case lower `W_target` relative to `W_churn`/`W_frag`, or whether the PM's monthly number is meant to be hit as entered and non-linearity is only ever a PM decision made before solving, in which case the current dominant weighting is correct as is.

**Decision:** _pending._

---

## `[OPEN-10]` Scope of the NCE (no-cost extension) recommendation

**Blocks:** `04-solver-design.md` diagnostics scope, whether this is v1 or later roadmap.

The notes ask for the solver to recommend a no-cost extension when worker constraints can't otherwise be met. `04-solver-design.md` sketches a candidate mechanic — re-run the elastic diagnostic with the binding project's `pop_end` pushed out and report whether that clears the binding set — but this is genuinely new scope, not a refinement of something already designed, and several things about it are undecided:

- Is this v1, or a later addition once the core solve/diagnose loop is proven?
- Is it purely diagnostic (report "extending by N months would clear this"), or should the tool ever act on it (e.g. write a proposed new `pop_end` for a human to accept)?
- How is "the binding driver is a PoP-end capacity crunch" distinguished from other kinds of infeasibility in the binding-constraint report?

**Cost of a late answer:** low to defer, since it can be added as a diagnostics-only feature after the core loop works without touching the data model. High if it turns out to require new decision variables (e.g. the solver choosing an extension length itself), which would be a real modeling addition.

**Recommendation:** treat as v1.1 — ship the core solve/diagnose loop first, add NCE recommendation as a diagnostics extension once there is real infeasibility data to test it against.

**Decision:** _pending — in scope for v1, or deferred?_

---

## Questions not yet asked of the operator

These need answers from whoever runs the plan, not from the design:

1. Where do actuals come from, and in what format? This determines the entire ingest mapping layer and is the single biggest unknown in `05-interfaces.md`. Still open — the notes describe this only as "another TBD automated process."
2. Is any monthly target a hard funding ceiling rather than an aim point? If yes, `target_type` is used from day one. Still open — the notes describe `labor_spend_target` only as a target, not distinguishing a hard ceiling.
3. Does uncovered capacity cost anything? Determines whether `W_idle` is meaningful or should be zero. Still open.
4. ~~Is there a fragmentation limit in practice, or is it acceptable for one person to be split across six projects in a month?~~ **Answered by the notes:** yes, defaults are soft max 2 / hard max 4 projects per person. See `[OPEN-8]` for the remaining weight-tuning question.
5. How often does the plan get re-solved, and by whom? Weekly by one PM implies different tooling from daily by three. Still open.
6. Who needs to see this outside the planning group, and in what format? Determines whether the MSPDI export is real or theoretical. Still open, though the notes confirm the editing surface itself should be "some kind of linked spreadsheet or workbook, but ideally not Excel itself" — consistent with the Grist choice already made in `02-architecture.md`.
