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

**My recommendation:** adopt the selection model literally, as the notes describe it. The notes' own wording — "most workers charge projects which use the project wrap rate, but some may charge projects that utilize the overhead or fee wrap rates in special circumstances" — reads naturally as mutually exclusive selection, not a stack. It also matches a real pattern in cost-plus government contracting, where certain efforts (IR&D, B&P) are charged against the overhead or fee pool rather than direct labor, rather than every hour being loaded with both. Settle it now: every downstream cost figure depends on it, and the cost of being wrong is invisible until a variance review.

**Decision:**
- [ ] Accept
- [ ] Reject — alternative: 

**Clarification**
each wrap rate, project, oh, fee, is complete. while it is the case that a project wrap rate contains fee and oh and other percentage components to it, this will be all represented as a single number in the system called Project Rate or project wrap rate, or some such name.  a project that a worker is assigned to will use one of these rates, most often the project wrap rate.  There are internally funded efforts like management time  or interal R&D or business development that may use the OH or Fee wrap rate instead.

---

## `[OPEN-5]` Are hour bounds per month or per period of performance?

**Blocks:** `bounds` table shape, editing UI design, variable count. `03-data-model.md`.

- **Per PoP.** One row per (project, person). Small table, simple list editor. Cannot express "half time through Q1, full time after."
- **Per month.** Roughly `projects x people x months` rows. Needs a real grid editor. Expresses ramp-up, ramp-down, and planned leave against a specific project.

**Middle option worth considering:** per-PoP defaults with per-month overrides only where they differ. Keeps the common case to one row and the table sparse, at the cost of an as-of resolution step, which is the same class of bug flagged for the rates table.

**Cost of a late answer:** high. Adding the month dimension later is a schema migration plus a UI rebuild plus a solver change.

**Recommendation:** decide by asking whether any current project has a staffing profile that varies within its PoP. If even one does, go per month now.

**Update from the notes (2026-08-29):** the notes describe ramp-up explicitly as a design goal — a project's first month(s) staffed only by PIs, co-PIs, and key technical contributors, phased in afterward, "likely manually enforced by the hard/soft min/max assignments." That is a staffing profile that varies within the PoP by the recommendation's own test, which points at per-month (or the per-PoP-with-overrides middle option). Not marked resolved here because the operational answer — how often this actually happens across real projects, and whether the overrides-only middle option is preferred over full per-month rows — is still a call for whoever runs the plan.

**My recommendation:** go per-month, not per-PoP and not the sparse-with-overrides middle option. Ramp-up is now a confirmed requirement, not a hypothetical, which settles the original test in the recommendation above. Between per-month and the overrides middle-ground: the overrides approach needs an as-of resolution step implemented in two places (Grist formula and Python) — exactly the bug class this schema already went out of its way to avoid by making `rates` dense rather than sparse. `bounds` is already restricted to `eligible` pairs, so the row-count blowup the middle option was hedging against is smaller than it looks. Take the row-count cost once, in exchange for one fewer place an as-of bug can hide.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

**Discussion**
I do want the bounds to be per month because plan review and replanning happens on a monthly basis based on project needs.  Adjustments are always expected to be necessary.

---

## `[OPEN-3]` Is `project_rate` entered, or derived from salary?

**Blocks:** `rates` table, data entry workflow. `03-data-model.md`.

The requirement lists annual salary *and* a monthly project rate on the same timeline. Either the two are maintained independently (and can disagree), or the rate is `salary / productive_hours_per_year` and salary is the real input.

If derived, the divisor is itself a decision: 2080 hours, or net of holiday and leave, or a standard productive-hours factor. That divisor is a policy number and should be a stored, versioned parameter rather than a constant in code.

**Recommendation:** if derived, store the divisor per person per year in a `productive_hours` column and compute `project_rate` as a formula. Keeps one input, makes the assumption visible.

**Update from the notes (2026-08-29):** this is now settled by the notes, which give the formula directly: `annual_salary / 12 / workable_hours_current_month = worker_hourly_rate`, then `worker_hourly_rate x wrap_rate = cost per hour`. `annual_salary` is the real input; `project_rate` (and `oh_rate`, `fee_rate`) are derived. The divisor (`workable_hours`) is exactly the versioned, stored parameter the recommendation called for — it lives in the new `wrap_rates` reference table, one row per month, in `03-data-model.md`. This also ties into `[OPEN-2]`: the wrap rate that gets applied depends on which of the three rate types the project selects.

**My recommendation:** adopt the formula exactly as the notes state it. Storing `project_rate` as an independently-entered field alongside `annual_salary` would let the two drift apart with no error signal — precisely the kind of silent divergence the "one implementation, cross-checked" principle elsewhere in this schema (rate composition, capacity) exists to prevent. Salary is the one input; everything else is computed.

