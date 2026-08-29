# 05. Interfaces

## Grist REST API

Base: `{GRIST_URL}/api/docs/{DOC_ID}`. Auth by bearer token in the environment.

### Read

```
GET /tables/{tableId}/records[?filter={...}]
```

All input tables are pulled in a single burst at the start of a run. Records come back as `{id, fields: {...}}`; the wrapper flattens to Pydantic models immediately so that Grist's envelope shape does not leak past `io/grist.py`.

**Read consistency:** Grist does not offer a snapshot read across tables. Two mitigations, both cheap: record the document's action log position before and after the read burst and abort if it moved, or accept the risk given 1 to 3 editors and a read burst measured in hundreds of milliseconds. Start with the second, implement the first if it ever bites. `[OPEN-6]`

### Write

```
PATCH /tables/Allocation/records     update existing rows
PUT   /tables/Allocation/records     upsert by key
```

Prefer `PUT` with `require: {project_id, person_id, month}` so that new cells and updated cells are one call. The entire write is one request per batch of up to a few thousand records, which makes it effectively atomic at the batch level.

**Never written by the solver:** `hours_actual`, `locked`, `lock_note`, and every column of every other table. Enforce this in code by giving the write client an explicit column allowlist, and enforce it again in Grist access rules so that a bug cannot corrupt human input.

### Client contract

```python
class GristClient:
    def fetch_table(self, table: str, model: type[T]) -> list[T]: ...
    def upsert_allocation(self, rows: list[AllocationWrite]) -> int: ...
    def action_log_position(self) -> int: ...
```

Three methods. Everything else the service needs is composition over these. Keeping this surface small is what makes swapping Grist for Postgres later a one-file change rather than a rewrite.

## Actuals ingest

The hard part is mapping, not loading.

### Input

A CSV or Excel export from the timekeeping system. Expected minimum columns: employee identifier, charge code, date or period, hours. Everything else ignored.

### Mapping table

Lives in Grist alongside the rest, since it needs human maintenance.

| Column | Notes |
|---|---|
| `charge_code` | As it appears in the export |
| `project_id` | Target project |
| `effective_from` | Month this mapping starts |
| `effective_to` | Nullable |

Charge code to project is many-to-one and changes over time, which is why the mapping is time-phased rather than a static dictionary. Reorganizations retroactively rename codes; a static map silently misallocates history when that happens.

Employee identifier to `person_id` needs the same treatment if the timekeeping system's identifiers do not match. Assume they do not.

### Pipeline

```
1. Parse       tolerant reader; do not assume column order or exact headers
2. Normalize   identifiers, trim, uppercase charge codes, parse dates
3. Map         charge_code + month -> project_id; employee -> person_id
4. Quarantine  unmapped rows to a report; never drop, never guess
5. Aggregate   sum hours by (project_id, person_id, month)
6. Write       hours_actual via upsert
7. Report      total hours in, mapped, quarantined, and rows written
```

Step 4 is the one that gets cut for time and should not be. An unmapped charge code that silently disappears makes actual cost quietly understated, and nobody notices until a variance review months later.

### Reconciliation report

After each ingest, emit:

- Total hours in the export vs total hours written. These must agree, or the difference must be fully accounted for by quarantined rows.
- Cells with actuals but no plan (unplanned work).
- Cells with plan but no actuals in a closed month (planned work that did not happen).

Both of the last two are planning signals, not errors, and both are invisible without this report.

## CLI

```
allocsolver solve      --horizon 2026-09:2027-08
                       [--dry-run] [--accept] [--time-limit 300]
                       [--weights weights.toml] [--lexicographic]

allocsolver validate   --horizon ...          checks only, no solve
allocsolver ingest     --file actuals.csv [--dry-run]
allocsolver diff       --from <snap> --to <snap>
allocsolver snapshot   --list | --show <id> | --accept <id>
allocsolver export     --format mspdi --out plan.xml
allocsolver iis        --horizon ...          analyst tool, infeasibility only
```

`--dry-run` on both `solve` and `ingest` writes nothing and prints the deltas it would have made. This is the default posture for anyone learning the tool.

## Snapshots

Every run writes a directory to the snapshot repo:

```
snapshots/2026-08-24T140312Z-a3f9c1/
    inputs.json        every input table as pulled, verbatim
    allocation.json    resulting hours_assigned
    objective.json     term-by-term breakdown, weights, MIP gap, solve time
    diagnostics.json   binding constraints, if any
    meta.json          solve_id, horizon, code version, solver version
```

Committed to git; accepted baselines get a tag. This gives reproducibility, scenario diffing, and an audit trail for free.

`inputs.json` is the important one. Storing the full inputs means any solve can be replayed exactly, months later, against a different code version, which is the only reliable way to answer "why did the plan say that in November."

`allocsolver diff` compares two snapshots cell by cell and reports movement grouped by project and by person, which is what a program review actually wants to see.

## MS Project export

Optional, for stakeholders who need a `.mpp`-family file.

`mpxj` via JPype writes MSPDI XML (it reads `.mpp` but does not write it), so the round trip is: generate MSPDI, open in Project, save as `.mpp` if required. Requires a JVM in the container.

The mapping is lossy by construction, and should be, since the whole premise is that Project's model does not fit:

| This system | MSPDI |
|---|---|
| Project | Task |
| Person | Resource |
| Cell hours | Timephased assignment work |
| Bounds | Nothing. Dropped. |
| Spend target | Nothing. Dropped. |
| Rate structure | Resource standard rate, flattened |

Export is one-way. There is no import path, and adding one would reintroduce exactly the coupling this design exists to remove.
