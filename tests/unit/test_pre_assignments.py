"""The planner's manual pre-assignment inbox, kept separate from solver/simulation output."""

import json
from pathlib import Path

import pytest

from allocsolver.io.pre_assignments import apply_pre_assignments, clear_pre_assignments, load_pre_assignments
from allocsolver.models.bounds import Bounds
from tests.fixtures import two_person_two_project_plan


def test_load_pre_assignments_missing_file_is_empty(tmp_path: Path):
    assert load_pre_assignments(tmp_path) == []


def test_apply_pre_assignments_upserts_by_key():
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    original = next(b for b in plan.bounds if b.project_id == "proj_a" and b.person_id == "alice" and b.month == m1)
    assert original.hard_max == 160.0

    override = Bounds(project_id="proj_a", person_id="alice", month=m1, hard_min=0, soft_min=0, soft_max=50, hard_max=50)
    updated_plan = apply_pre_assignments(plan, [override])

    new_row = next(
        b for b in updated_plan.bounds if b.project_id == "proj_a" and b.person_id == "alice" and b.month == m1
    )
    assert new_row.hard_max == 50.0
    # everything else is untouched
    assert len(updated_plan.bounds) == len(plan.bounds)


def test_apply_pre_assignments_can_add_a_new_eligible_cell():
    plan = two_person_two_project_plan(months=3)
    m3 = plan.horizon()[2]

    # Start from a plan with that one cell missing (not yet eligible), confirming
    # apply_pre_assignments can introduce a cell, not just override an existing one.
    without_cell = plan.model_copy(
        update={
            "bounds": [
                b for b in plan.bounds if not (b.project_id == "proj_a" and b.person_id == "alice" and b.month == m3)
            ]
        }
    )
    assert len(without_cell.bounds) == len(plan.bounds) - 1

    new_cell = Bounds(
        project_id="proj_a", person_id="alice", month=m3, hard_min=0, soft_min=0, soft_max=20, hard_max=20
    )
    result_plan = apply_pre_assignments(without_cell, [new_cell])
    assert len(result_plan.bounds) == len(plan.bounds)


def test_apply_pre_assignments_rejects_a_typo_d_person_id():
    """Hand-edited planner input is exactly where a typo'd id sneaks in — this must
    be caught immediately (full Plan validation), not silently accepted."""
    plan = two_person_two_project_plan()
    m1 = plan.horizon_start
    bad_entry = Bounds(
        project_id="proj_a", person_id="not_a_real_person", month=m1, hard_min=0, soft_min=0, soft_max=20, hard_max=20
    )
    with pytest.raises(ValueError, match="not_a_real_person"):
        apply_pre_assignments(plan, [bad_entry])


def test_load_and_clear_round_trip(tmp_path: Path):
    m = two_person_two_project_plan().horizon_start
    entry = Bounds(project_id="p", person_id="w", month=m, hard_min=0, soft_min=0, soft_max=10, hard_max=10)
    (tmp_path / "pre_assignments.json").write_text(json.dumps([entry.model_dump(mode="json")]))

    loaded = load_pre_assignments(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].project_id == "p"

    clear_pre_assignments(tmp_path)
    assert load_pre_assignments(tmp_path) == []