**Decision:**
- [ ] Accept
- [ X] Reject — alternative: 

**discussion**
this is close to what I want, but make sure you are tracking that the effecive hourly rate of an employee varies by the month because different months have different workable hours.

`annual_salary / 12 / workable_hours_current_month = worker_hourly_rate_current_month`, then `worker_hourly_rate_current_month x wrap_rate = cost per hour for the current month`

wrap_rate is not derived. it is specified by the rate-structure to use for the particular project and it will be in most cases the project_rate rather than the OH rate or the fee rate.  internally funded projects like managemnet time, business development, or internal research and development will be funded by either fee or oh nad then one of those rates will apply instead of the fproject rate.

---

## `[OPEN-4]` Do travel and ODC budgets enter the optimization?

**Blocks:** solver scope. `03-data-model.md`, `04-solver-design.md`.

Currently carried as project attributes and displayed, not optimized. The requirement describes the solver as labor-only, so this matches today's behavior.

If total project spend (labor + travel + ODC) is what must hit the monthly target, the spend constraint C4 changes to include non-labor terms, and travel and ODC need month phasing rather than a single budget number. That is a meaningful extension: new tables, new variables if they are decision quantities rather than fixed inputs, and a real question about whether the solver should be *choosing* travel spend.

**Recommendation:** keep labor-only for v1. Add a `non_labor_planned[p,m]` input column now, defaulting to zero, and subtract it from the labor target in C4. That is a one-line change that makes total-spend targeting available later without a schema migration.

**Update from the notes (2026-08-29):** consistent with the recommendation — the notes describe travel and ODC budgets as single values per project (not month-phased) sitting alongside PoP dates and rate structure, with no mention of the solver optimizing against them. This supports keeping v1 labor-only.

**My recommendation:** keep v1 labor-only, add `non_labor_planned[p,m]` defaulting to zero now. The notes describe travel/ODC as carried, single-value attributes with no signal that the solver should choose them, matching the current design exactly. The zero-default column is cheap insurance: if total-spend targeting ever becomes a real requirement, it is a one-line change to C4 instead of a schema migration.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

**discussion**
travel and ODC budgets are only for tracking, they are not part of the optimization.

---

## `[OPEN-1]` Month representation

**Blocks:** every join. `03-data-model.md`.

`YYYY-MM` text, or first-of-month date, or an integer month index from an epoch. Text sorts correctly and is readable in Grist. Date joins naturally with anything else date-shaped. Integer index is fastest and least readable.

**Recommendation:** `YYYY-MM` text at the storage boundary, a `Month` value object in Python that parses once and does arithmetic safely. Low stakes as long as it is uniform, and expensive to fix piecemeal if it is not.

**My recommendation:** adopt this as written. Nothing in the notes touches it, and the reasoning — readable in Grist, sorts correctly, one parser — is unaffected by anything new. Lowest-regret item on this list; no reason to revisit it further.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

---

## `[OPEN-6]` Read consistency across tables

**Blocks:** nothing yet. `05-interfaces.md`.

Grist has no cross-table snapshot read. With 1 to 3 editors and a sub-second read burst, a torn read is unlikely but not impossible, and it would produce a plan solved against inconsistent inputs with no visible symptom.

**Recommendation:** defer. Record the action log position before and after the read burst and warn if it moved. Escalate to abort-and-retry only if it is ever observed.

**My recommendation:** defer, as written. At 1-3 concurrent editors and a sub-second read burst, this is a low-probability failure mode; instrumenting it (log the action-log position, warn on movement) costs almost nothing and gives a way to notice if it's ever real, versus engineering an abort-and-retry path for a failure that may never occur.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

**discussion**
I do want to defer this now but make sure to document resolving this as future work for a real multi-user system.  my planners are hard to train and discipline and they routinely are writing over each other's work when they work in files stored on shared drives, so I think technical means are required to enforce discipline or guard against lack of disicipline.

---

## `[OPEN-7]` Are hard/soft min/max entered as FTE fraction or hours?

**Blocks:** `bounds` table units, solver conversion logic. `03-data-model.md`, `04-solver-design.md`.

New question, raised by the notes: they describe hard/soft min/max explicitly as "a number of FTE (full time equivalent percentage)," not hours — e.g. a planner enters "half time," not "84 hours." The solver's decision variable `x[p,w,m]` is naturally hours (it has to sum against capacity and multiply by an hourly rate), so somewhere a conversion has to happen.

