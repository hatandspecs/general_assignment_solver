"""Rolling horizon — `04-solver-design.md`, "Performance": solve a window, freeze, roll."""

from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan


def restrict_to_horizon(plan: Plan, start: Month, end: Month) -> Plan:
    """A copy of `plan` scoped to `[start, end]`. People and projects are kept as-is;
    eligibility already restricts variables to each project's PoP intersected with the
    horizon, so an out-of-window project simply contributes no eligible cells."""

    def in_range(m: Month) -> bool:
        return start <= m <= end

    closed_through = plan.closed_through if plan.closed_through and plan.closed_through <= end else None

    return Plan(
        horizon_start=start,
        horizon_end=end,
        people=plan.people,
        projects=plan.projects,
        rate_structures=plan.rate_structures,
        rates=[r for r in plan.rates if in_range(r.month)],
        wrap_rates=[w for w in plan.wrap_rates if in_range(w.month)],
        capacity=[c for c in plan.capacity if in_range(c.month)],
        bounds=[b for b in plan.bounds if in_range(b.month)],
        targets=[t for t in plan.targets if in_range(t.month)],
        allocation=[a for a in plan.allocation if in_range(a.month)],
        closed_through=closed_through,
    )
