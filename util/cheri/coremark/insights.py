#!/usr/bin/env python3
"""Analysis figures beyond per-metric overheads, in the style of
util/cheri/overhead_bars.py. Every plotted value is a gem5 statistic or a
ratio/difference of two; nothing is modelled or interpolated.

  tag_hw.pdf        cost of the tag hardware alone: the same binary on the
                    CPU with a tag model vs without one (config minor), for
                    passthrough (controller, no tag traffic: timing noise
                    floor), nocache, flat, hierarchical. (a) DRAM traffic,
                    (b) cycles. One ABI (--abi, default purecap).
  tag_scatter.pdf   the same, all ABIs in one scatter: every (workload,
                    ABI, tag model) run is a point at (DRAM traffic increase,
                    cycle increase); the grey band is the range passthrough
                    alone produces (timing noise).
  regimes.pdf       per workload, instruction overhead vs cycle overhead of
                    each ABI against the baseline (minor); y = x dashed:
                    above it extra instructions cost more than the average
                    instruction (memory/latency), below it less.
  sweep_pareto.pdf  cache-size sweep: on-chip data cache capacity (L1D + L2)
                    vs cycles relative to the baseline at the default
                    sizes, one panel per swept workload (plus their
                    geometric mean when 4+ workloads were swept); lines
                    join each ABI's Pareto-optimal points.

Usage: util/cheri/coremark/insights.py MERGED_RESULTS_DIR
         [--sweep CACHE_SWEEP_CSV] [--abi purecap] [--baseline plain]
         [--suite NAME] [--out DIR] [--png]
(works for any suite parsed by the CoreMark-PRO parser, e.g. Olden)
MERGED_RESULTS_DIR holds results.csv with the minor, minor-passthrough,
minor-nocache, minor-flat and minor-hierarchical runs (parse.py --into).
Also writes insights.csv with every plotted value. Needs matplotlib.
"""

import argparse
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from cache_sweep_collect import size_bytes  # noqa: E402
from overhead_bars import (ABI_NAME, SHORT, STYLE, legend,  # noqa: E402
                           style)

TAG_CONFIGS = [  # config, label, colour, hatch
    ("minor-passthrough", "passthrough (no tag traffic)", "#7f7f7f", "...."),
    ("minor-nocache", "no tag cache", "#D55E00", "\\\\\\\\\\\\"),
    ("minor-flat", "flat tag cache", "#0072B2", "////"),
    ("minor-hierarchical", "hierarchical tag cache", "#009E73", "xxxx"),
]
ABI_MARKER = {"plain": "s", "hybrid": "o", "purecap": "^"}


def short(w):
    return SHORT.get(w, w).replace("_", "-")


def num(r, *cols):
    return sum(float(r[c]) for c in cols)


def load(d):
    out = {}
    for r in csv.DictReader(open(os.path.join(d, "results.csv"))):
        if str(r["status"]) == "0" and str(r.get("errors", "0")) in ("0", ""):
            out[(r["abi"], r["config"], r["workload"])] = r
    return out


def bars(ax, wls, series, data, title, fmt):
    """Grouped white hatched bars; series [(key, label, colour, hatch)]."""
    width = 0.8 / len(series)
    for x, w in enumerate(wls):
        for i, (key, _, col, hatch) in enumerate(series):
            v = data.get((key, w))
            if v is None:
                continue
            ax.bar(x - 0.4 + width * (i + 0.5), v, width * 0.92,
                   facecolor="white", edgecolor=col, hatch=hatch,
                   linewidth=0.6, zorder=2)
    ax.axhline(0, color="#ff0000", linestyle=(0, (4, 2)), linewidth=0.6,
               zorder=3)
    ax.set_xlim(-0.6, len(wls) - 0.4)
    ax.set_xticks(range(len(wls)))
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(fmt))
    legend(ax, [Patch(facecolor="white", edgecolor=c, hatch=h, label=l)
                for _, l, c, h in series], title, len(series))
    lo, hi = ax.get_ylim()
    ax.set_ylim(min(lo, -0.05 * (hi - lo)), hi + 0.6 * (hi - lo))


