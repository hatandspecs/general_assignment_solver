"""Settings, env, weight defaults (`06-code-structure-and-dependencies.md`)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Weights:
    """Suggested starting weights — `04-solver-design.md`, "Objective"."""

    target: float = 100.0
    soft: float = 10.0
    frag: float = 8.0
    churn: float = 5.0
    idle: float = 3.0
    headcount: float = 1.0


DEFAULT_TIME_LIMIT_SECONDS = 300
DEFAULT_MIP_GAP = 0.01  # 1 percent — 'Performance' in `04-solver-design.md`


# How hard the solver tries to keep the planner's ballpark, as churn weights.
#
# The churn term is distance from `solve(baseline=...)`, so with a working assignment
# passed as the baseline it *is* the "follow my ballpark" term — but the default weight
# of 5 is calibrated for revision-to-revision stability between two solver outputs, not
# for following a hand-built assignment, and at that weight it mostly only breaks ties.
# Measured on `tests/fixtures.two_person_two_project_plan` with a four-cell ballpark
# (L1 distance from the ballpark, in hours):
#
#     churn=0    313h   a mirror-image plan — the "equally optimal but different every
#                       run" instability `AGENTS.md` calls out
#     churn=5    113h   same assignment a baseline-less solve returns; the ballpark
#                       picked the orientation and nothing else
#     churn=25    87h   starts following the shape
#     churn=100   87h
#     churn=500    0h   reproduces the ballpark exactly — and overshoots that month's
#                       spend target by ~40% to do it
#
# That last row is the trade-off the dial exists to expose: past a point, adherence is
# bought with the spend targets this tool exists to hit. `EXACT` is for answering "is my
# ballpark even reachable", not for producing a plan to send out.
ADHERENCE_CHURN_WEIGHTS: dict[str, float] = {
    "free": 5.0,
    "loose": 25.0,
    "close": 100.0,
    "exact": 500.0,
}
DEFAULT_ADHERENCE = "loose"
"""`loose`, not `free`: a planner who has just imported a ballpark and pressed Solve
means for it to be followed. `free` reproduces the pre-ballpark behavior exactly."""


def weights_for_adherence(adherence: str = DEFAULT_ADHERENCE) -> Weights:
    """`Weights` with `churn` set from a named adherence level. Raises `KeyError` with
    the valid names on an unknown one, so a bad API query string says what to pass."""
    try:
        churn = ADHERENCE_CHURN_WEIGHTS[adherence]
    except KeyError:
        raise KeyError(
            f"unknown adherence {adherence!r}; expected one of {', '.join(ADHERENCE_CHURN_WEIGHTS)}"
        ) from None
    return Weights(churn=churn)
