#!/usr/bin/env python3
"""What runs before the measured region: the boot (and job setup).

(a) Per run of a boot-from-scratch experiment (run.py without
    --checkpoint): instructions committed before `m5 workbegin`, i.e. the
    CheriBSD boot plus the job's unpack/sync/sysctl, for each workload and
    ABI. Statistics are reset at workbegin, so this is gem5's simInsts
    (instructions since the simulation started, not reset) minus the
    region's instructions, taken from the region's stats dump.
(b) Instruction mix (gem5 op classes) of complete boots, either
    --boot: checkpoint creation runs (boot + unpacking every binary, never
    reset), one bar per checkpoint; or
    --boot-mix-runs: the per-run "[boot-stats]" dump of boot-from-scratch
    runs (parse.py boot_inst_* columns), one bar per (RESULTS_DIR, ABI),
    summed over its workloads; with CHERI_INST_PROFILE runs loads and
    stores are split into capability-width and integer ones.

Usage: util/cheri/boot_insts_plot.py --runs LABEL=RESULTS_DIR [--runs ...]
         [--boot LABEL=CKPT_STATS_TXT ... | --boot-mix-runs]
         [--abis plain,purecap]
         [--config minor] [--out DIR] [--png]
RESULTS_DIR holds all_stats.csv and results.csv (parse.py). Writes
boot_insts.pdf/.csv.
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

from overhead_bars import (ABI_LETTER, ABI_NAME, INST_CLASSES,  # noqa
                           INST_CLASSES_SPLIT, SHORT, STYLE, legend, style)

SWITCH = "board.processor.switch.core.commitStats0.numInsts"
START = "board.processor.start.core.commitStats0.committedInstType::"


def first_dump(path):
    d = {}
    for line in open(path):
        if line.startswith("---------- End"):
            break
        p = line.split()
        if len(p) >= 2:
            try:
                d[p[0]] = float(p[1])
            except ValueError:
                pass
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", action="append", required=True)
    ap.add_argument("--boot", action="append", default=[])
    ap.add_argument("--boot-mix-runs", action="store_true")
    ap.add_argument("--abis", default="plain,purecap")
    ap.add_argument("--config", default="minor")
    ap.add_argument("--out", default=".")
    ap.add_argument("--png", action="store_true")
    a = ap.parse_args()
    abis = a.abis.split(",")
    style()
    table = []

    groups = []
    for spec in a.runs:
        lbl, _, d = spec.partition("=")
        rows = {(r["abi"], r["workload"]): r for r in csv.DictReader(
            open(os.path.join(d, "all_stats.csv")))
            if r["config"] == a.config}
        wls = sorted({w for (_, w) in rows if all((x, w) in rows
                                                  for x in abis)},
                     key=lambda w: SHORT.get(w, w))
        pre = {}
        for w in wls:
            for abi in abis:
                r = rows[(abi, w)]
                v = float(r["simInsts"]) - float(r[SWITCH])
                pre[(abi, w)] = v
                table.append({"part": "pre_region", "suite": lbl,
                              "workload": w, "abi": abi,
                              "instructions": int(v)})
        groups.append((lbl, wls, pre))

    # panel (b) bars: (label, {inst_<class>: count}, classes)
    mixes = []
    for spec in a.boot:
        lbl, _, path = spec.partition("=")
        d = first_dump(path)
        mixes.append((lbl, {k: sum(d.get(START + k.replace("inst_", ""), 0)
                                   for k in cols)
                            for _, cols, _, _ in INST_CLASSES
                            for k in cols}, INST_CLASSES))
    if a.boot_mix_runs:
        for spec in a.runs:
            lbl, _, d = spec.partition("=")
            res = [r for r in csv.DictReader(
                open(os.path.join(d, "results.csv")))
                if r["config"] == a.config and r.get("boot_insts")]
            for abi in abis:
                rs = [r for r in res if r["abi"] == abi]
                if not rs:
                    continue
                split = all(r.get("boot_inst_cap_load") for r in rs)
                classes = INST_CLASSES_SPLIT if split else INST_CLASSES
                mix = {k: sum(float(r["boot_" + k] or 0) for r in rs)
                       for _, cols, _, _ in classes for k in cols}
                mixes.append((f"{lbl} {ABI_LETTER.get(abi, abi)}", mix,
                              classes))
    if not mixes and a.boot_mix_runs:
        sys.exit("no boot_inst_* columns: runs made with a checkpoint?")

    nb = len(mixes)
    fig, axs = plt.subplots(
        1, 2 if nb else 1, figsize=(7.16, 2.8), squeeze=False,
        gridspec_kw={"width_ratios": [6, 1.7] if nb else [1],
                     "wspace": 0.18})
    ax = axs[0][0]
    width = 0.8 / len(abis)
    x, ticks, labels = 0.0, [], []
    for gi, (lbl, wls, pre) in enumerate(groups):
        if gi:
            ax.axvline(x - 0.25, color="#9a9a9a", linewidth=4, alpha=0.6)
            x += 0.5
        ax.text(x - 0.4, 1.01, lbl, transform=ax.get_xaxis_transform(),
                fontsize=6.5, ha="left", va="bottom")
        for w in wls:
            for i, abi in enumerate(abis):
                col, hatch = STYLE[abi]
                ax.bar(x - 0.4 + width * (i + 0.5), pre[(abi, w)] / 1e6,
                       width * 0.9, facecolor="white", edgecolor=col,
                       hatch=hatch, linewidth=0.6, zorder=2)
            d = 100 * (pre[(abis[1], w)] / pre[(abis[0], w)] - 1)
            ax.text(x, pre[(abis[1], w)] / 1e6 * 1.01, f"{d:+.1f}%",
                    ha="center", va="bottom", fontsize=4.8, rotation=90)
            ticks.append(x)
            labels.append(SHORT.get(w, w).replace("_", "-"))
            x += 1.0
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=90)
    ax.set_xlim(-0.6, x - 0.4)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}M"))
    hi = max(v for _, _, pre in groups for v in pre.values()) / 1e6
    ax.set_ylim(0, hi * 1.45)
    legend(ax, [Patch(facecolor="white", edgecolor=STYLE[x][0],
                      hatch=STYLE[x][1], label=ABI_NAME[x]) for x in abis],
           "Instructions before the measured region (boot + job setup); "
           f"label: {ABI_NAME[abis[1]]} vs {ABI_NAME[abis[0]]}", len(abis))
    ax.text(0.995, 0.96, "(a)", transform=ax.transAxes, ha="right",
            va="top", fontsize=7)

    if nb:
        bx = axs[0][1]
        for i, (lbl, mix, classes) in enumerate(mixes):
            y = 0.0
            tot = sum(mix.values())
            for cls, cols, col, hatch in classes:
                v = sum(mix[k] for k in cols)
                pct = 100 * v / tot
                bx.bar(i, pct, 0.6, bottom=y, facecolor="white",
                       edgecolor=col, hatch=hatch, linewidth=0.5, zorder=2)
                table.append({"part": "boot_mix", "suite": lbl,
                              "workload": cls, "abi": "",
                              "instructions": int(v)})
                y += pct
            bx.text(i, 101, f"{tot / 1e9:.2f}G", ha="center", va="bottom",
                    fontsize=5)
        bx.set_xticks(range(nb))
        bx.set_xticklabels([m[0] for m in mixes], rotation=90)
        bx.tick_params(axis="x", length=0)
        bx.set_ylim(0, 175)
        bx.set_yticks(range(0, 101, 25))
        bx.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        bx.grid(axis="y", color="#c8c8c8", linewidth=0.5, zorder=0)
        bx.set_axisbelow(True)
        bx.legend(handles=[Patch(facecolor="white", edgecolor=c, hatch=h,
                                 label=l) for l, _, c, h in mixes[-1][2]],
                  loc="upper center", fontsize=4.3, ncol=2, frameon=True,
                  fancybox=False, edgecolor="#bbbbbb", handlelength=1.4,
                  columnspacing=0.5, handletextpad=0.4,
                  title="boot mix (checkpoint creation)" if a.boot
                  else "boot mix (boot + job setup)",
                  title_fontsize=4.8).get_frame().set_linewidth(0.5)
        bx.text(0.0, 1.01, "(b)", transform=bx.transAxes, ha="left",
                va="bottom", fontsize=7)

    os.makedirs(a.out, exist_ok=True)
    fig.savefig(os.path.join(a.out, "boot_insts.pdf"))
    if a.png:
        fig.savefig(os.path.join(a.out, "boot_insts.png"), dpi=300)
    with open(os.path.join(a.out, "boot_insts.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"wrote {a.out}/boot_insts.pdf, boot_insts.csv")


if __name__ == "__main__":
    main()
