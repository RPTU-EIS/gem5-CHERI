#!/usr/bin/env python3
"""Paper figures and tables for the CoreMark-PRO purecap/hybrid experiment.

Reads one or more results.csv files written by parse.py (an experiment
directory or the CSV itself; rows of later inputs replace earlier ones with
the same ABI, config and workload) and writes, into --out:

  overhead.pdf   purecap overhead over hybrid: instructions (Atomic) and
                 cycles (Minor) per workload, with the geometric mean
  memory.pdf     L1D MPKI, L2 MPKI and DRAM bytes/kinst, hybrid vs purecap
  instmix.pdf    dynamic instruction mix, normalised to hybrid's count
  tags.pdf       tag-storage cost over passthrough: cycles, DRAM traffic,
                 tag-cache hit rate          (needs minor-<tag model> runs)
  endtoend.pdf   purecap with each tag model vs hybrid without tags
                                             (needs minor-<tag model> runs)
  tables.tex     per-workload table and simulation-cost table (booktabs)
  plot_data.csv  every plotted value

Figures are sized for two-column IEEE/ACM templates (DAC, ISCA): 3.5 in
single column, 7.16 in double, 8 pt text, PDF with TrueType (Type 42)
fonts embedded, no Type 3. Only runs with status 0 and no CRC errors are
plotted; others are listed and skipped.

Usage: plot.py RESULTS [RESULTS...] [--out DIR] [--png] [--hatch]
Needs matplotlib and numpy (pip install matplotlib numpy).
"""

import argparse
import csv
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SINGLE = 3.5  # in, IEEE/ACM column width
DOUBLE = 7.16  # in, full text width

# Categorical slots in their validated order (dataviz reference palette,
# light surface): adjacent pairs pass the colour-vision-deficiency check;
# the first three also pass all-pairs.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
HATCHES = ["", "////", "....", "\\\\\\\\", "xxxx", "----"]

SHORT = {
    "cjpeg-rose7-preset": "cjpeg",
    "core": "core",
    "linear_alg-mid-100x100-sp": "linear_alg",
    "loops-all-mid-10k-sp": "loops",
    "nnet_test": "nnet",
    "parser-125k": "parser",
    "radix2-big-64k": "radix2",
    "sha-test": "sha",
    "zip-test": "zip",
}
TAG_MODELS = ["flat", "hierarchical"]

# Instruction classes (gem5 OpClass) folded for the mix figure.
MIX = [
    ("Int ALU", ["inst_IntAlu"]),
    ("Int mul/div", ["inst_IntMult", "inst_IntDiv"]),
    ("FP", ["inst_FloatAdd", "inst_FloatCmp", "inst_FloatCvt",
            "inst_FloatMult", "inst_FloatMultAcc", "inst_FloatDiv",
            "inst_FloatMisc", "inst_FloatSqrt"]),
    ("Load", ["inst_MemRead", "inst_FloatMemRead"]),
    ("Store", ["inst_MemWrite", "inst_FloatMemWrite"]),
]

# ABIs in plotting order. plain: RV64 compiled without CHERI (a core
# without CHERI); hybrid: the same code built for a CHERI system; purecap:
# every pointer a capability. Ratios are against BASE: plain when present.
ABI_ORDER = ["plain", "hybrid", "purecap"]
ABI_NAME = {"plain": "Plain RV64", "hybrid": "Hybrid", "purecap": "Purecap"}
ABI_LETTER = {"plain": "R", "hybrid": "H", "purecap": "P"}
ABI_COLOR = {"plain": SLOTS[0], "purecap": SLOTS[1], "hybrid": SLOTS[2]}
BASE = "hybrid"

HATCH = False
PLOTTED = []  # rows of plot_data.csv


