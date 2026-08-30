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
DEFAULT_MIP_GAP = 0.01  # 1 percent — "Performance" in `04-solver-design.md`
