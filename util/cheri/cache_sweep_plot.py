#!/usr/bin/env python3
"""Cache-size sweep of one workload, in the style of overhead_bars.py.

Reads cache_sweep.csv (written by cache_sweep_collect.py) and draws, for one
workload, grouped bars per ABI at every simulated point: the left column
sweeps the L2 (L1D at its default), the right column the L1D (L2 at its
default). Rows:
  CPU cycles     % relative to the baseline ABI at the default sizes (the
                 dashed line); purecap's bars carry its overhead over the
                 baseline at the same cache sizes
  L2 misses      absolute count (log scale); purecap's bars carry
                 purecap / baseline at the same cache sizes
  DRAM traffic   bytes read + written, absolute (log scale), same labels
Only simulated points are drawn; nothing is interpolated.

Usage: util/cheri/cache_sweep_plot.py CACHE_SWEEP_CSV --workload NAME
         [--baseline plain] [--out DIR] [--png]
Writes <out>/cache_sweep_<workload>.pdf and a CSV of the plotted values.
Needs matplotlib.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from cache_sweep_collect import DEFAULT, size_bytes  # noqa: E402
from overhead_bars import ABI_NAME, STYLE, legend, style  # noqa: E402

ROWS = [
    ("cycles", "CPU cycles", ["cycles"]),
    ("l2", "L2 misses", ["l2_misses"]),
    ("dram", "DRAM traffic", ["dram_bytes_read", "dram_bytes_written"]),
]


def human(v, unit=""):
    for div, suf in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            return f"{v / div:g}{suf}{unit}"
    return f"{v:g}{unit}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv")
    ap.add_argument("--workload", required=True)
    ap.add_argument("--baseline", default="plain")
    ap.add_argument("--abis", default="plain,hybrid,purecap")
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()

    rows = [r for r in csv.DictReader(open(a.csv))
            if r["workload"] == a.workload]
    if not rows:
        sys.exit(f"no rows for {a.workload} in {a.csv}")
    by = {(r["l1d"], r["l2"], r["abi"]): r for r in rows}
    abis = [x for x in a.abis.split(",") if any(r["abi"] == x for r in rows)]
    d1, d2 = DEFAULT["CHERI_L1D"], DEFAULT["CHERI_L2"]
    cols = [
        (f"L2 size (L1D {d1})", "l2",
         sorted({r["l2"] for r in rows if r["l1d"] == d1}, key=size_bytes)),
        (f"L1D size (L2 {d2})", "l1d",
         sorted({r["l1d"] for r in rows if r["l2"] == d2}, key=size_bytes)),
    ]

    def get(l1d, l2, abi, fields):
        r = by.get((l1d, l2, abi))
        if not r or r["valid"] != "1":
            return None
        return sum(float(r[f]) for f in fields)

    base_cycles = get(d1, d2, a.baseline, ["cycles"])
    if base_cycles is None:
        sys.exit(f"no valid {a.baseline} run at L1D {d1} / L2 {d2}")
    style()
    fig, axs = plt.subplots(
        len(ROWS), 2, figsize=(7.16, 1.65 * len(ROWS)), sharey="row",
        gridspec_kw={"width_ratios": [len(c[2]) for c in cols],
                     "wspace": 0.04, "hspace": 0.12})
    width = 0.8 / len(abis)
    table = []
    for ri, (key, title, fields) in enumerate(ROWS):
        for ci, (ctitle, dim, points) in enumerate(cols):
            ax = axs[ri][ci]
            for xi, p in enumerate(points):
                l1d, l2 = (d1, p) if dim == "l2" else (p, d2)
                b = get(l1d, l2, a.baseline, fields)
                for i, abi in enumerate(abis):
                    v = get(l1d, l2, abi, fields)
                    if v is None:
                        continue
                    y = 100.0 * (v / base_cycles - 1) if key == "cycles" \
                        else v
                    xb = xi - 0.4 + width * (i + 0.5)
                    col, hatch = STYLE[abi]
                    ax.bar(xb, y, width * 0.92, facecolor="white",
                           edgecolor=col, hatch=hatch, linewidth=0.6,
                           zorder=2)
                    rel = v / b if b else None
                    table.append({"workload": a.workload, "metric": title,
                                  "l1d": l1d, "l2": l2, "abi": abi,
                                  "value": v, "plotted": round(y, 4),
                                  f"vs_{a.baseline}_same_size":
                                  round(rel, 4) if rel else ""})
                    if abi == "purecap" and rel and abi != a.baseline:
                        txt = (f"{100 * (rel - 1):+.1f}%" if key == "cycles"
                               else f"{rel:.2f}$\\times$")
                        ax.text(xb, max(y, 0), txt, rotation=90,
                                ha="center", va="bottom", fontsize=5,
                                zorder=4)
            ax.set_xticks(range(len(points)))
            ax.set_xticklabels(
                [p + ("\n(default)" if p == (d2 if dim == "l2" else d1)
                      else "") for p in points]
                if ri == len(ROWS) - 1 else [])
            ax.tick_params(axis="x", length=0)
            ax.set_xlim(-0.6, len(points) - 0.4)
            ax.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
            ax.set_axisbelow(True)
            if ri == 0:
                ax.set_title(f"{a.workload}: {ctitle}", fontsize=7, pad=3)
            if key == "cycles":
                ax.axhline(0, color="#ff0000", linestyle=(0, (4, 2)),
                           linewidth=0.6, zorder=3)
                ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                    lambda v, _: f"{v:+.0f}%"))
            else:
                ax.set_yscale("log")
                ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                    lambda v, _, k=key: human(v, "B" if k == "dram" else "")))
                ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
            if ci == 0:
                same = (f"\n(labels: purecap vs {ABI_NAME[a.baseline]} at "
                        "the same cache sizes)")
                what = {"cycles": f"overheads to {ABI_NAME[a.baseline]} at "
                                  f"L1D {d1}, L2 {d2}" + same,
                        "l2": "count" + same,
                        "dram": "bytes read + written" + same}[key]
                legend(ax, [Patch(facecolor="white", edgecolor=STYLE[x][0],
                                  hatch=STYLE[x][1], label=ABI_NAME[x])
                            for x in abis],
                       f"{title} - {what}", len(abis))
                ax.text(-0.13, 1.0, f"({'abc'[ri]})", transform=ax.transAxes,
                        va="top", ha="right", fontsize=7)
        lo, hi = axs[ri][0].get_ylim()
        if key == "cycles":
            axs[ri][0].set_ylim(min(lo, -0.05 * (hi - lo)),
                                hi + 1.0 * (hi - lo))
        else:  # log: same headroom in decades
            axs[ri][0].set_ylim(lo, hi * (hi / lo) ** 1.0)

    out = a.out or os.path.dirname(os.path.abspath(a.csv))
    os.makedirs(out, exist_ok=True)
    name = f"cache_sweep_{a.workload}"
    fig.savefig(os.path.join(out, f"{name}.pdf"))
    if a.png:
        fig.savefig(os.path.join(out, f"{name}.png"), dpi=300)
    with open(os.path.join(out, f"{name}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"wrote {out}/{name}.pdf, {name}.csv")


if __name__ == "__main__":
    main()