def style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Liberation Sans", "Arial", "Helvetica",
                            "DejaVu Sans"],
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.edgecolor": INK2,
        "axes.labelcolor": INK,
        "axes.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.5,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2,
        "ytick.major.size": 2,
        "legend.frameon": False,
        "legend.handlelength": 1.2,
        "legend.columnspacing": 1.0,
        "hatch.linewidth": 0.4,
        "hatch.color": "#ffffff",
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })


# ---------------------------------------------------------------- data

def fnum(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def load(paths):
    rows = {}
    for p in paths:
        f = os.path.join(p, "results.csv") if os.path.isdir(p) else p
        with open(f) as fh:
            for r in csv.DictReader(fh):
                rows[(r["abi"], r["config"], r["workload"])] = r
    good, bad = {}, []
    for k, r in rows.items():
        if fnum(r.get("status")) == 0 and not fnum(r.get("errors")):
            good[k] = r
        else:
            bad.append(k)
    if bad:
        print("skipping %d failed run(s):" % len(bad), file=sys.stderr)
        for k in sorted(bad):
            print("  %s %s %s" % k, file=sys.stderr)
    return good


class Data:
    def __init__(self, rows):
        self.rows = rows
        self.workloads = sorted({k[2] for k in rows},
                                key=lambda w: SHORT.get(w, w))
        self.configs = {k[1] for k in rows}
        self.abis = [a for a in ABI_ORDER if any(k[0] == a for k in rows)]

    def get(self, abi, config, wl, metric):
        r = self.rows.get((abi, config, wl))
        return fnum(r.get(metric)) if r else None

    def ratio(self, config, wl, metric, num=("purecap", None), den=None):
        """num/den; each side is (abi, config or None for `config`); den
        defaults to the baseline ABI."""
        den = den or (BASE, None)
        a = self.get(num[0], num[1] or config, wl, metric)
        b = self.get(den[0], den[1] or config, wl, metric)
        return a / b if a is not None and b else None


def geomean(vals):
    vals = [v for v in vals if v is not None and v > 0]
    return math.exp(sum(map(math.log, vals)) / len(vals)) if vals else None


def record(fig, series, wl, metric, value):
    PLOTTED.append({"figure": fig, "series": series, "workload": wl,
                    "metric": metric, "value": value})


def save(fig, out, name, png):
    fig.savefig(os.path.join(out, name + ".pdf"))
    if png:
        fig.savefig(os.path.join(out, name + ".png"), dpi=300)
    plt.close(fig)
    print("wrote", os.path.join(out, name + ".pdf"))


# ------------------------------------------------------------- helpers

def grouped_bars(ax, groups, series, values, label_last=True, fmt="%+.0f%%"):
    """Bars per group and series; values[s][g] may be None. The last group
    (the geometric mean) is set apart by a gap and gets value labels."""
    n = len(series)
    width = 0.8 / n
    x = np.arange(len(groups), dtype=float)
    if label_last:
        x[-1] += 0.5
    for i, s in enumerate(series):
        xs = x - 0.4 + width * (i + 0.5)
        ys = [values[s][g] for g in range(len(groups))]
        ax.bar([a for a, y in zip(xs, ys) if y is not None],
               [y for y in ys if y is not None], width,
               color=SLOTS[i], edgecolor="white", linewidth=0.5,
               hatch=HATCHES[i] if HATCH else None, label=s, zorder=2)
        y = ys[-1]
        if label_last and y is not None:
            ax.annotate(fmt % y, (xs[-1], y), xytext=(0, 2 if y >= 0 else -2),
                        textcoords="offset points", ha="center",
                        va="bottom" if y >= 0 else "top", rotation=90,
                        fontsize=6, color=INK)
    ax.margins(y=0.18)
    ax.set_xticks(x)
    ax.set_xticklabels(groups, rotation=35, ha="right",
                       rotation_mode="anchor")
    ax.axhline(0, color=INK2, linewidth=0.6, zorder=3)
    ax.set_xlim(x[0] - 0.6, x[-1] + 0.6)
    return x


def top_legend(fig, ax, ncol, titled=False):
    """Legend centred over the figure, just above the highest axes."""
    h, lab = ax.get_legend_handles_labels()
    top = max(a.get_position().y1 for a in fig.axes)
    fig.legend(h, lab, loc="lower center",
               bbox_to_anchor=(0.5, top + (0.07 if titled else 0.01)),
               ncol=ncol, borderaxespad=0.1)


def ratio_bars(d, fig_name, ratios):
    """ratios: {series: {workload: ratio or None}}. Keeps the workloads
    every series has, so all geometric means cover the same set; returns
    (group labels, {series: [overhead % ..., geomean]})."""
    wls = [w for w in d.workloads
           if all(r.get(w) for r in ratios.values())]
    vals = {}
    for name, r in ratios.items():
        rs = [r[w] for w in wls] + [geomean([r[w] for w in wls])]
        vals[name] = [(v - 1) * 100 if v else None for v in rs]
        for w, v in zip(wls + ["geomean"], rs):
            record(fig_name, name, w, "ratio", v)
    return [SHORT.get(w, w) for w in wls] + ["geomean"], vals


def pick(data, *configs):
    for c in configs:
        if c in data.configs:
            return c
    return None


# ------------------------------------------------------------- figures

def fig_overhead(d, out, png):
    """Instructions on Atomic (what CHERI-VP reports) and cycles on Minor."""
    timing = pick(d, "minor", "minor-passthrough")
    series = []
    if "atomic" in d.configs:
        series.append(("Purecap instructions (Atomic)", "atomic", "insts",
                       "purecap"))
    if timing:
        series.append(("Purecap cycles (Minor)", timing, "cycles",
                       "purecap"))
        if BASE == "plain" and "hybrid" in d.abis:
            series.append(("Hybrid cycles (Minor)", timing, "cycles",
                           "hybrid"))
    if not series:
        return
    groups, vals = ratio_bars(d, "overhead", {
        name: {w: d.ratio(cfg, w, metric, (abi, None)) for w in d.workloads}
        for name, cfg, metric, abi in series})
    if len(groups) < 2:
        return
    fig, ax = plt.subplots(figsize=(SINGLE, 1.75))
    grouped_bars(ax, groups, [s[0] for s in series], vals)
    ax.set_ylabel("Overhead vs.\n%s (%%)" % ABI_NAME[BASE].replace(
        "Plain", "plain").replace("Hybrid", "hybrid"))
    top_legend(fig, ax, 2 if len(series) < 3 else 1)
    save(fig, out, "overhead", png)


def fig_memory(d, out, png):
    """Dumbbell per workload: hybrid -> purecap, log scale (values span
    three decades across workloads)."""
    cfg = pick(d, "minor", "minor-passthrough")
    if not cfg:
        return
    metrics = [("l1d_mpki", "L1D MPKI"), ("l2_mpki", "L2 MPKI"),
               ("dram_bytes_per_kinst", "DRAM bytes / kinst")]
    wls = d.workloads
    fig, axs = plt.subplots(1, 3, figsize=(DOUBLE, 1.9), sharey=True)
    y = np.arange(len(wls))[::-1]
    sizes = [26, 17, 10]
    markers = ["o", "s", "D"]
    for ax, (m, label) in zip(axs, metrics):
        vals = {a: [d.get(a, cfg, w, m) for w in wls] for a in d.abis}
        for i, yi in enumerate(y):
            v = [vals[a][i] for a in d.abis if vals[a][i]]
            if len(v) > 1:
                ax.plot([min(v), max(v)], [yi, yi], color=GRID,
                        linewidth=2, solid_capstyle="round", zorder=1)
        for k, a in enumerate(d.abis):
            ax.scatter([v for v in vals[a] if v],
                       [yi for yi, v in zip(y, vals[a]) if v],
                       s=sizes[k], color=ABI_COLOR[a], edgecolor="white",
                       linewidth=0.5, marker=markers[k] if HATCH else "o",
                       label=ABI_NAME[a], zorder=3 + k)
            for w, v in zip(wls, vals[a]):
                record("memory", a, w, m, v)
        ax.set_xscale("log")
        ax.set_xlabel(label)
        ax.grid(axis="x", which="major")
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", length=0)
    axs[0].set_yticks(y)
    axs[0].set_yticklabels([SHORT.get(w, w) for w in wls])
    fig.subplots_adjust(wspace=0.08)
    top_legend(fig, axs[0], len(d.abis))
    save(fig, out, "memory", png)


def fig_instmix(d, out, png):
    """Stacked dynamic instruction mix; each bar is normalised to the
    baseline's instruction count, so a bar's height is that ABI's
    instruction ratio."""
    cfg = pick(d, "atomic", "minor")
    if not cfg:
        return
    abis = d.abis
    wls = [w for w in d.workloads
           if all(d.get(a, cfg, w, "insts") for a in abis)]
    if not wls:
        return
    def share(abi, w, cls):
        total = d.get(abi, cfg, w, "insts")
        if cls == "Other":
            v = total - sum(d.get(abi, cfg, w, c) or 0
                            for _, cs in MIX for c in cs)
        else:
            v = sum(d.get(abi, cfg, w, c) or 0 for c in dict(MIX)[cls])
        return max(v, 0) / d.get(BASE, cfg, w, "insts")

    # Classes under 0.5% of every bar are left out (stated in the caption).
    classes = [c for c in [m[0] for m in MIX] + ["Other"]
               if max(share(a, w, c) for w in wls
                      for a in abis) >= 0.005]
    fig, ax = plt.subplots(figsize=(DOUBLE, 1.9))
    xs, ticks, labels = [], [], []
    step = len(abis) + 0.6
    for i, w in enumerate(wls):
        for j, abi in enumerate(abis):
            x = i * step + j * 1.0
            xs.append(x)
            ticks.append(x)
            labels.append(ABI_LETTER[abi])
            bottom = 0.0
            for k, cls in enumerate(classes):
                v = share(abi, w, cls)
                ax.bar(x, v, 0.9, bottom=bottom, color=SLOTS[k],
                       edgecolor="white", linewidth=0.5,
                       hatch=HATCHES[k] if HATCH else None,
                       label=cls if i == 0 and j == 0 else None, zorder=2)
                record("instmix", abi, w, cls, v)
                bottom += v
        ax.text(i * step + (len(abis) - 1) / 2, -0.09, SHORT.get(w, w),
                ha="center",
                va="top", transform=ax.get_xaxis_transform(), fontsize=7,
                color=INK)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=6)
    ax.tick_params(axis="x", length=0, pad=1)
    ax.set_xlim(min(xs) - 0.8, max(xs) + 0.8)
    ax.set_ylabel("Instructions\n(norm. to %s)" % ABI_NAME[BASE])
    top_legend(fig, ax, len(classes))
    save(fig, out, "instmix", png)


