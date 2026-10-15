#!/usr/bin/env python3
"""Per-benchmark overhead bar charts in the style of Joannou's thesis
(UCAM-CL-TR-936, Figures 4.10-4.15): hatched grouped bars, one per ABI,
showing each metric as a percentage overhead relative to a baseline ABI
(plain RV64 by default), with a dashed zero line.

Metrics (one panel each), all read from results.csv written by parse.py:
  (a) data memory accesses   L1D accesses issued by the pipeline (gem5 counts
                             accesses, not bytes; the thesis' Fig. 4.10 plots
                             bytes fetched)
  (b) L1 Dcache misses       (c) L2 cache misses
  (d) DRAM traffic           bytes read + written at the memory controllers
  (e) instructions           (f) CPU cycles

Two more figures:
  instmix.pdf           dynamic instruction mix by gem5 op class, one
                        stacked bar per ABI and workload, as % of the
                        baseline's instruction count (dashed line: 100%)
  <abi>_overheads.pdf   one ABI (--summary-abi, default purecap): all six
                        metrics side by side per workload, vs the baseline

Usage:
  util/cheri/overhead_bars.py [--config minor] [--baseline plain]
      [--group LABEL=RESULTS_DIR ...] [--out DIR] [--png] RESULTS_DIR ...
Plain RESULTS_DIR arguments form one unnamed group; --group adds named
groups separated by a gap (e.g. CoreMark-PRO and Olden), as the thesis
separates MiBench, Octane and Olden. Writes overheads.pdf (all panels),
one PDF per metric, instmix.pdf and <abi>_overheads.pdf, plus CSVs with
every plotted value (overheads.csv, instmix.csv). Each run is
a single deterministic simulation, so there are no error bars.
Needs matplotlib and numpy.
"""

import argparse
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

METRICS = [
    ("accesses", "Data memory accesses", ["l1d_accesses"]),
    ("l1d", "L1 Dcache misses", ["l1d_misses"]),
    ("l2", "L2 cache misses", ["l2_misses"]),
    ("dram", "DRAM traffic", ["dram_bytes_read", "dram_bytes_written"]),
    ("insts", "Instructions", ["insts"]),
    ("cycles", "CPU cycles", ["cycles"]),
]
ABI_NAME = {"plain": "plain RV64", "hybrid": "Hybrid", "purecap": "Purecap"}
# Thesis style: white bars, coloured hatching, one hatch direction per series.
STYLE = {"hybrid": ("#1f1fff", "///"), "purecap": ("#ff1f1f", "\\\\\\"),
         "plain": ("#008000", "xxx")}
# purecap summary: one colour + hatch per metric (Okabe-Ito colours; the
# hatch keeps them apart in greyscale and for colour-blind readers)
METRIC_STYLE = {
    "cycles": ("CPU cycles", "#000000", "xxxx"),
    "insts": ("Instructions", "#0072B2", "////"),
    "accesses": ("Data mem. accesses", "#009E73", "...."),
    "l1d": ("L1D misses", "#E69F00", "\\\\\\\\"),
    "l2": ("L2 misses", "#D55E00", "||||"),
    "dram": ("DRAM traffic", "#CC79A7", "----"),
}
# instruction mix: gem5 commit op classes (capability loads/stores are
# MemRead/MemWrite; CHERI ALU instructions such as cincoffset are IntAlu)
INST_CLASSES = [
    ("Int ALU", ["inst_IntAlu"], "#0072B2", "////"),
    ("Int mul/div", ["inst_IntMult", "inst_IntDiv"], "#D55E00", "xxxx"),
    ("FP arith.", ["inst_FloatAdd", "inst_FloatCmp", "inst_FloatCvt",
                   "inst_FloatMult", "inst_FloatMultAcc", "inst_FloatDiv",
                   "inst_FloatMisc", "inst_FloatSqrt"], "#009E73", "...."),
    ("Int/cap load", ["inst_MemRead"], "#E69F00", "\\\\\\\\"),
    ("Int/cap store", ["inst_MemWrite"], "#CC79A7", "||||"),
    ("FP load", ["inst_FloatMemRead"], "#56B4E9", "----"),
    ("FP store", ["inst_FloatMemWrite"], "#999999", "++++"),
    ("Other", ["inst_No_OpClass"], "#000000", ""),
]
ABI_LETTER = {"plain": "P", "hybrid": "H", "purecap": "C"}
SHORT = {
    "cjpeg-rose7-preset": "cjpeg", "linear_alg-mid-100x100-sp": "linear_alg",
    "loops-all-mid-10k-sp": "loops", "nnet_test": "nnet",
    "parser-125k": "parser", "radix2-big-64k": "radix2", "sha-test": "sha",
    "zip-test": "zip",
}