`03-data-model.md` and `04-solver-design.md` now carry this as the candidate resolution: `bounds` stores FTE fractions, and the solver converts to hours at build time as `bound_h[p,w,m] = bound[p,w,m] * cap[w,m]`, using that person's actual monthly capacity rather than a fixed full-time constant.

**Cost of a late answer:** moderate. It changes the units and validation range of one table and one build-time step, but does not touch the constraint shapes themselves — C1/C2 just gain a multiplication.

**Recommendation:** confirm the FTE reading and the per-month-capacity conversion (rather than, say, a fixed 40-hour week) is what's intended — a person with reduced availability that month should have their FTE bounds scale down with them, not stay pinned to a nominal full week.

**My recommendation:** store FTE fraction, convert using that person's actual `cap[w,m]` for the month, not a flat full-time constant. This matches how the notes describe planners entering a pre-assignment ("half time," not a specific hour count), and using the real monthly capacity as the base keeps a partial-leave month correct automatically instead of needing a special case.

**Decision:**
- [ ] Accept
- [X ] Reject — alternative: 

**discussion**
at first I was thinking that I wanted these input as %fte, but in reality what people need and expect to see is hours.  I think instead I want these all entered in hours, and the number of workeable hours in the current month should be displayed prominently along with that month so the planners know what number to hit.  Right now the planners just pretend every month has 160 workable hours and assign people (without tools like this) to a target of 160 hours.  this causes enough problems and variations that I don't want to do that, I'd rather them be responsible for assigning actual units of hours. I do whant the %FTE for each worker aggregated as a check, and visible from either the project view or the person view, so the planner can see how close or far they are from filling the person's %FTE.


---

## `[OPEN-8]` What weight (and defaults) for the fragmentation penalty?

**Blocks:** `04-solver-design.md` objective tuning, `03-data-model.md` people defaults.

The notes give concrete defaults — soft max 2 concurrent projects, hard max 4, for every worker unless overridden — and say the solver "should rarely" violate the soft max. That fixes the defaults but not the objective weight `W_frag` that enforces "rarely." `04-solver-design.md` currently suggests `frag: 8`, placed above `churn: 5` because "rarely" reads stronger than general churn-avoidance, but that is a guess, not a value from the notes.

**Cost of a late answer:** low. It is one number in a weights file, tunable after the fact by rerunning historical scenarios.

**Recommendation:** start at the suggested value, then tune against a real planning period: if the solver fragments people more than planners consider acceptable, raise it before touching anything else.

**My recommendation:** start at `W_frag = 8`, between soft-bound (10) and churn (5). "Should be rare" reads as stronger intent than ordinary churn-avoidance but the notes don't ask for it to dominate spend or soft-bound adherence. Treat this as a starting point to tune against one real historical planning period rather than a number to get exactly right in the abstract — it's cheap to revisit.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

---

## `[OPEN-9]` Should the solver redistribute spend across months, or only hit the entered target?

**Blocks:** `04-solver-design.md` objective weighting (target vs. churn/fragmentation), how `targets` is meant to be populated and re-populated.

The notes state a preference for non-linear spend profiles over churn or fragmentation violations. `targets` already supports an arbitrary non-linear monthly value, entered by a PM, so one reading is: this is already handled, a PM who wants a non-linear profile just enters one. But the current objective weights target deviation at 100 versus churn at 5 and the (proposed) fragmentation weight at 8 — heavily dominant — which means the solver will always work hard to hit whatever is in `targets` for a given month even if a small reshuffle of *which month* the spend lands in would avoid a churn or fragmentation penalty entirely.

The alternative reading: the solver itself should have license to treat a soft target as an aim point it can miss in one month and make up in an adjacent one, if doing so avoids churn or a fragmentation violation — i.e., target deviation should not dominate churn/fragmentation as heavily as the current weights imply, at least for soft targets.

**Cost of a late answer:** moderate. It is a weighting change, not a schema change, but it changes what the solver's output means well enough that program reviews built around "the plan hits target X" need to be re-explained if it turns out targets are meant as flexible aim points.

**Recommendation:** clarify whether `targets.target_type = soft` already means "PM-adjustable aim point, solver may deviate for churn/fragmentation reasons," in which case lower `W_target` relative to `W_churn`/`W_frag`, or whether the PM's monthly number is meant to be hit as entered and non-linearity is only ever a PM decision made before solving, in which case the current dominant weighting is correct as is.

**My recommendation:** split what "hitting the target" means into two things, rather than treating it as one weight to retune. The notes are unambiguous that non-linear spend should be preferred over churn or fragmentation violations — but the same notes' stated goal is "the ultimate goal for the project is to spend out by the end of the PoP." Read together, that says the *total*, cumulative-by-PoP-end number is the thing that actually matters; the *monthly shape* is a planning aid the solver should be free to bend.

