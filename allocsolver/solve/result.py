"""SolveResult — the return type of a solve run."""

from dataclasses import dataclass, field

from allocsolver.costing.masks import Cell

from .locks import LockConflict


@dataclass(frozen=True, slots=True)
class ObjectiveBreakdown:
    target: float
    soft: float
    idle: float
    churn: float
    headcount: float
    frag: float
    total: float


@dataclass(frozen=True, slots=True)
class BindingSlack:
    kind: str  # "capacity" | "hard_min" | "hard_max" | "hard_target"
    project_id: str | None
    person_id: str | None
    month: str
    amount: float
    detail: str


@dataclass(frozen=True, slots=True)
class DiagnosticsReport:
    binding: list[BindingSlack] = field(default_factory=list)
    lock_conflicts: list[LockConflict] = field(default_factory=list)
    """Locks that can't hold, from `solve/locks.py`. Reported before `binding` because
    they're both the likelier cause when a planner has been pinning cells by hand and
    the only cause the elastic model can't surface on its own."""

    def is_empty(self) -> bool:
        return not self.binding and not self.lock_conflicts

    def blocking_lock_conflicts(self) -> list[LockConflict]:
        return [c for c in self.lock_conflicts if c.is_infeasible]

    def render(self) -> str:
        if self.is_empty():
            # Reachable when the elastic model itself is infeasible for a reason no
            # slack covers and no lock explains. Rare, but a planner still needs to be
            # told what to do about it rather than handed an empty report.
            return (
                "INFEASIBLE, with no binding constraint or lock conflict identified. "
                "This is unexpected: the relaxed model should always be solvable. Check "
                "for a person with zero capacity in a month a hard target needs covered, "
                "or a hard_max_concurrent_projects of 0."
            )

        lines: list[str] = []
        blocking = self.blocking_lock_conflicts()
        if blocking:
            lines += ["INFEASIBLE. These locks cannot all hold:", ""]
            for c in blocking:
                who = " / ".join(x for x in (c.project_id, c.person_id) if x)
                lines.append(f"  {c.kind:14s} {who:24s} {c.month:8s} {c.locked_amount:g} vs limit {c.limit:g}")
                lines.append(f"    {c.detail}")
                if c.cells:
                    lines.append(f"    locked: {', '.join(c.cells)}")
            lines.append("")

        if self.binding:
            header = (
                "Also, minimum relaxation to reach feasibility:"
                if blocking
                else "INFEASIBLE. Minimum relaxation to reach feasibility:"
            )
            lines += [header, ""]
            for b in self.binding:
                who = " / ".join(x for x in (b.project_id, b.person_id) if x)
                lines.append(f"  {b.kind:12s} {who:24s} {b.month:8s} {b.amount:+.1f} h  ({b.detail})")

        ignored = [c for c in self.lock_conflicts if not c.is_infeasible]
        if ignored:
            lines += ["", "Locks the solver is ignoring (no variable for the cell):", ""]
            for c in ignored:
                lines.append(f"  {c.project_id} / {c.person_id} {c.month}: {c.detail}")

        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SolveResult:
    feasible: bool
    hours_assigned: dict[Cell, float]
    objective: ObjectiveBreakdown | None
    mip_gap: float | None
    wall_time_seconds: float
    solve_id: str
    diagnostics: DiagnosticsReport | None = None
    lock_warnings: list[LockConflict] = field(default_factory=list)
    """Locks that were silently dropped rather than honored — a cell with no `Bounds`
    row has no variable to pin (`locks.py`'s `ineligible`). Populated on a *feasible*
    solve too: the solve succeeded, but not with the pins the planner thinks they set,
    and nothing else in the result would ever reveal that."""
