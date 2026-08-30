"""Builds the proposed `targets` update for review — mirrors solve's dry-run/accept posture.

Never a silent write: `04-solver-design.md`'s Reforecasting section is explicit that this
proposes a starting point for the PM's monthly review, it doesn't replace it.
"""

from dataclasses import dataclass

from allocsolver.models.calendar import Month
from allocsolver.models.plan import Plan

from .redistribute import proportional_share, remaining_open_months
from .variance import target_variance


@dataclass(frozen=True, slots=True)
class ReforecastProposal:
    project_id: str
    closed_month: Month
    variance: float
    updated_targets: dict[Month, float]


def propose_reforecast(plan: Plan, project_id: str, closed_month: Month) -> ReforecastProposal:
    variance = target_variance(plan, project_id, closed_month)
    months = remaining_open_months(plan, project_id, closed_month)
    shares = proportional_share(plan, project_id, variance, months)

    current = {t.month: t.labor_spend_target for t in plan.targets if t.project_id == project_id}
    updated_targets = {m: current.get(m, 0.0) + shares[m] for m in months}

    return ReforecastProposal(
        project_id=project_id,
        closed_month=closed_month,
        variance=variance,
        updated_targets=updated_targets,
    )
