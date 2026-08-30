"""SolveResult — the return type of a solve run."""

from dataclasses import dataclass, field

from allocsolver.costing.masks import Cell


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

    def is_empty(self) -> bool:
        return not self.binding

    def render(self) -> str:
        if self.is_empty():
            return "No binding constraints."
        lines = ["INFEASIBLE. Minimum relaxation to reach feasibility:", ""]
        for b in self.binding:
            who = " / ".join(x for x in (b.project_id, b.person_id) if x)
            lines.append(f"  {b.kind:12s} {who:24s} {b.month:8s} {b.amount:+.1f} h  ({b.detail})")
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