def fig_tags(d, out, png, abi):
    """Cost of storing tags in memory, relative to a tag controller that
    adds no tag traffic (passthrough), same ABI and CPU."""
    base = "minor-passthrough"
    models = [m for m in TAG_MODELS if "minor-" + m in d.configs]
    if base not in d.configs or not models:
        return
    wls = [w for w in d.workloads if d.get(abi, base, w, "cycles")]
    if not wls:
        return
    groups = [SHORT.get(w, w) for w in wls] + ["geomean"]
    names = [m.capitalize() for m in models]
    cyc, dram, hit = {}, {}, {}
    for m, name in zip(models, names):
        cfg = "minor-" + m
        rc = [d.ratio(None, w, "cycles", (abi, cfg), (abi, base))
              for w in wls]
        tr = []
        for w in wls:
            a = [d.get(abi, cfg, w, k) for k in
                 ("dram_bytes_read", "dram_bytes_written")]
            b = [d.get(abi, base, w, k) for k in
                 ("dram_bytes_read", "dram_bytes_written")]
            tr.append(sum(a) / sum(b) if None not in a + b and sum(b)
                      else None)
        hr = []
        for w in wls:
            h = d.get(abi, cfg, w, "tag_leaf_hits")
            mi = d.get(abi, cfg, w, "tag_leaf_misses")
            hr.append(h / (h + mi) * 100 if h is not None and mi is not None
                      and h + mi else None)
        cyc[name] = [(v - 1) * 100 if v else None for v in rc + [geomean(rc)]]
        dram[name] = [(v - 1) * 100 if v else None
                      for v in tr + [geomean(tr)]]
        hvals = [v for v in hr if v is not None]
        hit[name] = hr + [sum(hvals) / len(hvals) if hvals else None]
        for w, a, b, c in zip(wls + ["geomean"], cyc[name], dram[name],
                              hit[name]):
            record("tags", name, w, "cycles_overhead_pct", a)
            record("tags", name, w, "dram_traffic_overhead_pct", b)
            record("tags", name, w, "tag_cache_hit_pct", c)
    fig, axs = plt.subplots(1, 3, figsize=(DOUBLE, 1.75))
    grouped_bars(axs[0], groups, names, cyc, fmt="%+.2f%%")
    axs[0].set_ylabel("Cycle overhead (%)")
    grouped_bars(axs[1], groups, names, dram, fmt="%+.1f%%")
    axs[1].set_ylabel("DRAM traffic overhead (%)")
    grouped_bars(axs[2], groups[:-1] + ["mean"], names, hit, fmt="%.0f%%")
    axs[2].set_ylabel("Tag-cache hit rate (%)")
    axs[2].set_ylim(0, 105)
    for ax, t in zip(axs, "abc"):
        ax.set_title("(%s)" % t, loc="left", fontsize=8, pad=2)
    fig.subplots_adjust(wspace=0.38)
    top_legend(fig, axs[0], len(names), titled=True)
    save(fig, out, "tags", png)