def load(dirs, config):
    rows = {}
    for d in dirs:
        with open(os.path.join(d, "results.csv")) as f:
            for r in csv.DictReader(f):
                if r.get("config") != config:
                    continue
                if str(r.get("status")) != "0" or str(
                        r.get("errors", "0")) not in ("0", ""):
                    print(f"skipping failed run {r['abi']} {r['workload']}",
                          file=sys.stderr)
                    continue
                rows[(r["abi"], r["workload"])] = r
    return rows


def value(r, cols):
    try:
        return sum(float(r[c]) for c in cols)
    except (KeyError, TypeError, ValueError):
        return None


def style():
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["cmr10", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "axes.formatter.use_mathtext": True,
        "axes.unicode_minus": False,
        "font.size": 7,
        "axes.linewidth": 0.6,
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "legend.fontsize": 6,
        "hatch.linewidth": 0.6,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })


def label(wl):
    """Tick label of a (group, workload) key; cmr10 has no underscore."""
    name = SHORT.get(wl[1], wl[1]).replace("_", "-")
    return f"{wl[0]}-{name}" if wl[0] else name


def axis_cut(values, clip):
    """Top of the y axis when a few bars (at most 3) exceed CLIP times the
    rest and would flatten them; None to show everything."""
    vals = sorted((abs(v) for v in values), reverse=True)
    if not clip:
        return None
    for k in range(1, min(4, len(vals))):
        if vals[k] > 0 and vals[k - 1] > clip * vals[k]:
            return vals[k] * 1.6
    return None


def legend(ax, handles, title, ncol):
    leg = ax.legend(handles=handles, loc="upper left", ncol=ncol,
                    title=title, title_fontsize=6, frameon=True,
                    fancybox=False, edgecolor="#bbbbbb", borderpad=0.3,
                    handlelength=2.2, columnspacing=1.0)
    leg.get_frame().set_linewidth(0.5)
    return leg


def x_layout(groups):
    """x position of every workload; groups are separated by half a slot.
    Returns ([(x, wl)], [gap x], right end)."""
    x, pos, gaps = 0.0, [], []
    for gi, (_, wls) in enumerate(groups):
        if gi:
            gaps.append(x - 0.25)
            x += 0.5
        for wl in wls:
            pos.append((x, wl))
            x += 1.0
    return pos, gaps, x


def finish_x(ax, pos, gaps, end, show_xlabels):
    for g in gaps:
        ax.axvline(g, color="#9a9a9a", linewidth=4, alpha=0.6, zorder=1)
    ax.set_xlim(-0.6, end - 0.4)
    ax.set_xticks([x for x, _ in pos])
    ax.set_xticklabels([label(wl) for _, wl in pos] if show_xlabels else [],
                       rotation=90)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)


