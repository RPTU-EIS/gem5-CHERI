#!/usr/bin/env python3
"""Checkpoint-restored vs booted-from-scratch runs of the same experiment.

Compares, per workload and ABI, the region statistics of runs restored from
a checkpoint (cold caches, TLBs and predictor at the region start) with
runs that booted CheriBSD in the same simulation (warm state from the boot).
Every value is a ratio of two gem5 statistics. Figures (overhead_bars.py
style):
  boot_vs_ckpt_metrics.pdf   % difference boot vs checkpoint of cycles,
                             instructions, L1D/L2/dTLB misses and DRAM
                             traffic; optional grey band: the cycle
                             difference between two checkpoint runs
                             (--noise A=results.csv,B=results.csv), i.e.
                             what two different guest states give anyway
  boot_vs_ckpt_overhead.pdf  ABI overhead (--abi vs --baseline) in both modes
  boot_vs_ckpt_time.pdf      host seconds per run: the region and the rest
                             (restore or boot), with the one-off checkpoint
                             creation cost in the legend

Usage: util/cheri/boot_vs_ckpt_plot.py --suite LABEL=CKPT_CSV,BOOT_CSV
         [--suite ...] [--noise CKPT_A_CSV,CKPT_B_CSV]
         [--ckpt-cost LABEL=SECONDS ...] [--config minor]
         [--abi purecap --baseline plain] [--out DIR] [--png]
Writes the three PDFs and boot_vs_ckpt.csv.
"""

import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from overhead_bars import (ABI_NAME, SHORT, STYLE, legend, panel,  # noqa
                           style, x_layout, finish_x)

METRICS = [  # key, label, columns, colour, hatch
    ("cycles", "CPU cycles", ["cycles"], "#000000", "xxxx"),
    ("insts", "Instructions", ["insts"], "#0072B2", "////"),
    ("l1d", "L1D misses", ["l1d_misses"], "#E69F00", "\\\\\\\\\\\\"),
    ("l2", "L2 misses", ["l2_misses"], "#D55E00", "||||"),
    ("dtlb", "dTLB misses", ["dtlb_misses"], "#CC79A7", "++++"),
    ("dram", "DRAM traffic", ["dram_bytes_read", "dram_bytes_written"],
     "#009E73", "----"),
]


def load(path, config):
    rows = {}
    for r in csv.DictReader(open(path)):
        if r["config"] == config and str(r["status"]) == "0" and \
                str(r.get("errors", "0")) in ("0", ""):
            rows[(r["abi"], r["workload"])] = r
    return rows


