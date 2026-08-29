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

Projects are modeled as single tasks with no precedence relationships. The only coupling between them is competition for finite worker capacity. Given per-person-per-project FTE bounds, time-phased labor rates derived from salary and annual wrap rates, worker capacity, and a monthly labor spend target per project, the system solves for an hours assignment across (project, person, month) that hits spend targets, respects hard bounds and capacity, minimizes soft bound and fragmentation violations, and stays close to the previous baseline. Humans edit constraints in a Grist document; a Python service reads them over REST, solves, and writes back a single `allocation` table. All cost figures are derived, never stored.

## Core design commitments

These are the load-bearing decisions. Changing any one of them invalidates large parts of the rest.

1. **No schedule graph.** There are no task dependencies, durations, or critical path. Capacity is the only interdependency. Any feature request that reintroduces precedence is out of scope, not a backlog item.
2. **The solver owns exactly one table.** `allocation.hours_assigned` is the only field the optimizer writes. Everything else is human input or derived output.
3. **Cost is never stored.** Cost is always `hours x rate(person, month, project rate structure)`, computed at read time. A retroactive rate correction reprices history with no re-solve and no migration.
4. **The human feedback loop runs through constraints, not results.** When a plan looks wrong, the operator edits a bound, a capacity value, or a target, then re-solves. Hand-editing assigned hours is supported only through an explicit lock mechanism, which the solver treats as a fixed variable.
5. **Infeasibility is a product surface, not an error.** The solver never returns a bare "infeasible". It returns which constraints bind and what relaxation would clear them.
6. **Bounds are entered as FTE fraction, not hours.** Hard/soft min/max are a percentage of full time, the way planners actually think about a pre-assignment. The solver converts to hours against that person's capacity for the specific month.
7. **Fragmentation is two-tiered.** Every worker gets a soft max (default 2) and a hard max (default 4) concurrent projects. The soft max is a penalty, meant to be rarely crossed; the hard max is never crossed.
8. **A project's rate structure selects one wrap rate, it does not stack layers.** Each person has a base hourly rate (salary / 12 / workable hours) and three derived rates (project, OH, fee), each that base rate times its own wrap rate. A project's `rate_structure` names which single one applies; OH and fee are not layered multiplicatively or additively on top of the project rate.

Commitments 6-8 are recent, sourced from `unstructured_notes.md`, and carried into the docs as candidate resolutions of open questions rather than settled fact — see `07-open-questions.md` (`[OPEN-2]`, `[OPEN-3]`, `[OPEN-7]`, `[OPEN-8]`) before relying on them for implementation.

## Repository layout

```
design-docs/          this set
allocsolver/          python package (see 06)
tests/
grist/                document schema export, seeded fixtures
deploy/               docker compose, env templates
```
