#!/usr/bin/env python3
"""Effect of each hardware prefetcher on one phase, per workload and ABI.

Inputs are results directories of runs with CHERI_STATS_AT_PC phase dumps
(e.g. the prefetch_sweep.sh points), one per prefetcher setting. For every
workload and ABI it takes that phase's cycles (difference of the phase's
stats dumps, see util/cheri/phase_stats.py) and plots the change relative
to the --baseline setting (normally no prefetcher) of the same ABI: one
panel per ABI, one bar per prefetcher, in the style of overhead_bars.py,
plus the geometric mean over the workloads. Negative = faster.

Usage: util/cheri/prefetch_compare_plot.py --set LABEL=DIR [--set ...]
         --baseline LABEL [--phase compute] [--abis purecap,plain]
         [--mode all|user|kernel] [--norm phase|run] [--config minor]
         [--labels startup,build,compute,exit]
         [--out DIR] [--png]
--norm run weights each change by the phase's share of the run:
  impact = (C_pf - C_base) / T_base, C = phase cycles, T = whole-run cycles
of the baseline setting, so a large change of a tiny phase stays small.
LABEL ending in '*' is drawn as is but flagged in the legend (e.g. a run
restored from another checkpoint). Writes prefetch_<phase>.pdf/.csv.
"""

import argparse
import csv
import math
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