Concretely: keep hard targets exactly as they are (a true ceiling, never negotiable). For soft targets, demote the monthly deviation term below churn and fragmentation in the default weights (e.g. `frag 10, churn 10, target(soft, monthly) 6, soft-bound 6, idle 3, headcount 1`), and add a lighter-weight cumulative-to-date check — sum of `dp[p,m'] - dm[p,m']` for `m' <= m`, tracked against cumulative target through the same month — so total PoP spend still lands close to the funded amount even as the month-to-month shape flexes. This is a small model addition (one new term, using variables that already exist), not just a weight change, and it's worth doing because otherwise "lower the target weight" would quietly let a project underspend by PoP end, which is the opposite of what the notes ask for.

**Decision:**
- [ ] Accept
- [X ] Reject — alternative: 

I think the spend should be redistributed across the remaining months, but only AFTER the actual hours are input for a month (at the beginning of the subsequent month).  So the spend should redistribute once the actual known spend is in the system.

---

## `[OPEN-10]` Scope of the NCE (no-cost extension) recommendation

**Blocks:** `04-solver-design.md` diagnostics scope, whether this is v1 or later roadmap.

The notes ask for the solver to recommend a no-cost extension when worker constraints can't otherwise be met. `04-solver-design.md` sketches a candidate mechanic — re-run the elastic diagnostic with the binding project's `pop_end` pushed out and report whether that clears the binding set — but this is genuinely new scope, not a refinement of something already designed, and several things about it are undecided:

- Is this v1, or a later addition once the core solve/diagnose loop is proven?
- Is it purely diagnostic (report "extending by N months would clear this"), or should the tool ever act on it (e.g. write a proposed new `pop_end` for a human to accept)?
- How is "the binding driver is a PoP-end capacity crunch" distinguished from other kinds of infeasibility in the binding-constraint report?

**Cost of a late answer:** low to defer, since it can be added as a diagnostics-only feature after the core loop works without touching the data model. High if it turns out to require new decision variables (e.g. the solver choosing an extension length itself), which would be a real modeling addition.

**Recommendation:** treat as v1.1 — ship the core solve/diagnose loop first, add NCE recommendation as a diagnostics extension once there is real infeasibility data to test it against.

**My recommendation:** defer to v1.1, diagnostics-only (report a candidate extension length; never write a new `pop_end` automatically). This is new scope, not a refinement of an existing part of the design — building it now means designing against imagined infeasibilities instead of real ones. Once the core solve/diagnose/elastic-relaxation loop is running against actual data, extending the elastic re-solve to also try pushing `pop_end` is a small, well-scoped addition with real cases to validate it against.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

---

## Questions not yet asked of the operator

These need answers from whoever runs the plan, not from the design:

1. Where do actuals come from, and in what format? This determines the entire ingest mapping layer and is the single biggest unknown in `05-interfaces.md`. Still open — the notes describe this only as "another TBD automated process."

The actuals come from a timekeeping and finance system. they will be in the form of hours per worker per project and should be easy to write an importer for when the time comes.  For now, this project will work off of a randomly generated simulated example.


2. Is any monthly target a hard funding ceiling rather than an aim point? If yes, `target_type` is used from day one. Still open — the notes describe `labor_spend_target` only as a target, not distinguishing a hard ceiling.

The monthly target is not a hard celiing, it is an aim point. we are routinel over or under spent each month and the hours are modulated month by month from the orginal plan to compensate such that the project spends to near zero, usually a few hunderd or thousand dollars over.


3. Does uncovered capacity cost anything? Determines whether `W_idle` is meaningful or should be zero. Still open.

Uncovered capacity, workers with available hours that are not assigned to a project, should be identified, after a solve.  what I expect to happen is if a solution respecting the constraints leaves a worker with left over capacity, the planner will investigate, renegotiate constraints (e.g. like hard max number of projects they are willing to work), or find an outside-of-the-unit project for them to work on to fill their remaining time.


4. ~~Is there a fragmentation limit in practice, or is it acceptable for one person to be split across six projects in a month?~~ **Answered by the notes:** yes, defaults are soft max 2 / hard max 4 projects per person. See `[OPEN-8]` for the remaining weight-tuning question.
5. How often does the plan get re-solved, and by whom? Weekly by one PM implies different tooling from daily by three. Still open.
6. Who needs to see this outside the planning group, and in what format? Determines whether the MSPDI export is real or theoretical. Still open, though the notes confirm the editing surface itself should be "some kind of linked spreadsheet or workbook, but ideally not Excel itself" — consistent with the Grist choice already made in `02-architecture.md`.
