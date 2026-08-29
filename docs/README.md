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

Projects are modeled as single tasks with no precedence relationships. The only coupling between them is competition for finite worker capacity. Given per-person-per-project hour bounds, time-phased labor rates, worker capacity, and a monthly labor spend target per project, the system solves for an hours assignment across (project, person, month) that hits spend targets, respects hard bounds and capacity, minimizes soft bound violations, and stays close to the previous baseline. Humans edit constraints in a Grist document; a Python service reads them over REST, solves, and writes back a single `allocation` table. All cost figures are derived, never stored.

## Core design commitments

These are the load-bearing decisions. Changing any one of them invalidates large parts of the rest.

1. **No schedule graph.** There are no task dependencies, durations, or critical path. Capacity is the only interdependency. Any feature request that reintroduces precedence is out of scope, not a backlog item.
2. **The solver owns exactly one table.** `allocation.hours_assigned` is the only field the optimizer writes. Everything else is human input or derived output.
3. **Cost is never stored.** Cost is always `hours x rate(person, month, project rate structure)`, computed at read time. A retroactive rate correction reprices history with no re-solve and no migration.
4. **The human feedback loop runs through constraints, not results.** When a plan looks wrong, the operator edits a bound, a capacity value, or a target, then re-solves. Hand-editing assigned hours is supported only through an explicit lock mechanism, which the solver treats as a fixed variable.
5. **Infeasibility is a product surface, not an error.** The solver never returns a bare "infeasible". It returns which constraints bind and what relaxation would clear them.

## Repository layout

```
design-docs/          this set
allocsolver/          python package (see 06)
tests/
grist/                document schema export, seeded fixtures
deploy/               docker compose, env templates
```