def fig_endtoend(d, out, png):
    """Purecap with in-memory tags against the baseline (plain RV64 when
    present) on a machine without them: what adopting CHERI costs."""
    base = "minor"
    series = [("Purecap, no tag storage", pick(d, "minor-passthrough",
                                                "minor"))]
    series += [("Purecap + %s tags" % m, "minor-" + m) for m in TAG_MODELS
               if "minor-" + m in d.configs]
    if base not in d.configs or len(series) < 2 or not series[0][1]:
        return
    groups, vals = ratio_bars(d, "endtoend", {
        name: {w: d.ratio(None, w, "cycles", ("purecap", cfg),
                          (BASE, base)) for w in d.workloads}
        for name, cfg in series})
    if len(groups) < 2:
        return
    fig, ax = plt.subplots(figsize=(SINGLE, 1.75))
    grouped_bars(ax, groups, [s[0] for s in series], vals)
    ax.set_ylabel("Cycle overhead vs.\n%s, no tags (%%)" % ABI_NAME[BASE])
    top_legend(fig, ax, 1 if len(series) > 2 else 2)
    save(fig, out, "endtoend", png)


# -------------------------------------------------------------- tables

def fmt(v, f):
    return "--" if v is None else f % v


def tables(d, out):
    timing = pick(d, "minor", "minor-passthrough")
    lines = [
        "% Generated by util/cheri/coremark/plot.py",
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        " & %s & \\multicolumn{2}{c}{Purecap / %s} & "
        "\\multicolumn{2}{c}{IPC (Minor)} & %s \\\\" % (
            ABI_NAME[BASE], ABI_NAME[BASE].lower(), ABI_NAME[BASE]),
        "\\cmidrule(lr){3-4}\\cmidrule(lr){5-6}",
        "Workload & Minst & Insts & Cycles & %s & Purecap & " % ABI_NAME[BASE] +
        "L2 MPKI \\\\",
        "\\midrule",
    ]
    ri, rc = [], []
    for w in d.workloads:
        a = d.ratio("atomic", w, "insts")
        c = d.ratio(timing, w, "cycles") if timing else None
        ri.append(a)
        rc.append(c)
        n = d.get(BASE, "atomic", w, "insts") or (
            d.get(BASE, timing, w, "insts") if timing else None)
        lines.append("%s & %s & %s & %s & %s & %s & %s \\\\" % (
            SHORT.get(w, w).replace("_", "\\_"),
            fmt(n / 1e6 if n else None, "%.0f"), fmt(a, "%.2f"),
            fmt(c, "%.2f"),
            fmt(d.get(BASE, timing, w, "ipc"), "%.2f"),
            fmt(d.get("purecap", timing, w, "ipc"), "%.2f"),
            fmt(d.get(BASE, timing, w, "l2_mpki"), "%.2f")))
    lines += ["\\midrule",
              "Geomean & & %s & %s & & & \\\\" % (
                  fmt(geomean(ri), "%.2f"), fmt(geomean(rc), "%.2f")),
              "\\bottomrule", "\\end{tabular}", ""]

    # Simulation cost: host time and speed per configuration.
    lines += ["\\begin{tabular}{lrrr}", "\\toprule",
              "Configuration & Runs & Host time (h) & MIPS \\\\",
              "\\midrule"]
    for cfg in sorted(d.configs):
        rs = [r for k, r in d.rows.items() if k[1] == cfg]
        host = sum(fnum(r.get("host_seconds")) or 0 for r in rs)
        insts = sum(fnum(r.get("insts")) or 0 for r in rs)
        lines.append("%s & %d & %.1f & %s \\\\" % (
            cfg, len(rs), host / 3600,
            fmt(insts / host / 1e6 if host else None, "%.2f")))
    boots = {fnum(r.get("checkpoint_boot_wall_seconds"))
             for r in d.rows.values()} - {None}
    lines += ["\\bottomrule", "\\end{tabular}"]
    if boots:
        lines.append("%% checkpoint boot (host): %s s"
                     % ", ".join("%.0f" % b for b in sorted(boots)))
    with open(os.path.join(out, "tables.tex"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", os.path.join(out, "tables.tex"))


def main():
    global HATCH
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("results", nargs="+",
                    help="experiment directories or results.csv files")
    ap.add_argument("--out", help="output directory (default: "
                    "<first input>/plots)")
    ap.add_argument("--png", action="store_true",
                    help="also write 300 dpi PNGs")
    ap.add_argument("--hatch", action="store_true",
                    help="add hatching / marker shapes for grayscale print")
    ap.add_argument("--baseline", choices=ABI_ORDER[:2], default=None,
                    help="ABI that ratios are against (default plain if "
                    "present, else hybrid)")
    ap.add_argument("--tag-abi", default="purecap",
                    help="ABI shown in tags.pdf (default purecap)")
    a = ap.parse_args()
    HATCH = a.hatch
    first = a.results[0]
    out = a.out or os.path.join(
        first if os.path.isdir(first) else os.path.dirname(first), "plots")
    os.makedirs(out, exist_ok=True)
    style()
    d = Data(load(a.results))
    global BASE
    BASE = a.baseline or ("plain" if "plain" in d.abis else "hybrid")
    print(f"baseline: {BASE}")
    if not d.rows:
        sys.exit("no successful runs in %s" % ", ".join(a.results))
    fig_overhead(d, out, a.png)
    fig_memory(d, out, a.png)
    fig_instmix(d, out, a.png)
    fig_tags(d, out, a.png, a.tag_abi)
    fig_endtoend(d, out, a.png)
    tables(d, out)
    with open(os.path.join(out, "plot_data.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, ["figure", "series", "workload", "metric",
                               "value"])
        w.writeheader()
        w.writerows(PLOTTED)


if __name__ == "__main__":
    main()
