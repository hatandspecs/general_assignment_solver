# 07. Open Questions

Decisions not yet made. Each is referenced inline where it affects a design choice. Ordered by how much rework a late answer costs.

---

## `[OPEN-2]` How do the rate layers compose?

**Blocks:** every cost number in the system. `03-data-model.md`, `04-solver-design.md`.

Stored per person per month are a project rate, an OH rate, and a fee rate. Two readings:

- **Additive.** All three are dollars per hour, and `R = project + oh + fee`.
- **Multiplicative.** Project rate is dollars per hour, OH and fee are fractions, and `R = project x (1 + oh) x (1 + fee)`.

The field naming ("Monthly OH Rate") leans additive, but is equally consistent with stored fractions. Whether fee applies to the OH-loaded base or to raw labor also differs by contract type and is a third variant.

**Cost of a late answer:** low in code (one function), high in trust. Every number produced before this is settled is wrong by a multiplier, and the error is plausible enough not to be noticed.

**Recommendation:** settle now, encode it in `rate_structures.composition`, and write the parity test in the same commit.

---

## `[OPEN-5]` Are hour bounds per month or per period of performance?

**Blocks:** `bounds` table shape, editing UI design, variable count. `03-data-model.md`.

- **Per PoP.** One row per (project, person). Small table, simple list editor. Cannot express "half time through Q1, full time after."
- **Per month.** Roughly `projects x people x months` rows. Needs a real grid editor. Expresses ramp-up, ramp-down, and planned leave against a specific project.

**Middle option worth considering:** per-PoP defaults with per-month overrides only where they differ. Keeps the common case to one row and the table sparse, at the cost of an as-of resolution step, which is the same class of bug flagged for the rates table.

**Cost of a late answer:** high. Adding the month dimension later is a schema migration plus a UI rebuild plus a solver change.

**Recommendation:** decide by asking whether any current project has a staffing profile that varies within its PoP. If even one does, go per month now.

---

## `[OPEN-3]` Is `project_rate` entered, or derived from salary?

**Blocks:** `rates` table, data entry workflow. `03-data-model.md`.

The requirement lists annual salary *and* a monthly project rate on the same timeline. Either the two are maintained independently (and can disagree), or the rate is `salary / productive_hours_per_year` and salary is the real input.

If derived, the divisor is itself a decision: 2080 hours, or net of holiday and leave, or a standard productive-hours factor. That divisor is a policy number and should be a stored, versioned parameter rather than a constant in code.

**Recommendation:** if derived, store the divisor per person per year in a `productive_hours` column and compute `project_rate` as a formula. Keeps one input, makes the assumption visible.

---

## `[OPEN-4]` Do travel and ODC budgets enter the optimization?

**Blocks:** solver scope. `03-data-model.md`, `04-solver-design.md`.

Currently carried as project attributes and displayed, not optimized. The requirement describes the solver as labor-only, so this matches today's behavior.

If total project spend (labor + travel + ODC) is what must hit the monthly target, the spend constraint C4 changes to include non-labor terms, and travel and ODC need month phasing rather than a single budget number. That is a meaningful extension: new tables, new variables if they are decision quantities rather than fixed inputs, and a real question about whether the solver should be *choosing* travel spend.

**Recommendation:** keep labor-only for v1. Add a `non_labor_planned[p,m]` input column now, defaulting to zero, and subtract it from the labor target in C4. That is a one-line change that makes total-spend targeting available later without a schema migration.

---

## `[OPEN-1]` Month representation

**Blocks:** every join. `03-data-model.md`.

`YYYY-MM` text, or first-of-month date, or an integer month index from an epoch. Text sorts correctly and is readable in Grist. Date joins naturally with anything else date-shaped. Integer index is fastest and least readable.

**Recommendation:** `YYYY-MM` text at the storage boundary, a `Month` value object in Python that parses once and does arithmetic safely. Low stakes as long as it is uniform, and expensive to fix piecemeal if it is not.

---

## `[OPEN-6]` Read consistency across tables

**Blocks:** nothing yet. `05-interfaces.md`.

Grist has no cross-table snapshot read. With 1 to 3 editors and a sub-second read burst, a torn read is unlikely but not impossible, and it would produce a plan solved against inconsistent inputs with no visible symptom.

**Recommendation:** defer. Record the action log position before and after the read burst and warn if it moved. Escalate to abort-and-retry only if it is ever observed.

---

## Questions not yet asked of the operator

These need answers from whoever runs the plan, not from the design:

1. Where do actuals come from, and in what format? This determines the entire ingest mapping layer and is the single biggest unknown in `05-interfaces.md`.
2. Is any monthly target a hard funding ceiling rather than an aim point? If yes, `target_type` is used from day one.
3. Does uncovered capacity cost anything? Determines whether `W_idle` is meaningful or should be zero.
4. Is there a fragmentation limit in practice, or is it acceptable for one person to be split across six projects in a month?
5. How often does the plan get re-solved, and by whom? Weekly by one PM implies different tooling from daily by three.
6. Who needs to see this outside the planning group, and in what format? Determines whether the MSPDI export is real or theoretical.