def panel(ax, groups, data, series, title, show_xlabels=True, clip=2.5,
          legend_cols=None, ymax=None):
    """Grouped bars: per workload one white, hatched bar per series.
    series: [(key, label, colour, hatch)]; data[(key, wl)] = overhead %.

    Bars far above the rest (see axis_cut) are cut at the top of the axis,
    with a break mark and their value printed (as the thesis does). With
    YMAX the axis ends there and bars above YMAX/1.5 are cut instead."""
    width = 0.8 / len(series)
    if ymax:
        top = ymax / 1.5 if max(data.values()) > ymax / 1.5 else None
    else:
        top = axis_cut(data.values(), clip)
    pos, gaps, end = x_layout(groups)
    clipped_x = []
    for x, wl in pos:
        for i, (key, _, col, hatch) in enumerate(series):
            v = data.get((key, wl))
            if v is None:
                continue
            xb = x - 0.4 + width * (i + 0.5)
            h = v if top is None or v <= top else top
            if h != v:
                clipped_x.append(xb)
            ax.bar(xb, h, width * 0.92, facecolor="white", edgecolor=col,
                   hatch=hatch, linewidth=0.6, zorder=2)
            if h != v:
                # break mark: a white gap across the bar between two strokes
                w2, y0, gap = width * 0.6, top * 0.82, top * 0.05
                ax.fill_between([xb - w2, xb + w2], [y0 - gap / 2, y0],
                                [y0 + gap / 2, y0 + gap], color="white",
                                zorder=3)
                for yy in (y0 - gap / 2, y0 + gap / 2):
                    ax.plot([xb - w2, xb + w2], [yy, yy + gap / 2],
                            color=col, linewidth=0.6, zorder=4)
                ax.text(xb, top * 1.01, f"{v:+.0f}%", ha="center",
                        va="bottom", rotation=90, fontsize=5, zorder=4)
    ax.axhline(0, color="#ff0000", linestyle=(0, (4, 2)), linewidth=0.6,
               zorder=3)
    finish_x(ax, pos, gaps, end, show_xlabels)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
    leg = legend(ax, [Patch(facecolor="white", edgecolor=col, hatch=hatch,
                            label=lbl) for _, lbl, col, hatch in series],
                 title, legend_cols or len(series))
    # keep a clipped bar's value label clear of the legend box
    if any(cx < 0.45 * end for cx in clipped_x) and \
            not any(cx > 0.55 * end for cx in clipped_x):
        leg.set_loc("upper right")
        ax.legend_right = True  # panel letters go top-left instead
    lo, hi = ax.get_ylim()
    if ymax:
        ax.set_ylim(min(lo, -0.05 * ymax), ymax)
        ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(ymax / 6))
        return
    if top is not None:
        hi = top * 1.25  # room for the upright value label
    rows = -(-len(series) // (legend_cols or len(series)))
    # room above the bars for the legend box (title + its rows)
    ax.set_ylim(min(lo, -0.05 * (hi - lo)), hi + (0.3 + 0.2 * rows) *
                (hi - lo))


def instmix(ax, groups, rows, abis, baseline, table, clip=2.0):
    """Stacked op-class bars per (workload, ABI), % of the baseline's
    instruction count. A bar more than CLIP times the next tallest is cut
    (break mark, total printed), as in panel()."""
    width = 0.8 / len(abis)
    pos, gaps, end = x_layout(groups)
    totals = []
    for x, wl in pos:
        b = rows.get((baseline, wl))
        for abi in abis:
            r = rows.get((abi, wl))
            if r and b and value(b, ["insts"]):
                totals.append(100.0 * sum(value(r, c) or 0.0 for _, c, _, _
                                          in INST_CLASSES) /
                              value(b, ["insts"]))
    totals.sort(reverse=True)
    cut = None
    if clip and len(totals) > 1 and totals[0] > clip * totals[1]:
        cut = totals[1] * 1.25
    minor, minor_lbl, tops = [], [], []
    for x, wl in pos:
        b = rows.get((baseline, wl))
        bv = value(b, ["insts"]) if b else None
        for i, abi in enumerate(abis):
            r = rows.get((abi, wl))
            if r is None or not bv:
                continue
            xb = x - 0.4 + width * (i + 0.5)
            y = 0.0
            for cls, cols, col, hatch in INST_CLASSES:
                v = value(r, cols) or 0.0
                pct = 100.0 * v / bv
                if cut is None or y < cut:
                    h = pct if cut is None else min(pct, cut - y)
                    ax.bar(xb, h, width * 0.9, bottom=y, facecolor="white",
                           edgecolor=col, hatch=hatch, linewidth=0.5,
                           zorder=2)
                table.append({"group": wl[0], "workload": wl[1], "abi": abi,
                              "class": cls, "count": v,
                              f"{baseline}_insts": bv,
                              "pct_of_baseline": round(pct, 3)})
                y += pct
            if cut is not None and y > cut:
                w2, y0, gap = width * 0.55, cut * 0.8, cut * 0.04
                ax.fill_between([xb - w2, xb + w2], [y0 - gap / 2, y0],
                                [y0 + gap / 2, y0 + gap], color="white",
                                zorder=3)
                for yy in (y0 - gap / 2, y0 + gap / 2):
                    ax.plot([xb - w2, xb + w2], [yy, yy + gap / 2],
                            color="black", linewidth=0.6, zorder=4)
                ax.text(xb, cut * 1.01, f"{y:.0f}%", ha="center",
                        va="bottom", rotation=90, fontsize=5, zorder=4)
                y = cut * 1.2
            tops.append(y)
            minor.append(xb)
            minor_lbl.append(ABI_LETTER.get(abi, abi[0].upper()))
    ax.axhline(100, color="#ff0000", linestyle=(0, (4, 2)), linewidth=0.6,
               zorder=3)
    finish_x(ax, pos, gaps, end, True)
    # ABI letter under each bar, the workload name under the letters
    ax.xaxis.remove_overlapping_locs = False  # keep the middle letter
    ax.set_xticks(minor, minor=True)
    ax.set_xticklabels(minor_lbl, minor=True, fontsize=4.5)
    ax.tick_params(axis="x", which="minor", length=0, pad=1.5)
    ax.tick_params(axis="x", which="major", pad=9)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    names = ", ".join(f"{ABI_LETTER.get(a, a[0].upper())} = {ABI_NAME[a]}"
                      for a in abis)
    legend(ax, [Patch(facecolor="white", edgecolor=col, hatch=hatch,
                      label=cls) for cls, _, col, hatch in INST_CLASSES],
           f"Instruction mix - % of {ABI_NAME[baseline]} instructions "
           f"({names})", 4)
    hi = max(tops) if tops else 100
    ax.set_ylim(0, hi * 1.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="*", help="results dirs (one group)")
    ap.add_argument("--group", action="append", default=[],
                    help="LABEL=RESULTS_DIR (repeatable; groups are spaced)")
    ap.add_argument("--config", default="minor",
                    help="CPU/tag config to plot (default minor)")
    ap.add_argument("--baseline", default="plain")
    ap.add_argument("--abis", default="hybrid,purecap",
                    help="series to plot against the baseline")
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--summary-abi", default="purecap",
                    help="ABI of the all-metrics summary figure")
    ap.add_argument("--summary-ymax", type=float, default=150,
                    help="y-axis top of the summary figure, %% (0: auto)")
    ap.add_argument("--clip", type=float, default=2.5,
                    help="cut the axis when the largest bar exceeds CLIP x "
                    "the next largest (0: never)")
    a = ap.parse_args()

    group_specs = [("", a.dirs)] if a.dirs else []
    for g in a.group:
        label, _, d = g.partition("=")
        group_specs.append((label, [d]))
    if not group_specs:
        sys.exit("give RESULTS_DIR arguments or --group LABEL=DIR")
    abis = a.abis.split(",")
    out = a.out or os.path.join(group_specs[0][1][0], "plots")
    os.makedirs(out, exist_ok=True)
    style()

    groups, rows = [], {}
    for label, dirs in group_specs:
        r = load(dirs, a.config)
        wls = sorted({w for (_, w) in r},
                     key=lambda w: SHORT.get(w, w))
        groups.append((label, wls))
        rows.update({(abi, (label, w)): v for (abi, w), v in r.items()})
    # key workloads by (group, name) so equal names in two suites stay apart
    groups = [(label, [(label, w) for w in wls]) for label, wls in groups]

    table = []
    per_metric = {}
    for key, title, cols in METRICS:
        data = {}
        for _, wls in groups:
            for wl in wls:
                b = rows.get((a.baseline, wl))
                bv = value(b, cols) if b else None
                for abi in abis:
                    r = rows.get((abi, wl))
                    v = value(r, cols) if r else None
                    if v is None or not bv:
                        continue
                    pct = 100.0 * (v / bv - 1.0)
                    data[(abi, wl)] = pct
                    table.append({"metric": title, "group": wl[0],
                                  "workload": wl[1], "abi": abi,
                                  "baseline": a.baseline, "value": v,
                                  "baseline_value": bv,
                                  "overhead_pct": round(pct, 3)})
        per_metric[key] = (title, data)

    def draw(fig_axes, keys, last_labels_only):
        for i, (ax, key) in enumerate(zip(fig_axes, keys)):
            title, data = per_metric[key]
            show = (not last_labels_only) or i == len(keys) - 1
            panel(ax, groups, data,
                  [(abi, ABI_NAME[abi]) + STYLE[abi] for abi in abis],
                  f"{title} - overheads to {ABI_NAME[a.baseline]}",
                  show_xlabels=show, clip=a.clip)

    keys = [k for k, _, _ in METRICS]
    n = sum(len(w) for _, w in groups)
    width = min(7.16, max(3.5, 0.32 * n + 1.0))
    fig, axs = plt.subplots(len(keys), 1, figsize=(width, 1.25 * len(keys)),
                            sharex=True)
    draw(axs, keys, last_labels_only=True)
    fig.subplots_adjust(hspace=0.12)
    for t, ax in zip("abcdef", axs):
        right = not getattr(ax, "legend_right", False)
        ax.text(0.995 if right else 0.005, 0.96, f"({t})",
                transform=ax.transAxes, va="top",
                ha="right" if right else "left", fontsize=7)
    fig.savefig(os.path.join(out, "overheads.pdf"))
    if a.png:
        fig.savefig(os.path.join(out, "overheads.png"), dpi=300)
    plt.close(fig)
    for key in keys:
        fig, ax = plt.subplots(figsize=(width, 1.6))
        draw([ax], [key], last_labels_only=False)
        fig.savefig(os.path.join(out, f"overhead_{key}.pdf"))
        if a.png:
            fig.savefig(os.path.join(out, f"overhead_{key}.png"), dpi=300)
        plt.close(fig)
    with open(os.path.join(out, "overheads.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)

    def save(fig, name):
        fig.savefig(os.path.join(out, f"{name}.pdf"))
        if a.png:
            fig.savefig(os.path.join(out, f"{name}.png"), dpi=300)
        plt.close(fig)

    # one ABI, every metric side by side
    sa = a.summary_abi
    data = {(key, wl): v for key, (_, d) in per_metric.items()
            for (abi, wl), v in d.items() if abi == sa}
    if data:
        order = ["cycles", "insts", "accesses", "l1d", "l2", "dram"]
        fig, ax = plt.subplots(figsize=(7.16, 2.4))
        panel(ax, groups, data, [(k,) + METRIC_STYLE[k] for k in order],
              f"{ABI_NAME[sa]} - overheads to {ABI_NAME[a.baseline]}",
              clip=a.clip, legend_cols=len(order) if a.summary_ymax else 3,
              ymax=a.summary_ymax)
        save(fig, f"{sa}_overheads")

    mix = []
    fig, ax = plt.subplots(figsize=(7.16, 2.6))
    instmix(ax, groups, rows, [a.baseline] + abis, a.baseline, mix)
    save(fig, "instmix")
    with open(os.path.join(out, "instmix.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(mix[0]))
        w.writeheader()
        w.writerows(mix)
    print(f"wrote {out}/: overheads.pdf, overhead_<metric>.pdf, "
          f"{sa}_overheads.pdf, instmix.pdf, overheads.csv, instmix.csv "
          f"(config {a.config}, baseline {a.baseline})")


if __name__ == "__main__":
    main()