STYLES = [("#000000", "xxxx"), ("#7f7f7f", "...."), ("#D55E00", "////"),
          ("#0072B2", "\\\\\\\\\\\\"), ("#009E73", "||||"),
          ("#E69F00", "----"), ("#CC79A7", "++++"), ("#56B4E9", "oo")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", action="append", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--phase", default="compute")
    ap.add_argument("--mode", choices=("all", "user", "kernel"),
                    default="all",
                    help="cycles counted: all, or only user / kernel mode "
                    "(needs CHERI_PRIV_STATS=1 runs)")
    ap.add_argument("--norm", choices=("phase", "run"), default="phase",
                    help="phase: change of the phase's cycles in %% of the "
                    "baseline's phase cycles; run: the same change in %% of "
                    "the baseline's whole-run cycles, i.e. weighted by the "
                    "phase's share of the run (mean instead of geomean)")
    ap.add_argument("--abis", default="purecap,plain")
    ap.add_argument("--config", default="minor")
    ap.add_argument("--labels", default="startup,build,compute,exit")
    ap.add_argument("--out", default=".")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    sets = [s.partition("=")[::2] for s in a.set]
    labels = a.labels.split(",")
    abis = a.abis.split(",")
    base = [d for lbl, d in sets if lbl == a.baseline]
    if not base:
        sys.exit(f"--baseline {a.baseline} is not one of the --set labels")

    cyc, run_cyc = {}, {}
    wls = None
    for lbl, d in sets:
        found = sorted(w for w in os.listdir(d) if all(
            os.path.isdir(os.path.join(d, w, f"{x}-{a.config}"))
            for x in abis))
        wls = found if wls is None else [w for w in wls if w in found]
        for w in found:
            for abi in abis:
                rows = {r["phase"]: r for r in phase_stats.phases(
                    os.path.join(d, w, f"{abi}-{a.config}"), labels)}
                key = {"all": "cycles", "user": "user_cycles",
                       "kernel": "supervisor_cycles"}[a.mode]
                cyc[(lbl, abi, w)] = rows[a.phase][key]
                run_cyc[(lbl, abi, w)] = rows["total"]["cycles"]
    series = [lbl for lbl, _ in sets if lbl != a.baseline]

    table = []
    style()
    fig, axs = plt.subplots(len(abis), 1, figsize=(7.16, 2.3 * len(abis)),
                            sharex=True, gridspec_kw={"hspace": 0.12})
    axs = [axs] if len(abis) == 1 else axs
    summary = "geomean" if a.norm == "phase" else "mean"
    groups = wls + [summary]
    width = 0.84 / len(series)
    for ax, abi in zip(axs, abis):
        for i, lbl in enumerate(series):
            col, hatch = STYLES[i % len(STYLES)]
            vals = []
            for x, w in enumerate(groups):
                if w == summary:
                    if a.norm == "phase":
                        v = 100 * (math.exp(sum(math.log(1 + u / 100)
                                                for u in vals)
                                            / len(vals)) - 1)
                    else:
                        v = sum(vals) / len(vals)
                else:
                    c, cb = cyc[(lbl, abi, w)], cyc[(a.baseline, abi, w)]
                    tb = run_cyc[(a.baseline, abi, w)]
                    # phase: (C - C_base) / C_base; run: (C - C_base) / T_base
                    v = 100 * (c - cb) / (cb if a.norm == "phase" else tb)
                    vals.append(v)
                    table.append({"abi": abi, "workload": w, "prefetcher":
                                  lbl, "phase": a.phase,
                                  "mode": a.mode, "norm": a.norm,
                                  "cycles": c, "baseline_cycles": cb,
                                  "baseline_run_cycles": tb,
                                  "phase_share_of_run_pct":
                                  round(100 * cb / tb, 3),
                                  "change_pct": round(v, 3)})
                ax.bar(x - 0.42 + width * (i + 0.5), v,
                       width * 0.9, facecolor="white", edgecolor=col,
                       hatch=hatch, linewidth=0.6, zorder=2)
            table.append({"abi": abi, "workload": summary,
                          "prefetcher": lbl, "phase": a.phase,
                          "mode": a.mode, "norm": a.norm,
                          "cycles": "", "baseline_cycles": "",
                          "baseline_run_cycles": "",
                          "phase_share_of_run_pct": "",
                          "change_pct": round(v, 3)})
        ax.axhline(0, color="#ff0000", linestyle=(0, (4, 2)),
                   linewidth=0.6, zorder=3)
        ax.axvline(len(wls) - 0.5, color="#9a9a9a", linewidth=0.6,
                   zorder=1)
        ax.set_xlim(-0.6, len(groups) - 0.4)
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels(groups, rotation=90)
        ax.tick_params(axis="x", length=0)
        ax.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
        lo, hi = ax.get_ylim()
        hi = max(hi, 0.0)
        ax.set_ylim(lo, hi + 0.5 * (hi - lo))  # room for the legend
        what = (f"{a.phase}-phase "
                f"{'' if a.mode == 'all' else a.mode + '-mode '}cycles")
        title = (f"{ABI_NAME[abi]}: {what} - change vs {a.baseline} "
                 "(same ABI)" if a.norm == "phase" else
                 f"{ABI_NAME[abi]}: change in {what}, % of the whole run "
                 f"with {a.baseline}")
        legend(ax, [Patch(facecolor="white",
                          edgecolor=STYLES[i % len(STYLES)][0],
                          hatch=STYLES[i % len(STYLES)][1], label=lbl)
                    for i, lbl in enumerate(series)], title, 4)
        if a.norm == "run":
            # each workload's phase share of the run (baseline), under the axis
            for x, w in enumerate(wls):
                share = 100 * cyc[(a.baseline, abi, w)] / \
                    run_cyc[(a.baseline, abi, w)]
                lo_, hi_ = ax.get_ylim()
                ax.text(x, 0.04 * (hi_ - lo_), f"{share:.0f}%", ha="center",
                        va="bottom", fontsize=5, color="#555555", zorder=4)
            ax.text(-0.5, 0.11 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
                    f"compute share of the run ({a.baseline}):", ha="left",
                    va="bottom", fontsize=5, color="#555555")
    for t, ax in zip("abcd", axs):
        ax.text(0.995, 0.96, f"({t})", transform=ax.transAxes, va="top",
                ha="right", fontsize=7)
    os.makedirs(a.out, exist_ok=True)
    name = (f"prefetch_{a.phase}" + ("" if a.mode == "all" else f"_{a.mode}")
            + ("" if a.norm == "phase" else "_of_run"))
    fig.savefig(os.path.join(a.out, f"{name}.pdf"))
    if a.png:
        fig.savefig(os.path.join(a.out, f"{name}.png"), dpi=300)
    with open(os.path.join(a.out, f"{name}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"wrote {a.out}/{name}.pdf, {name}.csv")


if __name__ == "__main__":
    main()
