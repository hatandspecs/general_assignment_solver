"""Why a set of locks can't be satisfied — the question `diagnose`'s elastic model
structurally cannot answer.

`AGENTS.md`: "An infeasible model needs to say why. 'No solution' is not an answer a
planner can act on." The elastic relaxation (`elastic.py`) delivers that for bounds,
capacity and hard targets by relaxing them and reporting the slack that had to open.
It cannot do it for locks, because locks are the one thing it re-pins verbatim
(`elastic.py`'s "C5: fixed cells still pinned") — a contradiction between two locks,
or between a lock and a hard ceiling, makes the *elastic* model infeasible too, and
`diagnose` then reports an empty `binding` list: "INFEASIBLE. No binding constraints."

Relaxing locks in the elastic model would be the wrong fix anyway. Slack on a locked
cell would report "your lock had to move by 14h", which is true but useless, since the
planner set that value on purpose and the whole point is that it is not negotiable.
What they need is the conflict named: *these* locks, together, exceed *this* limit.

So this module answers it directly in Python instead of through the solver. Locks are
constants, not variables — once pinned, every constraint they can violate is plain
arithmetic over known numbers, with no search involved. Three can actually bind, and
they are exactly the constraints that survive `apply_fixed`:

- **capacity (C3)**, an equality with a non-negative idle term, so locked hours for one
  person-month may not exceed their available hours;
- **fragmentation (C6)**, whose hard ceiling has no slack in either model, and which
  locked nonzero cells drive directly (`apply_fixed` sets `y=1` for them);
- **hard spend targets (C4)**, whose `spend <= target` ceiling locked hours can blow
  through on their own.

C1/C2 are deliberately *not* checked: `constraints.py` skips them for fixed cells, so a
lock above its cell's `hard_max` is legal by design — the lock overrides the bound
rather than fighting it. Reporting it as a conflict would be a false alarm.

A fourth kind, `ineligible`, isn't an infeasibility at all but a silent no-op worth the
same attention: `fixed_cells_and_values` iterates over eligible cells, so a lock on a
cell with no `Bounds` row is dropped without comment, and a planner who locked it has
every reason to think it is holding.
"""

from dataclasses import dataclass

from allocsolver.costing.masks import eligible_cells
from allocsolver.costing.rates import loaded_rate
from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan
from allocsolver.models.targets import TargetType


@dataclass(frozen=True, slots=True)
class LockConflict:
    kind: str  # "capacity" | "fragmentation" | "hard_target" | "ineligible"
    person_id: str | None
    project_id: str | None
    month: str
    locked_amount: float
    limit: float
    cells: tuple[str, ...]
    detail: str

    @property
    def is_infeasible(self) -> bool:
        """`ineligible` is a dropped lock, not a contradiction — it never makes a
        model infeasible, so it's reported as a warning on a *successful* solve too."""
        return self.kind != "ineligible"


def lock_conflicts(plan: Plan) -> list[LockConflict]:
    """Every way the current locks are unsatisfiable, named and quantified.

    Open months only. A closed month's cells are fixed to `hours_actual` by C5 whatever
    their `locked` flag says, and an actual that overran capacity is history, not a
    conflict to resolve.
    """
    closed_through = plan.closed_through
    eligible = set(eligible_cells(plan))

    locked = [
        a
        for a in plan.allocation
        if a.locked and (closed_through is None or a.month > closed_through)
    ]
    if not locked:
        return []

    out: list[LockConflict] = []

    for a in locked:
        cell = (a.project_id, a.person_id, a.month)
        if cell in eligible:
            continue
        out.append(
            LockConflict(
                kind="ineligible",
                person_id=a.person_id,
                project_id=a.project_id,
                month=str(a.month),
                locked_amount=round(a.hours_assigned, 2),
                limit=0.0,
                cells=(f"{a.project_id}/{a.person_id}",),
                detail=(
                    f"{a.person_id} is locked to {a.hours_assigned:g}h on {a.project_id} in {a.month}, but that "
                    f"cell is not eligible (no Bounds row, or eligible=False) — the solver has no variable for "
                    f"it, so the lock is silently ignored and the cell stays empty"
                ),
            )
        )

    in_play = [a for a in locked if (a.project_id, a.person_id, a.month) in eligible]

    # C3: capacity. An equality `sum(x) + idle == cap` with `idle >= 0`, so locked
    # hours alone exceeding capacity has no feasible completion.
    by_person_month: dict[tuple[str, Month], list] = {}
    for a in in_play:
        by_person_month.setdefault((a.person_id, a.month), []).append(a)

    for (person_id, month), rows in sorted(by_person_month.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        total = sum(r.hours_assigned for r in rows)
        try:
            available = plan.capacity_of(person_id, month).available_hours
        except KeyError:
            continue
        if total > available + 1e-6:
            out.append(
                LockConflict(
                    kind="capacity",
                    person_id=person_id,
                    project_id=None,
                    month=str(month),
                    locked_amount=round(total, 2),
                    limit=round(available, 2),
                    cells=tuple(sorted(f"{r.project_id}:{r.hours_assigned:g}h" for r in rows)),
                    detail=(
                        f"{person_id}'s locked cells in {month} total {total:g}h against {available:g}h of "
                        f"capacity — {total - available:g}h over. Unlock one, or lower a locked value."
                    ),
                )
            )

        nonzero = [r for r in rows if r.hours_assigned > 1e-9]
        hard_max = plan.person(person_id).hard_max_concurrent_projects
        if len(nonzero) > hard_max:
            out.append(
                LockConflict(
                    kind="fragmentation",
                    person_id=person_id,
                    project_id=None,
                    month=str(month),
                    locked_amount=float(len(nonzero)),
                    limit=float(hard_max),
                    cells=tuple(sorted(r.project_id for r in nonzero)),
                    detail=(
                        f"{person_id} is locked onto {len(nonzero)} projects in {month} against a "
                        f"hard_max_concurrent_projects of {hard_max}. Unlock "
                        f"{len(nonzero) - hard_max}, or raise their concurrency ceiling."
                    ),
                )
            )

    # C4: hard spend targets carry a `spend <= target` ceiling with no slack.
    hard_targets = {
        (t.project_id, t.month): t for t in plan.targets if t.target_type == TargetType.HARD
    }
    if hard_targets:
        by_project_month: dict[tuple[str, Month], list] = {}
        for a in in_play:
            by_project_month.setdefault((a.project_id, a.month), []).append(a)

        for (project_id, month), rows in sorted(
            by_project_month.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
        ):
            target = hard_targets.get((project_id, month))
            if target is None:
                continue
            spend = sum(
                loaded_rate(plan, r.person_id, r.month, r.project_id) * r.hours_assigned for r in rows
            )
            if spend > target.labor_spend_target + 1e-6:
                out.append(
                    LockConflict(
                        kind="hard_target",
                        person_id=None,
                        project_id=project_id,
                        month=str(month),
                        locked_amount=round(spend, 2),
                        limit=round(target.labor_spend_target, 2),
                        cells=tuple(sorted(f"{r.person_id}:{r.hours_assigned:g}h" for r in rows)),
                        detail=(
                            f"{project_id}'s locked cells in {month} cost ${spend:,.0f} against a hard spend "
                            f"target of ${target.labor_spend_target:,.0f} — ${spend - target.labor_spend_target:,.0f} "
                            f"over a ceiling that has no tolerance. Lower a locked value, or make the target soft."
                        ),
                    )
                )

    return out