def fig_tag_hw(res, abi, out, save, table):
    wls = sorted({w for (a, c, w) in res if a == abi and c == "minor"},
                 key=short)
    dram, cyc = {}, {}
    for cfg, *_ in TAG_CONFIGS:
        for w in wls:
            b, r = res.get((abi, "minor", w)), res.get((abi, cfg, w))
            if not b or not r:
                continue
            bd = num(b, "dram_bytes_read", "dram_bytes_written")
            rd = num(r, "dram_bytes_read", "dram_bytes_written")
            dram[(cfg, w)] = 100 * (rd / bd - 1)
            cyc[(cfg, w)] = 100 * (num(r, "cycles") / num(b, "cycles") - 1)
            table.append({"figure": "tag_hw", "abi": abi, "workload": w,
                          "config": cfg, "metric": "dram_bytes", "value": rd,
                          "reference": bd, "pct": round(dram[(cfg, w)], 3)})
            table.append({"figure": "tag_hw", "abi": abi, "workload": w,
                          "config": cfg, "metric": "cycles",
                          "value": num(r, "cycles"),
                          "reference": num(b, "cycles"),
                          "pct": round(cyc[(cfg, w)], 3)})
    fig, axs = plt.subplots(2, 1, figsize=(7.16, 3.6), sharex=True,
                            gridspec_kw={"hspace": 0.1})
    pct = lambda v, _: f"{v:+.0f}%"  # noqa: E731
    bars(axs[0], wls, TAG_CONFIGS, dram,
         f"{ABI_NAME[abi]}: DRAM traffic - increase over the same binary "
         "without a tag model", pct)
    bars(axs[1], wls, TAG_CONFIGS, cyc,
         f"{ABI_NAME[abi]}: CPU cycles - increase over the same binary "
         "without a tag model", lambda v, _: f"{v:+.1f}%")
    axs[1].set_xticklabels([short(w) for w in wls], rotation=90)
    for t, ax in zip("ab", axs):
        ax.text(0.995, 0.96, f"({t})", transform=ax.transAxes, va="top",
                ha="right", fontsize=7)
    save(fig, f"tag_hw_{abi}")


def fig_tag_scatter(res, out, save, table, suite):
    abis = ["plain", "hybrid", "purecap"]
    wls = sorted({w for (a, c, w) in res if c == "minor"}, key=short)

    def delta(abi, cfg, w):
        b, r = res.get((abi, "minor", w)), res.get((abi, cfg, w))
        if not b or not r:
            return None
        d = num(r, "dram_bytes_read", "dram_bytes_written") / \
            num(b, "dram_bytes_read", "dram_bytes_written")
        return 100 * (d - 1), 100 * (num(r, "cycles") / num(b, "cycles") - 1)

    noise = [delta(a, "minor-passthrough", w)[1] for a in abis for w in wls
             if delta(a, "minor-passthrough", w)]
    fig, ax = plt.subplots(figsize=(3.5, 2.6))
    ax.axhspan(min(noise), max(noise), color="#d9d9d9", zorder=0, lw=0)
    ax.axhline(0, color="#ff0000", linestyle=(0, (4, 2)), linewidth=0.6,
               zorder=1)
    worst = {}
    for cfg, lbl, col, _ in TAG_CONFIGS[1:]:
        for abi in abis:
            for w in wls:
                d = delta(abi, cfg, w)
                if not d:
                    continue
                ax.scatter(*d, s=14, marker=ABI_MARKER[abi],
                           facecolor="white", edgecolor=col, linewidth=0.7,
                           zorder=3)
                table.append({"figure": "tag_scatter", "abi": abi,
                              "workload": w, "config": cfg,
                              "metric": "dram_pct,cycles_pct",
                              "value": round(d[0], 3), "reference": "minor",
                              "pct": round(d[1], 3)})
                if cfg not in worst or d[1] > worst[cfg][0][1]:
                    worst[cfg] = (d, abi, w)
    _, _, w = worst["minor-nocache"]
    ys = [delta(a, "minor-nocache", w) for a in abis]
    ys = [y for y in ys if y]
    top = max(ys, key=lambda t: t[1])
    ax.annotate(f"{short(w)}, no tag cache:\n"
                f"{min(y[1] for y in ys):+.2f}% to {top[1]:+.2f}% cycles "
                "(all ABIs)", top, xytext=(-40, 0),
                textcoords="offset points", fontsize=5, ha="right",
                va="center", arrowprops={"arrowstyle": "-",
                                         "linewidth": 0.4})
    ax.text(0.42, max(noise),
            f"grey: passthrough, no tag traffic (timing noise) "
            f"{min(noise):+.2f}% to {max(noise):+.2f}%", ha="center",
            va="bottom", fontsize=4.8, color="#555555", zorder=2,
            transform=matplotlib.transforms.blended_transform_factory(
                ax.transAxes, ax.transData))
    f = lambda v, _: f"{v:+.0f}%"  # noqa: E731
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(f))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(f))
    ax.set_xlabel("DRAM traffic - increase over no tag model")
    ax.set_ylabel("CPU cycles - increase over no tag model")
    ax.grid(color="#c8c8c8", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo, hi + 0.6 * (hi - lo))
    cfg_h = [Patch(facecolor="white", edgecolor=c,
                   label=f"{l} (max {worst[k][0][1]:+.2f}%)")
             for k, l, c, _ in TAG_CONFIGS[1:]]
    abi_h = [Line2D([], [], marker=ABI_MARKER[a], linestyle="",
                    markerfacecolor="white", markeredgecolor="black",
                    markeredgewidth=0.7, label=ABI_NAME[a]) for a in abis]
    legend(ax, cfg_h + abi_h, f"Tag hardware cost, {suite} (Minor)", 2)
    save(fig, "tag_scatter")