def val(r, cols):
    return sum(float(r[c]) for c in cols)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--suite", action="append", required=True)
    ap.add_argument("--noise")
    ap.add_argument("--ckpt-cost", action="append", default=[])
    ap.add_argument("--config", default="minor")
    ap.add_argument("--abi", default="purecap")
    ap.add_argument("--baseline", default="plain")
    ap.add_argument("--out", default=".")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    abis = [a.abi, a.baseline]
    style()
    os.makedirs(a.out, exist_ok=True)

    suites, groups = [], []
    for s in a.suite:
        lbl, _, paths = s.partition("=")
        ck, bt = [load(p, a.config) for p in paths.split(",")]
        wls = sorted({w for (_, w) in bt if all((x, w) in ck and (x, w) in bt
                                                for x in abis)},
                     key=lambda w: SHORT.get(w, w))
        suites.append((lbl, ck, bt, wls))
        groups.append(("", [("", w) for w in wls]))

    noise = None
    if a.noise:
        na, nb = [load(p, a.config) for p in a.noise.split(",")]
        diffs = [100 * (val(nb[k], ["cycles"]) / val(na[k], ["cycles"]) - 1)
                 for k in na if k in nb and k[0] in abis]
        noise = (min(diffs), max(diffs))

    table = []

    def save(fig, name):
        fig.savefig(os.path.join(a.out, f"{name}.pdf"))
        if a.png:
            fig.savefig(os.path.join(a.out, f"{name}.png"), dpi=300)
        plt.close(fig)

    def separators(ax):
        x = 0.0
        for gi, (lbl, _, _, wls) in enumerate(suites):
            if gi:
                x += 0.5
            ax.text(x - 0.4, 1.01, lbl, transform=ax.get_xaxis_transform(),
                    fontsize=6.5, ha="left", va="bottom", color="#333333")
            x += len(wls)

    # 1. metric differences, one panel per ABI
    fig, axs = plt.subplots(2, 1, figsize=(7.16, 4.6), sharex=True,
                            gridspec_kw={"hspace": 0.1})
    for ax, abi in zip(axs, abis):
        data = {}
        for lbl, ck, bt, wls in suites:
            for w in wls:
                for key, mlbl, cols, *_ in METRICS:
                    c, b = val(ck[(abi, w)], cols), val(bt[(abi, w)], cols)
                    d = 100 * (b / c - 1) if c else 0.0
                    data[(key, ("", w))] = d
                    table.append({"figure": "metrics", "suite": lbl,
                                  "workload": w, "abi": abi, "metric": key,
                                  "checkpoint": c, "boot": b,
                                  "diff_pct": round(d, 3)})
        panel(ax, groups, data, [(k, l, c, h) for k, l, _, c, h in METRICS],
              f"{ABI_NAME[abi]}: booted from scratch vs restored from a "
              "checkpoint (% difference)",
              show_xlabels=(ax is axs[-1]), legend_cols=6)
        if noise:
            ax.axhspan(noise[0], noise[1], color="#d9d9d9", zorder=0, lw=0)
            ax.text(0.995, 0.03, f"grey: cycles, two checkpoints "
                    f"({noise[0]:+.2f}% to {noise[1]:+.2f}%)",
                    transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=5, color="#555555")
        separators(ax)
    save(fig, "boot_vs_ckpt_metrics")

    # 2. ABI overhead in both modes
    fig, ax = plt.subplots(figsize=(7.16, 2.4))
    data = {}
    for lbl, ck, bt, wls in suites:
        for w in wls:
            for mode, rows in (("ckpt", ck), ("boot", bt)):
                o = 100 * (val(rows[(a.abi, w)], ["cycles"]) /
                           val(rows[(a.baseline, w)], ["cycles"]) - 1)
                data[(mode, ("", w))] = o
                table.append({"figure": "overhead", "suite": lbl,
                              "workload": w, "abi": a.abi, "metric":
                              f"overhead_vs_{a.baseline}_{mode}",
                              "checkpoint": "", "boot": "",
                              "diff_pct": round(o, 3)})
    panel(ax, groups, data,
          [("ckpt", "restored from a checkpoint", STYLE[a.abi][0], "\\\\\\"),
           ("boot", "booted from scratch", "#0072B2", "////")],
          f"{ABI_NAME[a.abi]} CPU cycles - overhead to "
          f"{ABI_NAME[a.baseline]}", legend_cols=2)
    separators(ax)
    save(fig, "boot_vs_ckpt_overhead")

    # 3. host time per run
    cost = dict(c.partition("=")[::2] for c in a.ckpt_cost)
    fig, ax = plt.subplots(figsize=(7.16, 2.6))
    pos, gaps, end = x_layout(groups)
    series = [(m, abi) for m in ("ckpt", "boot") for abi in abis]
    width = 0.8 / len(series)
    cols = {("ckpt", a.abi): "#ff1f1f", ("ckpt", a.baseline): "#008000",
            ("boot", a.abi): "#b30000", ("boot", a.baseline): "#004d00"}
    flat = [(lbl, ck, bt) for lbl, ck, bt, wls in suites for _ in wls]
    for (x, (_, w)), (lbl, ck, bt) in zip(pos, flat):
        for i, (mode, abi) in enumerate(series):
            r = (ck if mode == "ckpt" else bt)[(abi, w)]
            region = float(r["host_seconds"]) / 3600
            total = float(r["run_wall_seconds"]) / 3600
            xb = x - 0.4 + width * (i + 0.5)
            col = cols[(mode, abi)]
            ax.bar(xb, region, width * 0.9, facecolor="white",
                   edgecolor=col, hatch="////" if mode == "ckpt" else "xxxx",
                   linewidth=0.6, zorder=2)
            ax.bar(xb, total - region, width * 0.9, bottom=region,
                   facecolor="#eeeeee", edgecolor=col, linewidth=0.6,
                   zorder=2)
            table.append({"figure": "time", "suite": lbl, "workload": w,
                          "abi": abi, "metric": f"host_hours_{mode}",
                          "checkpoint": "", "boot": "",
                          "diff_pct": round(total, 4)})
    finish_x(ax, pos, gaps, end, True)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g} h"))
    lo, hi = ax.get_ylim()
    ax.set_ylim(0, hi * 1.55)
    hs = [Patch(facecolor="white", edgecolor=cols[(m, abi)],
                hatch="////" if m == "ckpt" else "xxxx",
                label=f"{ABI_NAME[abi]}, "
                f"{'checkpoint' if m == 'ckpt' else 'boot'}")
          for m, abi in series]
    hs.append(Patch(facecolor="#eeeeee", edgecolor="#555555",
                    label="outside the region (restore or boot)"))
    once = ", ".join(f"{k} {float(v) / 3600:.2f} h" for k, v in cost.items())
    legend(ax, hs, "Host time per run (hatched: the measured region)"
           + (f"; one-off checkpoint creation: {once}" if once else ""), 3)
    separators(ax)
    save(fig, "boot_vs_ckpt_time")

    with open(os.path.join(a.out, "boot_vs_ckpt.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"wrote {a.out}/boot_vs_ckpt_{{metrics,overhead,time}}.pdf, "
          "boot_vs_ckpt.csv")


if __name__ == "__main__":
    main()
