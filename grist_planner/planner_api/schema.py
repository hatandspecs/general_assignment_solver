"""Grist table schema — the single source of truth for both provisioning (creating
tables/columns) and read/write field mapping.

Column ids mirror the corresponding Pydantic model's field names exactly (`Month`
serializes to plain "YYYY-MM" text, same as `allocsolver/io/local.py`'s JSON files),
so a Grist record's `fields` dict can be passed straight to `Model.model_validate()`
and a model's `model_dump(mode="json")` can be passed straight back as `fields` —
no separate mapping layer needed.

Table names follow the same star schema as `io/local.py`'s one-file-per-table
layout, plus two tables that file-based storage doesn't need:

- `Pre_Assignments`: the planner's manual-input surface (`io/pre_assignments.py`'s
  `pre_assignments.json`, promoted to a live, editable Grist table).
- `Meta`: `Plan.horizon_start` / `horizon_end` / `closed_through` — top-level Plan
  fields with nowhere else to live now that there's no `meta.json`.

`Report_*` tables are generated, read-only output — the backend overwrites them
wholesale on every "run reports" action; nothing else should write to them.
"""

from dataclasses import dataclass

GristType = str  # one of Grist's column type strings: "Text", "Numeric", "Int", "Bool"


@dataclass(frozen=True, slots=True)
class TableSchema:
    table_id: str
    columns: list[tuple[str, GristType]]


INPUT_TABLES: list[TableSchema] = [
    TableSchema(
        "People",
        [
            ("person_id", "Text"),
            ("name", "Text"),
            ("active_from", "Text"),
            ("active_to", "Text"),
            ("soft_max_concurrent_projects", "Int"),
            ("hard_max_concurrent_projects", "Int"),
        ],
    ),
    TableSchema(
        "Projects",
        [
            ("project_id", "Text"),
            ("name", "Text"),
            ("pop_start", "Text"),
            ("pop_end", "Text"),
            ("rate_structure", "Text"),
            ("labor_budget", "Numeric"),
            ("travel_budget", "Numeric"),
            ("odc_budget", "Numeric"),
            ("status", "Text"),
        ],
    ),
    TableSchema("Rate_Structures", [("structure_id", "Text"), ("rate_type", "Text")]),
    TableSchema("Rates", [("person_id", "Text"), ("month", "Text"), ("annual_salary", "Numeric")]),
    TableSchema(
        "Wrap_Rates",
        [
            ("month", "Text"),
            ("workable_hours", "Numeric"),
            ("project_wrap_rate", "Numeric"),
            ("oh_wrap_rate", "Numeric"),
            ("fee_wrap_rate", "Numeric"),
        ],
    ),
    TableSchema("Capacity", [("person_id", "Text"), ("month", "Text"), ("available_hours", "Numeric")]),
    TableSchema(
        "Bounds",
        [
            ("project_id", "Text"),
            ("person_id", "Text"),
            ("month", "Text"),
            ("hard_min", "Numeric"),
            ("soft_min", "Numeric"),
            ("soft_max", "Numeric"),
            ("hard_max", "Numeric"),
            ("eligible", "Bool"),
        ],
    ),
    TableSchema(
        "Targets",
        [
            ("project_id", "Text"),
            ("month", "Text"),
            ("labor_spend_target", "Numeric"),
            ("target_tolerance", "Numeric"),
            ("target_type", "Text"),
        ],
    ),
    TableSchema(
        "Allocation",
        [
            ("project_id", "Text"),
            ("person_id", "Text"),
            ("month", "Text"),
            ("hours_assigned", "Numeric"),
            ("hours_actual", "Numeric"),
            ("locked", "Bool"),
            ("lock_note", "Text"),
            ("solve_id", "Text"),
        ],
    ),
    # Manual pre-assignment input, same shape as Bounds — `05-interfaces.md`'s
    # "Manual pre-assignments", now editable live in Grist instead of a hand-edited
    # JSON file. Cleared (all rows removed) once a "Commit Plan" merges them into Bounds.
    TableSchema(
        "Pre_Assignments",
        [
            ("project_id", "Text"),
            ("person_id", "Text"),
            ("month", "Text"),
            ("hard_min", "Numeric"),
            ("soft_min", "Numeric"),
            ("soft_max", "Numeric"),
            ("hard_max", "Numeric"),
            ("eligible", "Bool"),
        ],
    ),
    # Plan.horizon_start / horizon_end / closed_through — a single row, id=1.
    TableSchema("Meta", [("horizon_start", "Text"), ("horizon_end", "Text"), ("closed_through", "Text")]),
]

REPORT_TABLES: list[TableSchema] = [
    TableSchema(
        "Report_WorkAssignments",
        [("worker_name", "Text"), ("project_name", "Text"), ("month", "Text"), ("hours_assigned", "Numeric")],
    ),
    TableSchema(
        "Report_Variance",
        [
            ("worker_name", "Text"),
            ("project_name", "Text"),
            ("month", "Text"),
            ("hours_assigned", "Numeric"),
            ("actual_hours", "Numeric"),
            ("delta", "Numeric"),
        ],
    ),
    TableSchema(
        "Report_BudgetSummary",
        [
            ("project_id", "Text"),
            ("project_name", "Text"),
            ("month", "Text"),
            ("planned_spend", "Numeric"),
            ("actual_spend", "Numeric"),
            ("delta", "Numeric"),
            ("cumulative_planned_spend", "Numeric"),
            ("cumulative_actual_spend", "Numeric"),
            ("planned_funds_remaining", "Numeric"),
            ("actual_funds_remaining", "Numeric"),
        ],
    ),
    TableSchema(
        "Report_StaffingBalance",
        [
            ("month", "Text"),
            ("capacity_dollars", "Numeric"),
            ("demand_dollars", "Numeric"),
            ("balance_dollars", "Numeric"),
            ("status", "Text"),
        ],
    ),
    # "See how the solution differs from the pre-assignment" — one row per cell that
    # was either pre-assigned, solved, or both, for the month a "Run Planning"
    # preview just solved.
    TableSchema(
        "Report_SolveDiff",
        [
            ("project_id", "Text"),
            ("person_id", "Text"),
            ("month", "Text"),
            ("pre_assigned_hours", "Numeric"),
            ("solved_hours", "Numeric"),
            ("delta", "Numeric"),
            ("status", "Text"),
        ],
    ),
]

ALL_TABLES: list[TableSchema] = INPUT_TABLES + REPORT_TABLES
