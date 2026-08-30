# 07. Open Questions — Revision 3

Revision 2 carried forward one open item (`[OPEN-11]`) plus two previously-unanswered operator questions. All three now have answers, and the answers were detailed enough to also pin down the real operating cadence (a monthly cycle, one step behind its own actuals, with an optional "hot fix") and three concrete export formats that weren't specified before. Everything from Revisions 1 and 2 is now either resolved or explicitly deferred as tracked future work — this revision surfaces exactly one small new fork that came out of those answers.

Full reasoning trails for earlier items are in git history for this file, not repeated here.

---

## Resolved this revision

| # | Question | Decision | Where it lives now |
|---|---|---|---|
| `[OPEN-11]` | Exact reforecast algorithm | Accepted: proportional split, human-reviewed. Confirmed operational detail: planners review the prior month's plan monthly, edit current/future values themselves, and manually trigger the re-solve — reforecast proposes a starting point, it doesn't replace that review. | `04-solver-design.md` |
| *(operator)* | How often does the plan get re-solved, and by whom? | Fully answered: monthly, at month-end, for next-month-forward, by the planners. Workforce export goes out by the 1st. That month's actuals land in the *first week of the following month* — too late to inform the solve that already ran — so a conditional second solve (a "hot fix") happens only if the resulting variance is judged significant enough to justify revising and re-sending an already-distributed assignment. | `01-system-overview.md` (workflow), `04-solver-design.md` (reforecasting) |
| *(operator)* | Who needs to see this, and in what format? | Fully answered: only planners use the tool itself. Two new audiences and three new concrete export formats: a workforce assignment sheet (hours only, no cost/rate data — a hard requirement, not just an omission), a variance sheet, and a per-project budget summary sheet. The originally-speculative MS Project/MSPDI export has no confirmed consumer and is now legacy/low-priority rather than a real deliverable. | `05-interfaces.md`, `06-code-structure-and-dependencies.md` |

---

## Remaining open questions

### `[OPEN-12]` Does a "hot fix" need a numeric trigger, or is planner judgment enough?

**Blocks:** nothing structural — this only affects whether the tool adds an alerting/flagging feature on top of the reforecast report.

The confirmed cadence has planners deciding *whether* to re-solve the in-progress month based on whether the prior month's variance was "significant." No numeric threshold was specified. Two ways this could go:

- **Pure judgment (current default).** The reforecast/variance report always shows the number; the planner decides. Nothing to build beyond the report itself.
- **A flagged threshold.** e.g. the tool highlights a project/month combination in the reforecast report once variance exceeds some percentage or dollar amount, as a "you may want to look at this" signal rather than a hard rule.

**Cost of a late answer:** low. This is a display/alerting nicety layered on a report that has to exist either way; adding a highlight rule later doesn't change any stored data or the solve/reforecast mechanics.

**Recommendation:** ship with pure judgment in v1 (no threshold) — a fabricated threshold with no real usage history behind it is more likely to be wrong (crying wolf, or missing real misses) than helpful. Revisit once there's a track record of actual hot-fix decisions to calibrate against.

**Decision:**
- [ X] Accept
- [ ] Reject — alternative: 

**discussion** planner judgement only. the system need not detect when a hot fix is necessary.

---

## Future work (tracked, not blocking v1)

- **Multi-editor conflict protection.** Unchanged from Revision 2: deferred for the solver's own read-consistency (low risk at 1-3 editors), but flagged as real future work given this planning group's demonstrated pattern of overwriting each other's work on shared files elsewhere. See `02-architecture.md`.

## Still unanswered

None carried forward — both operator questions from Revision 2 are resolved above.
