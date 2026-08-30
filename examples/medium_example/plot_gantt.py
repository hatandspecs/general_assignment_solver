#!/usr/bin/env python
"""Gantt-style portfolio timeline for the medium example.

Projects, one per row, ordered chronologically by PoP start (which is also their
numbering order — project_1 starts earliest), their PoP as horizontal bars,
year-month across the top X axis, with vertical reference lines for UFY wrap-rate
changes (July 1) and October salary increases.

    python plot_gantt.py [--out portfolio_gantt.png]

Requires the `viz` extra: `pip install -e '.[viz]'` (or just `matplotlib`, already
in `environment.yml`).
"""

import argparse
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from allocsolver.io.local import load_plan
from allocsolver.models.calendar import Month

DATA_DIR = Path(__file__).parent / "data"

RATE_TYPE_COLORS = {
    "project": "#4a90d9",  # direct
    "oh": "#c87f3f",
    "fee": "#4fa86f",
}


def _month_start(m: Month) -> date:
    return date(m.year, m.month, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "portfolio_gantt.png")
    args = parser.parse_args()

    plan = load_plan(DATA_DIR)
    projects = sorted(plan.projects, key=lambda p: p.pop_start)

    fig_height = max(6.0, 0.22 * len(projects))
    fig, ax = plt.subplots(figsize=(18, fig_height))

    for row_idx, p in enumerate(projects):
        start = mdates.date2num(_month_start(p.pop_start))
        end_exclusive = mdates.date2num(_month_start(p.pop_end.add(1)))
        structure = plan.rate_structure(p.rate_structure)
        color = RATE_TYPE_COLORS.get(structure.rate_type.value, "#888888")
        ax.broken_barh(
            [(start, end_exclusive - start)],
            (row_idx - 0.4, 0.8),
            facecolors=color,
            edgecolors="white",
            linewidth=0.6,
        )

    ax.set_yticks(range(len(projects)))
    ax.set_yticklabels([p.name for p in projects], fontsize=8)
    ax.set_ylim(len(projects), -1)  # earliest-starting project at the top

    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="left", fontsize=8)

    horizon_start = mdates.date2num(_month_start(plan.horizon_start))
    horizon_end = mdates.date2num(_month_start(plan.horizon_end.add(1)))
    ax.set_xlim(horizon_start, horizon_end)

    # Vertical reference lines: UFY wrap-rate changes (July 1) and salary raises (Oct 1).
    for year in range(plan.horizon_start.year, plan.horizon_end.year + 2):
        july_num = mdates.date2num(date(year, 7, 1))
        oct_num = mdates.date2num(date(year, 10, 1))
        if horizon_start <= july_num <= horizon_end:
            ax.axvline(july_num, color="crimson", linestyle="--", linewidth=1, alpha=0.75, zorder=0)
        if horizon_start <= oct_num <= horizon_end:
            ax.axvline(oct_num, color="seagreen", linestyle=":", linewidth=1.2, alpha=0.75, zorder=0)

    legend_elements = [
        Patch(facecolor=RATE_TYPE_COLORS["project"], label="direct"),
        Patch(facecolor=RATE_TYPE_COLORS["oh"], label="oh_charged"),
        Patch(facecolor=RATE_TYPE_COLORS["fee"], label="fee_charged"),
        Line2D([0], [0], color="crimson", linestyle="--", label="UFY wrap-rate change (Jul 1)"),
        Line2D([0], [0], color="seagreen", linestyle=":", label="Salary increases (Oct 1)"),
    ]
    ax.legend(handles=legend_elements, loc="upper center", bbox_to_anchor=(0.5, -0.015), ncol=5, fontsize=8)

    ax.set_title("Medium Example: Project Portfolio Timeline", pad=70)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
