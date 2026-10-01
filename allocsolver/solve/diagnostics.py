"""Binding-constraint report, IIS wrapper — `04-solver-design.md`, "Infeasibility diagnostics"."""

from ortools.linear_solver import pywraplp

from allocsolver.models.plan import Plan

from .elastic import build_elastic_model
from .locks import lock_conflicts
from .result import BindingSlack, DiagnosticsReport


def diagnose(plan: Plan) -> DiagnosticsReport:
    """Nonzero slacks in the elastic model are exactly what had to break.

    Lock conflicts are computed first and reported alongside, because the elastic
    model re-pins locked cells verbatim and so can be infeasible itself when the locks
    are the problem — in which case the slack half of this report comes back empty and
    `locks.py` is the only half that has anything to say. See that module's docstring.
    """
    conflicts = lock_conflicts(plan)
    bundle = build_elastic_model(plan)
    status = bundle.solver.Solve()
    binding: list[BindingSlack] = []

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        # The relaxation itself didn't solve — locks pinned into it are the usual
        # reason, and `conflicts` is what names them.
        return DiagnosticsReport(binding=[], lock_conflicts=conflicts)

    for cell, var in bundle.s_hmin.items():
        if var.solution_value() > 1e-6:
            p, w, m = cell
            binding.append(BindingSlack("hard_min", p, w, str(m), -var.solution_value(), "hard_min unmet"))
    for cell, var in bundle.s_hmax.items():
        if var.solution_value() > 1e-6:
            p, w, m = cell
            binding.append(BindingSlack("hard_max", p, w, str(m), var.solution_value(), "hard_max exceeded"))
    for (w, m), var in bundle.s_cap.items():
        if var.solution_value() > 1e-6:
            binding.append(
                BindingSlack("capacity", None, w, str(m), var.solution_value(), "over available capacity")
            )
    for (proj, m), var in bundle.s_target.items():
        if var.solution_value() > 1e-6:
            binding.append(
                BindingSlack("hard_target", proj, None, str(m), var.solution_value(), "hard target exceeded")
            )

    return DiagnosticsReport(binding=binding, lock_conflicts=conflicts)


def iis(plan: Plan) -> str:
    """`--iis`: an irreducible infeasible subsystem via SCIP directly.

    Resolved in `04-solver-design.md`/`06-code-structure-and-dependencies.md`: OR-Tools'
    generic `MPSolver` wrapper doesn't expose SCIP's native IIS extraction, so this path
    requires the optional `PySCIPOpt` dependency (extra `[iis]`) rather than reusing the
    default solve path.
    """
    try:
        import pyscipopt  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "`--iis` requires the optional PySCIPOpt dependency (`pip install allocsolver[iis]`)"
        ) from exc
    raise NotImplementedError("IIS extraction via PySCIPOpt is analyst tooling, not yet implemented")
