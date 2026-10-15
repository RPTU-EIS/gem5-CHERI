#!/usr/bin/env python3
"""Where an ABI's extra cycles go: phases x privilege modes, per workload.

For runs made with CHERI_PRIV_STATS=1 and CHERI_STATS_AT_PC phase dumps
(see util/cheri/olden/README.md), draws one stacked bar per workload in the
style of overhead_bars.py: the ABI's cycle overhead over the baseline ABI
(% of the baseline's cycles), split into kernel and user cycles of the
build and compute phases, plus startup + exit. Components that are
negative stack below zero. Values are differences of gem5 statistics.

Usage: util/cheri/phase_plot.py RESULTS_DIR [--abi purecap]
         [--baseline plain] [--config minor] [--out DIR] [--png]
RESULTS_DIR holds <workload>/<abi>-<config>/ runs. Writes
phase_breakdown.pdf and phase_breakdown.csv. Needs matplotlib.
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

import phase_stats  # noqa: E402
from overhead_bars import ABI_NAME, legend, style  # noqa: E402

LABELS = ["startup", "build", "compute", "exit"]
PARTS = [  # key, label, colour, hatch
    ("build_k", "build, kernel", "#D55E00", "\\\\\\\\\\\\"),
    ("build_u", "build, user", "#E69F00", "////"),
    ("compute_k", "compute, kernel", "#0072B2", "xxxx"),
    ("compute_u", "compute, user", "#56B4E9", "...."),
    ("other", "startup + exit", "#7f7f7f", ""),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("results")
    ap.add_argument("--abi", default="purecap")
    ap.add_argument("--baseline", default="plain")
    ap.add_argument("--config", default="minor")
    ap.add_argument("--out")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    out = a.out or os.path.join(a.results, "plots")
    os.makedirs(out, exist_ok=True)

    rows, table = {}, []
    for wl in sorted(os.listdir(a.results)):
        runs = [os.path.join(a.results, wl, f"{x}-{a.config}")
                for x in (a.baseline, a.abi)]
        if not all(os.path.isdir(r) for r in runs):
            continue
        base, abi = [{r["phase"]: r for r in phase_stats.phases(r, LABELS)}
                     for r in runs]
        tot = base["total"]["cycles"]

        def d(phase, key):
            return 100.0 * (abi[phase][key] - base[phase][key]) / tot

        v = {
            "build_k": d("build", "supervisor_cycles"),
            "build_u": d("build", "user_cycles"),
            "compute_k": d("compute", "supervisor_cycles"),
            "compute_u": d("compute", "user_cycles"),
            "other": d("startup", "cycles") + d("exit", "cycles"),
        }
        v["total"] = d("total", "cycles")
        rows[wl] = v
        table.append(dict({"workload": wl, "abi": a.abi,
                           "baseline": a.baseline,
                           "baseline_cycles": tot},
                          **{k: round(x, 3) for k, x in v.items()}))
    if not rows:
        sys.exit(f"no {a.baseline}/{a.abi}-{a.config} run pairs found")

    style()
    wls = list(rows)
    fig, ax = plt.subplots(figsize=(7.16, 2.6))
    for x, wl in enumerate(wls):
        pos = neg = 0.0
        for key, _, col, hatch in PARTS:
            h = rows[wl][key]
            bottom = pos if h >= 0 else neg
            ax.bar(x, h, 0.6, bottom=bottom, facecolor="white",
                   edgecolor=col, hatch=hatch, linewidth=0.6, zorder=2)
            if h >= 0:
                pos += h
            else:
                neg += h
        t = rows[wl]["total"]
        ax.text(x, max(pos, 0) + 1.5, f"{t:+.1f}%", ha="center",
                va="bottom", fontsize=5.5, rotation=90)
    ax.axhline(0, color="#ff0000", linestyle=(0, (4, 2)), linewidth=0.6,
               zorder=3)
    ax.set_xticks(range(len(wls)))
    ax.set_xticklabels(wls, rotation=90)
    ax.set_xlim(-0.6, len(wls) - 0.4)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo, hi + 0.55 * (hi - lo))
    legend(ax, [Patch(facecolor="white", edgecolor=c, hatch=h, label=lbl)
                for _, lbl, c, h in PARTS],
           f"{ABI_NAME[a.abi]} CPU cycles - overhead to "
           f"{ABI_NAME[a.baseline]} by phase and privilege mode", 3)
    fig.savefig(os.path.join(out, "phase_breakdown.pdf"))
    if a.png:
        fig.savefig(os.path.join(out, "phase_breakdown.png"), dpi=300)
    with open(os.path.join(out, "phase_breakdown.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"wrote {out}/phase_breakdown.pdf, phase_breakdown.csv")


if __name__ == "__main__":
    main()
