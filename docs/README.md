# Labor Allocation Planner: Design Documentation

Design docs for a MILP-driven labor allocation and spend planning system, replacing MS Project as the plan representation layer.

**Status:** draft. Open decisions are collected in `07-open-questions.md` and are marked inline as `[OPEN]` wherever they affect a design choice.

## Read in this order

| Doc | Covers | Read it when |
|---|---|---|
| `01-system-overview.md` | Problem, scope, non-goals, users, glossary | Starting cold |
| `02-architecture.md` | Components, boundaries, control flow, deployment | Wiring anything up |
| `03-data-model.md` | Tables, keys, types, invariants | Touching schema or storage |
| `04-solver-design.md` | MILP formulation, objective, diagnostics | Touching the optimizer |
| `05-interfaces.md` | Grist API contract, actuals ingest, CLI, snapshots | Writing an integration |
| `06-code-structure-and-dependencies.md` | Package layout, dependency graph, licenses | Setting up the repo |
| `07-open-questions.md` | Decisions not yet made, with the tradeoff for each | Before committing to schema or formulation |

## One-paragraph summary

Projects are modeled as single tasks with no precedence relationships. The only coupling between them is competition for finite worker capacity. Given per-person-per-project hour bounds, time-phased labor rates derived from salary and annual wrap rates, worker capacity, and a monthly labor spend target per project, the system solves for an hours assignment across (project, person, month) that hits whatever is currently in the target table, respects hard bounds and capacity, minimizes soft bound and fragmentation violations, and stays close to the previous baseline. When a month closes, actuals are reconciled and a reforecast redistributes any variance across the project's remaining open months, so the plan keeps converging on its funded total without any single month's target being sacred. Humans edit constraints in a Grist document; a Python service reads them over REST, solves, and writes back a single `allocation` table. All cost figures are derived, never stored.

## Core design commitments

These are the load-bearing decisions. Changing any one of them invalidates large parts of the rest.

1. **No schedule graph.** There are no task dependencies, durations, or critical path. Capacity is the only interdependency. Any feature request that reintroduces precedence is out of scope, not a backlog item.
2. **The solver owns exactly one table.** `allocation.hours_assigned` is the only field the optimizer writes. Everything else is human input or derived output.
3. **Cost is never stored.** Cost is always `hours x rate(person, month, project rate structure)`, computed at read time. A retroactive rate correction reprices history with no re-solve and no migration.
4. **The human feedback loop runs through constraints, not results.** When a plan looks wrong, the operator edits a bound, a capacity value, or a target, then re-solves. Hand-editing assigned hours is supported only through an explicit lock mechanism, which the solver treats as a fixed variable.
5. **Infeasibility is a product surface, not an error.** The solver never returns a bare "infeasible". It returns which constraints bind and what relaxation would clear them.
6. **Bounds are entered and stored in hours, not FTE fraction.** Planners are responsible for exact hour counts against a displayed monthly workable-hours reference, not a percentage abstraction. An aggregate %FTE per person per month is computed as a reporting check, never a solver input.
7. **Fragmentation is two-tiered.** Every worker gets a soft max (default 2) and a hard max (default 4) concurrent projects. The soft max is a penalty, meant to be rarely crossed (`W_frag = 8`); the hard max is never crossed.
8. **A project's rate structure selects one wrap rate, it does not stack layers.** A person has one base hourly rate (salary / 12 / workable hours); a project's `rate_structure` selects exactly one of the project, OH, or fee wrap rate to apply to it. Each wrap rate is a single, complete, atomic multiplier — never decomposed or recomposed. Most projects select `project`; internally funded efforts (management time, IR&D, business development) select `oh` or `fee` instead.
9. **Non-linear spend is achieved by reforecasting `targets` between solves, not by loosening the solver's target weight within one.** The solver always works hard to hit whatever is currently in `targets` (target weight stays dominant). Redistribution happens as a distinct step, triggered when a closed month's actuals reveal a variance, that proposes a proportionally-split updated target profile for the project's remaining open months — always human-reviewed, never a silent write.
10. **Read-consistency and multi-editor conflict handling are deferred, not solved.** At 1-3 editors this is low-risk today, but the planning group has a known real-world pattern of clobbering each other's work in shared files elsewhere, so this is tracked as real future work, not assumed away — see `02-architecture.md`.
11. **The solve cadence is monthly, one cycle behind its own actuals, with an optional mid-cycle "hot fix."** Planners solve at month-end for the next month forward and distribute a hours-only workforce export by the 1st. That month's own actuals aren't available until the following month has already started, so reforecasting always corrects the *next* solve, not the one just sent out — except when a variance is judged significant enough to warrant re-solving the in-progress month and re-sending it, which is a human decision, not an automatic trigger.
12. **Workforce and planners see fundamentally different things.** Only planners use Grist/the solver. The workforce receives a plain export — worker, project, hours for next month, nothing else — with cost, rate, and salary data deliberately excluded. Planners additionally get a variance export and a per-project budget summary export. The originally-speculative MS Project (MSPDI) export has no confirmed consumer and is now legacy/low-priority.

These reflect the user's answers across two rounds of `07-open-questions.md`; see that document for the reasoning behind each and what (if anything) remains genuinely open.

## Repository layout

```
design-docs/          this set
allocsolver/          python package (see 06)
tests/
grist/                document schema export, seeded fixtures
deploy/               docker compose, env templates
```