def fig_regimes(res, abis, base, out, save, table):
    wls = sorted({w for (a, c, w) in res if c == "minor"}, key=short)
    fig, ax = plt.subplots(figsize=(3.5, 3.0))
    pts = {}
    for abi in abis:
        for w in wls:
            b, r = res.get((base, "minor", w)), res.get((abi, "minor", w))
            if not b or not r:
                continue
            x = 100 * (num(r, "insts") / num(b, "insts") - 1)
            y = 100 * (num(r, "cycles") / num(b, "cycles") - 1)
            pts[(abi, w)] = (x, y)
            table.append({"figure": "regimes", "abi": abi, "workload": w,
                          "config": "minor", "metric": "insts_pct",
                          "value": round(x, 3), "reference": base,
                          "pct": round(x, 3)})
            table.append({"figure": "regimes", "abi": abi, "workload": w,
                          "config": "minor", "metric": "cycles_pct",
                          "value": round(y, 3), "reference": base,
                          "pct": round(y, 3)})
    # a point far beyond all others (e.g. hybrid bh's memcpy) would squeeze
    # them into a corner: it is drawn on the border with its values
    mags = sorted((max(p) for p in pts.values()), reverse=True)
    cut = mags[1] * 1.6 if len(mags) > 1 and mags[0] > 2.5 * mags[1] \
        else None
    hi = (cut or mags[0]) * 1.12
    lo = min(0, min(min(p) for p in pts.values())) - 0.04 * hi
    labels = []
    for (abi, w), (x, y) in pts.items():
        off = cut is not None and max(x, y) > cut
        px, py = (min(x, hi * 0.96), min(y, hi * 0.96)) if off else (x, y)
        ax.scatter([px], [py], s=18, marker=ABI_MARKER[abi],
                   facecolor="white", edgecolor=STYLE[abi][0],
                   linewidth=0.8, zorder=3)
        if off:
            ax.annotate(f"{short(w)} ({ABI_NAME[abi]}), off scale:\n"
                        f"{x:+.0f}% insts, {y:+.0f}% cycles", (px, py),
                        xytext=(-2, -9), textcoords="offset points",
                        fontsize=5, ha="right", va="top")
        elif abi == "purecap":
            labels.append((x, y, short(w)))
    # spread labels of nearby points over four sides
    cand = [((3, 2), "left"), ((3, -7), "left"), ((-3, 2), "right"),
            ((-3, -7), "right")]
    placed = []
    for x, y, t in sorted(labels):
        near = [k for (px, py, k) in placed
                if abs(px - x) < 0.1 * hi and abs(py - y) < 0.1 * hi]
        k = next(i for i in range(len(cand)) if i not in near) \
            if len(near) < len(cand) else 0
        placed.append((x, y, k))
        ax.annotate(t, (x, y), xytext=cand[k][0], textcoords="offset points",
                    fontsize=5.5, ha=cand[k][1])
    ax.plot([lo, hi], [lo, hi], color="#ff0000", linestyle=(0, (4, 2)),
            linewidth=0.6, zorder=1)
    ax.text(hi * 0.62, hi * 0.62, "cycles = insts", rotation=45,
            ha="right", va="bottom", fontsize=5.5, color="#ff0000")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    f = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%")
    ax.xaxis.set_major_formatter(f)
    ax.yaxis.set_major_formatter(f)
    ax.set_xlabel(f"Instructions - overhead to {ABI_NAME[base]}")
    ax.set_ylabel(f"CPU cycles - overhead to {ABI_NAME[base]}")
    ax.grid(color="#c8c8c8", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    legend(ax, [Line2D([], [], marker=ABI_MARKER[a], linestyle="",
                       markerfacecolor="white", markeredgecolor=STYLE[a][0],
                       label=ABI_NAME[a]) for a in abis],
           "Minor CPU, per workload", len(abis))
    save(fig, "regimes")
    return pts


def pct1(v, _):
    """Tick label of a ratio as an overhead; a decimal only when needed."""
    p = 100 * (v - 1)
    return f"{p:+.0f}%" if abs(p - round(p)) < 1e-6 else f"{p:+.1f}%"


def fig_pareto(sweep_csv, base, out, save, table):
    rows = [r for r in csv.DictReader(open(sweep_csv)) if r["valid"] == "1"]
    pts_by_wl = {}
    for r in rows:
        pts_by_wl.setdefault(r["workload"], set()).add((r["l1d"], r["l2"]))
    wls = sorted((w for w, p in pts_by_wl.items() if len(p) > 1), key=short)
    if not wls:
        return
    col = f"cycles_vs_{base}_default"
    abis = ("plain", "hybrid", "purecap")

    def series(w, abi):
        return sorted(
            ((size_bytes(r["l1d"]) + size_bytes(r["l2"])) / 1024,
             float(r[col]), f"{r['l1d']}/{r['l2']}")
            for r in rows if r["workload"] == w and r["abi"] == abi
            and r[col] != "")

    data = {(w, abi): series(w, abi) for w in wls for abi in abis}
    # geometric mean over the workloads swept at every point (4+ workloads)
    panels = list(wls)
    if len(wls) >= 4:
        for abi in abis:
            per = [{p[2]: p for p in data[(w, abi)]} for w in wls]
            common = set.intersection(*(set(d) for d in per))
            data[("geomean", abi)] = sorted(
                (per[0][k][0], math.exp(sum(math.log(d[k][1]) for d in per)
                                        / len(per)), k) for k in common)
        panels.append("geomean")
    grid = len(panels) > 2
    ncols = 4 if grid else len(panels)
    nrows = -(-(len(panels) + grid) // ncols)
    fig, axs = plt.subplots(nrows, ncols,
                            figsize=(7.16, 1.75 * nrows if grid else 2.6),
                            squeeze=False,
                            gridspec_kw={"wspace": 0.3, "hspace": 0.35})
    flat = [ax for row in axs for ax in row]
    for ax, w in zip(flat, panels):
        for abi in abis:
            pts = data.get((w, abi))
            if not pts:
                continue
            c = STYLE[abi][0]
            ax.scatter([p[0] for p in pts], [p[1] for p in pts],
                       s=10 if grid else 16, marker=ABI_MARKER[abi],
                       facecolor="white", edgecolor=c, linewidth=0.7,
                       zorder=3)
            # Pareto front: points not beaten on both capacity and cycles
            front, best = [], math.inf
            for p in pts:
                if p[1] < best:
                    front.append(p)
                    best = p[1]
            ax.plot([p[0] for p in front], [p[1] for p in front], color=c,
                    linewidth=0.7, zorder=2)
            for p in pts:
                table.append({"figure": "sweep_pareto", "abi": abi,
                              "workload": w, "config": p[2],
                              "metric": "cycles_vs_default",
                              "value": p[1], "reference": base,
                              "pct": round(100 * (p[1] - 1), 3)})
                if abi == "purecap" and not grid:
                    # L2 points above the line, the L1D variants below it
                    l1d, l2 = p[2].split("/")
                    l2sweep = l1d == "16kB"
                    if not l2sweep and l1d != "64kB":
                        continue  # one label for the L1D variants
                    ax.annotate(f"L2 {l2}" if l2sweep else "L1D 32k, 64k",
                                (p[0], p[1]),
                                xytext=(2, 4) if l2sweep else (3, -7),
                                textcoords="offset points", fontsize=4.5)
        ax.axhline(1.0, color="#ff0000", linestyle=(0, (4, 2)),
                   linewidth=0.6, zorder=1)
        ax.set_xscale("log", base=2)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: f"{v / 1024:g}M" if v >= 1024 else f"{v:g}k"))
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        lo, hi = ax.get_ylim()
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(pct1))
        ax.grid(color="#c8c8c8", linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)
        if grid:
            ax.tick_params(labelsize=5)
            ax.set_ylim(lo, hi + 0.2 * (hi - lo))
            ax.text(0.97, 0.94, short(w), transform=ax.transAxes,
                    ha="right", va="top", fontsize=6.5,
                    bbox={"facecolor": "white", "edgecolor": "#bbbbbb",
                          "linewidth": 0.5, "pad": 1.5})
        else:
            ax.set_xlabel("On-chip data cache capacity, L1D + L2 (bytes)")
            ax.set_ylim(lo, hi + 0.45 * (hi - lo))
    handles = [Line2D([], [], marker=ABI_MARKER[a], color=STYLE[a][0],
                      markerfacecolor="white", linewidth=0.7,
                      label=ABI_NAME[a]) for a in abis]
    title = (f"CPU cycles (Minor) vs {ABI_NAME[base]} at 16kB L1D / "
             "256kB L2 (dashed)")
    if grid:
        for ax in flat[len(panels):]:
            ax.axis("off")
        leg_ax = flat[len(panels)]
        leg = leg_ax.legend(handles=handles, loc="center",
                            title=title.replace(" at ", "\nat "),
                            title_fontsize=6, fontsize=6, frameon=True,
                            fancybox=False, edgecolor="#bbbbbb")
        leg.get_frame().set_linewidth(0.5)
        leg_ax.text(0.5, 0.08, "x: on-chip data cache capacity,\n"
                    "L1D + L2 (bytes); lines: Pareto front",
                    transform=leg_ax.transAxes, ha="center", va="bottom",
                    fontsize=5.5)
    else:
        for ax, w in zip(flat, panels):
            legend(ax, handles, f"{short(w)}: {title}", 3)
        flat[0].set_ylabel("CPU cycles (Minor)")
    save(fig, "sweep_pareto")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("merged")
    ap.add_argument("--sweep")
    ap.add_argument("--abi", default="purecap")
    ap.add_argument("--baseline", default="plain")
    ap.add_argument("--out")
    ap.add_argument("--suite", default="CoreMark-PRO",
                    help="suite name in figure titles")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    out = a.out or os.path.join(a.merged, "plots")
    os.makedirs(out, exist_ok=True)
    style()

    def save(fig, name):
        fig.savefig(os.path.join(out, f"{name}.pdf"))
        if a.png:
            fig.savefig(os.path.join(out, f"{name}.png"), dpi=300)
        plt.close(fig)

    res = load(a.merged)
    table = []
    fig_tag_hw(res, a.abi, out, save, table)
    fig_tag_scatter(res, out, save, table, a.suite)
    fig_regimes(res, ["hybrid", "purecap"], a.baseline, out, save, table)
    if a.sweep:
        fig_pareto(a.sweep, a.baseline, out, save, table)
    with open(os.path.join(out, "insights.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"wrote {out}/: tag_hw_{a.abi}.pdf, tag_scatter.pdf, regimes.pdf"
          + (", sweep_pareto.pdf" if a.sweep else "") + ", insights.csv")


if __name__ == "__main__":
    main()
